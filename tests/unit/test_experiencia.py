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
    # no cuentan: años de la empresa, contratos, cosas que solo se valoran
    ("0-2 years of experience", None),
    ("Valorable 1 año de experiencia", None),
    ("Empresa con más de 20 años de experiencia en el sector", None),
    ("Contamos con 10 años de experiencia", None),
    ("Contrato de 2 años", None),
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
