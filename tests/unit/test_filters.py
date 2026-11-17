from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jobradar.filters import Catalog, Synonyms, detect_modality, evaluate
from jobradar.models import Exclusions, JobOffer, Search

DATA = Path(__file__).resolve().parents[2] / "src" / "jobradar" / "data"
SYN = Synonyms.from_files(DATA / "sinonimos.yaml", None)
CAT = Catalog.from_file(DATA / "catalogo.yaml")
NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def offer(title, **kw):
    return JobOffer(**{"title": title, "url": "https://x.com/1", "source": "x", "company": "Acme", **kw})


def ev(o, searches, excl=None, **kw):
    return evaluate(o, searches, excl or Exclusions(), SYN, CAT, NOW, **kw)


PRAC = [Search(id="p", name="Prácticas", tipos=["practicas"])]


@pytest.mark.parametrize("title,expected", [
    ("Software Engineering Intern", True),
    ("Becaria Data", True),
    ("Prácticas en Marketing", True),
    ("International Sales Manager", False),
    ("Internal Audit", False),
])
def test_tipo_practicas(title, expected):
    assert ev(offer(title), PRAC).ok is expected


def test_descripcion_no_cuenta_pero_categoria_si():
    assert not ev(offer("Analista", description="Aplicarás buenas prácticas"), PRAC).ok
    trainee = [Search(id="t", name="T", tipos=["trainee"])]
    assert ev(offer("Analista", category="Trainee"), trainee).ok


def test_exclusion_senior_y_caso_ambiguo():
    ex = Exclusions(words=["senior"])
    jr = [Search(id="j", name="J", tipos=["junior"])]
    d = ev(offer("Senior Java Developer"), jr, ex)
    assert not d.ok and "senior" in d.reasons[0]
    d = ev(offer("Junior/Senior Developer"), jr, ex)
    assert d.ok and any("caso ambiguo" in r for r in d.reasons)


def test_exclusion_de_palabra_de_area_no_arrastra_su_grupo():
    ex = Exclusions(words=["arquitecto"])
    todo = [Search(id="a", name="A", tipos=["cualquiera"])]
    assert not ev(offer("Arquitecta de software"), todo, ex).ok
    assert ev(offer("Técnico instalador de climatización"), todo, ex).ok
    assert ev(offer("Fontanero"), todo, ex).ok


def test_exclusion_empresa_por_nombre_normalizado():
    d = ev(offer("Becario Data", company="NTT Data Spain S.L."), PRAC,
           Exclusions(companies=["NTT Data"]))
    assert not d.ok and "empresa" in d.reasons[0]


def test_tipo_junior_y_area_programador():
    s = [Search(id="s", name="JP", tipos=["junior"], areas=["programador"])]
    assert ev(offer("Desarrollador/a Junior"), s).ok
    assert not ev(offer("Junior Marketing Specialist"), s).ok


def test_remoto_regiones():
    s = [Search(id="s", name="R", modalidades=["remoto"], ubicaciones=["espana"])]
    assert not ev(offer("Becario", modality="remoto", remote_region="US only"), s).ok
    assert not ev(offer("Becario", modality="remoto", remote_region="Americas"), s).ok
    assert ev(offer("Becario", modality="remoto", remote_region="Europe"), s).ok
    assert ev(offer("Becario", modality="remoto", remote_region="Europe, US"), s).ok
    assert ev(offer("Becario", modality="remoto"), s).ok
    assert ev(offer("Becario", modality="remoto", remote_region="Narnia"), s).ok


def test_desconocidos_pasan():
    s = [Search(id="s", name="X", modalidades=["presencial"], ubicaciones=["granada"])]
    assert ev(offer("Becario"), s).ok
    assert ev(offer("Becario", location="Granada"), s).ok


def test_antiguedad():
    old = offer("Becario", posted_at=NOW - timedelta(days=20))
    d = ev(old, PRAC, max_age_days=14)
    assert not d.ok and "antigua" in d.reasons[0]
    assert ev(old, PRAC, max_age_days=30).ok


