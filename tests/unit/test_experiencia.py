from datetime import datetime, timezone
from pathlib import Path

import pytest

from jobradar.experiencia import required_years
from jobradar.filters import Catalog, Synonyms, evaluate
from jobradar.models import Exclusions, JobOffer, Search

DATA = Path(__file__).resolve().parents[2] / "src" / "jobradar" / "data"
SYN = Synonyms.from_files(DATA / "sinonimos.yaml", None)
CAT = Catalog.from_file(DATA / "catalogo.yaml")


@pytest.mark.parametrize("text, expected", [
    ("Requisitos: más de 2 años de experiencia en Python", 3),
    ("Se requiere +2 años de experiencia", 2),
    ("3+ years of experience with Python", 3),
    ("At least 2 years of professional experience", 2),
    ("Experiencia mínima: Al menos 3 años", 3),
    ("experiencia de 2 a 4 años en desarrollo", 2),
    ("2-4 años de experiencia demostrable", 2),
    ("Minimum of 5 years' experience", 5),
    ("Experience: 4+ years", 4),
    ("three years of relevant work experience", 3),
    ("Tienes un año de experiencia como mínimo", 1),
    ("5+ years in the same process family", 5),
    ("We have over 10 years of experience building products. You have 2+ years of experience", 2),
    ("Entre 2 y 4 años de experiencia", 2),
    ("between 2 and 4 years of experience", 2),
    ("Experiencia en Python (mínimo 2 años)", 2),
    ("Bring your 3+ years of experience", 3),
    ("Our client requires 3 years of experience", 3),
    ("5 años de experiencia en Java, se valorará Kotlin", 5),
    # los saltos de línea separan requisitos: "(valorable)" de una viñeta no anula la anterior
    ("3 años de experiencia en Java\nInglés (valorable)", 3),
    ("Requisitos:\n- 2 años de experiencia\n- Inglés B2 (valorable)", 2),
    # no cuentan: años de la empresa, contratos, cosas que solo se valoran
    ("0-2 years of experience", None),
    ("Valorable 1 año de experiencia", None),
    ("Empresa con más de 20 años de experiencia en el sector", None),
    ("Contamos con 10 años de experiencia", None),
    ("Contrato de 2 años", None),
    ("Requisitos: 1,5 años de experiencia", None),
    ("At least 2.5 years of experience", None),
    ("No se requiere ningún año de experiencia", None),
    ("25 days per year to work remotely", None),
    ("Did the work within the last 3 years", None),
    ("2 years of experience is a plus", None),
    ("Sin experiencia previa, te formamos", None),
    ("Experiencia mínima: No Requerida", None),
    (None, None),
])
def test_required_years(text, expected):
    assert required_years(text) == expected


def _offer(description):
    return JobOffer(title="Junior Data Analyst", url="https://e.invalid/1", source="t",
                    location="Madrid", description=description)


def _decide(description, **excl):
    s = Search(id="d", name="d", areas=["data"], estricta=True)
    return evaluate(_offer(description), [s], Exclusions(**excl), SYN, CAT, datetime.now(timezone.utc))


def test_descripcion_con_mas_experiencia_de_la_admitida_se_descarta():
    d = _decide("<p>Buscamos junior con 3+ años de experiencia en SQL.</p>", experiencia_max=2)
    assert not d.ok and "3 años de experiencia" in d.reasons[-1]


def test_sin_limite_o_dentro_del_limite_pasa():
    assert _decide("3+ años de experiencia").ok            # sin experiencia_max
    assert _decide("1 año de experiencia", experiencia_max=2).ok
    assert _decide(None, experiencia_max=2).ok              # sin descripción no se descarta


def test_palabra_excluida_en_la_descripcion():
    d = _decide("Se valora SAP y alemán nativo", en_descripcion=["alemán nativo"])
    assert not d.ok and "alemán nativo" in d.reasons[-1]
    assert _decide("Trabajo con Python y SQL", en_descripcion=["alemán nativo"]).ok


def test_json_ld_raro_no_rompe_y_se_lee_la_experiencia():
    from jobradar.sources.detalle import description_from_html
    raro = ('<script type="application/ld+json">{"@type": ["JobPosting"], "description": "Junior",'
            ' "experienceRequirements": {"monthsOfExperience": [24]}}</script>')
    assert description_from_html(raro) == "Junior"
    ok = raro.replace("[24]", "36")
    assert "3 years of experience" in description_from_html(ok)


def test_linkedin_comparte_tope_entre_subdominios():
    from jobradar.sources.detalle import budget_key, limit_for
    assert budget_key("https://es.linkedin.com/jobs/view/x") == budget_key("https://www.linkedin.com/jobs/view/y")
    assert limit_for("https://es.linkedin.com/jobs/view/x") == 5
    assert limit_for("https://www.tecnoempleo.com/x") > 5


def test_aviso_muestra_los_anos_que_piden():
    from types import SimpleNamespace

    from jobradar import notify
    job = SimpleNamespace(id=1, title="Junior Data Analyst", company="Acme", location="Madrid",
                          modality=None, priority="alta", description="Buscamos 2+ años de experiencia")
    assert "🎓 Piden 2 años de experiencia" in notify.format_job(job, [], [])
    job.description = "Sin requisitos"
    assert "🎓" not in notify.format_job(job, [], [])


def test_master_data_analyst_ya_no_se_excluye():
    from jobradar.models import Exclusions
    s = Search(id="d", name="d", areas=["data"], estricta=True)
    ok = evaluate(JobOffer(title="Master Data Analyst", url="https://e.invalid/2", source="t"),
                  [s], Exclusions(), SYN, CAT, datetime.now(timezone.utc))
    no = evaluate(JobOffer(title="Master Data Management Specialist", url="https://e.invalid/3", source="t"),
                  [s], Exclusions(), SYN, CAT, datetime.now(timezone.utc))
    assert ok.ok and not no.ok


def test_probar_con_descripcion(tmp_path):
    from jobradar import radar
    from jobradar.paths import Paths
    paths = Paths(tmp_path)
    from jobradar.config import save_searches
    save_searches(paths.searches, [Search(id="b1", name="B", areas=["data"], estricta=True)],
                  Exclusions(experiencia_max=2))
    assert radar.probe(paths, "Junior Data Analyst").ok
    assert not radar.probe(paths, "Junior Data Analyst", description="3+ años de experiencia").ok


def test_modalidad_desde_la_descripcion():
    from jobradar.modalidad import modality_from_text as m
    assert m("Puesto 100% remoto desde España") == "remoto"
    assert m("Modelo híbrido: 3 días a la semana en oficina") == "hibrido"
    assert m("Trabajo presencial en Madrid") == "presencial"
    assert m("Posibilidad de teletrabajo ocasional") is None       # ambiguo: no se adivina
    assert m("No es un puesto presencial") is None
    assert m("We work with remote teams") is None
    assert m(None) is None


def test_ciudad_sin_modalidad_no_vale_como_remota():
    s = Search(id="r", name="remoto", areas=["data"], modalidades=["remoto"], ubicaciones=["espana"], estricta=True)
    now = datetime.now(timezone.utc)

    def decide(**kw):
        offer = JobOffer(title="Junior Data Analyst", url="https://e.invalid/9", source="t", **kw)
        return evaluate(offer, [s], Exclusions(), SYN, CAT, now)
    assert not decide(location="Madrid").ok
    assert decide(location="España").ok                  # ubicación genérica: ante la duda, pasa
    assert decide(location="Madrid", modality="remoto").ok
    assert decide(location="Madrid", description="Puesto 100% remoto").ok