def test_ubicacion_alias_y_motivo():
    s = [Search(id="g", name="Granada", ubicaciones=["granada"])]
    assert ev(offer("Becario", location="Armilla, Granada"), s).ok
    d = ev(offer("Becario", location="Madrid"), s)
    assert not d.ok and "Madrid" in d.reasons[0] and "granada" in d.reasons[0]
    sp = [Search(id="e", name="España", ubicaciones=["espana"])]
    assert ev(offer("Becario", location="Valladolid"), sp).ok


def test_modalidad_detectada_del_titulo():
    assert detect_modality(offer("Becario (Remoto)"), SYN) == "remoto"
    assert detect_modality(offer("Becario", location="Madrid"), SYN) is None
    s = [Search(id="s", name="P", modalidades=["presencial"])]
    assert not ev(offer("Becario remoto"), s).ok


def test_prioridad_y_pausa():
    s = [Search(id="a", name="A", tipos=["practicas"], prioridad="normal"),
         Search(id="b", name="B", tipos=["practicas"], prioridad="alta"),
         Search(id="c", name="C", tipos=["practicas"], paused=True)]
    d = ev(offer("Intern"), s)
    assert d.matched == ["a", "b"] and d.priority == "alta"
    assert d.reasons[0] == "encaja con 'A': tipo 'Prácticas' (intern)"


def test_sinonimos():
    assert "intern" in SYN.expand("prácticas")
    assert SYN.expand("zzz") == ["zzz"]
    assert SYN.pattern("practicas") is SYN.pattern("practicas")
    assert SYN.pattern("becario").search("becarias en ti")
    assert SYN.pattern("work placement").search("work-placement 2027")


# --- grupos propios y búsqueda estricta ---
def _user_syn(tmp_path):
    user = tmp_path / "sinonimos_usuario.yaml"
    user.write_text("python:\n  - python\n  - django\nia:\n  - ia\n  - machine learning\n  - llm\n",
                    encoding="utf-8")
    return Synonyms.from_files(DATA / "sinonimos.yaml", user)


def test_grupo_propio_no_arrastra_el_grupo_donde_ya_estaba(tmp_path):
    syn = _user_syn(tmp_path)
    assert "developer" not in syn.expand("python")  # "python" también está en programador
    assert syn.search("python", "django backend") and not syn.search("python", "java developer")


def test_siglas_sin_variantes_de_genero():
    assert SYN.search("data", "ia generativa") and not SYN.search("data", "developer ios android")


@pytest.mark.parametrize("title", [
    "Junior Data Analyst", "Becario Data Science", "Prácticas analista de datos", "Junior BI Developer",
    "Deep Learning Engineer Intern", "DL Researcher junior", "Junior ML Engineer", "Junior Data Engineer",
    "NLP Engineer junior", "Becario/a Power BI", "Prácticas en IA generativa",
])
def test_area_datos_ia_cubre_analisis_ciencia_e_ia(title):
    assert _ok(title, Search(id="d", name="d", areas=["data"], estricta=True), SYN)


@pytest.mark.parametrize("title", [
    "Data Entry Clerk junior", "Técnico de Protección de Datos junior", "Data Center Technician junior",
    "Prácticas grabación de datos", "Master Data Specialist junior", "Desarrollador iOS junior",
])
def test_area_datos_ia_no_confunde_datos_sueltos(title):
    assert not _ok(title, Search(id="d", name="d", areas=["data"], estricta=True), SYN)


def _ok(title, search, syn, category=None):
    offer = JobOffer(title=title, url="https://e.invalid/1", source="t", category=category)
    return evaluate(offer, [search], Exclusions(), syn, CAT, datetime.now(timezone.utc)).ok


def test_busqueda_estricta_exige_el_area_en_el_titulo(tmp_path):
    syn = _user_syn(tmp_path)
    laxa = Search(id="a", name="a", tipos=["practicas"], areas=["python", "ia"])
    estricta = laxa.model_copy(update={"estricta": True})
    sin_area = "Estudiante en prácticas departamento TEF7"
    assert _ok(sin_area, laxa, syn) and not _ok(sin_area, estricta, syn)
    assert _ok("Prácticas Machine Learning", estricta, syn)
    assert _ok("Becario/a desarrollo Python", estricta, syn)
    # la categoría del portal no cuenta en la estricta: "Data & AI" no hace de IA un puesto de analista
    assert not _ok("Prácticas Business Analyst", estricta, syn, category="Data & AI")
