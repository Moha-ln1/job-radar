"""Regresiones de recall de recall: ofertas válidas que en algún momento se descartaban."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jobradar.filters import Catalog, Synonyms, evaluate
from jobradar.models import Exclusions, Search, build_offer

DATA = Path(__file__).resolve().parents[2] / "src" / "jobradar" / "data"
SYN = Synonyms.from_files(DATA / "sinonimos.yaml", None)
CAT = Catalog.from_file(DATA / "catalogo.yaml")
ACADEMIES = Search(id="a", name="Academies", tipos=["practicas", "trainee", "bootcamp"],
                   ubicaciones=["granada", "andalucia"])
JUNIOR_REMOTO = Search(id="j", name="Junior", tipos=["junior"], areas=["programador"],
                       modalidades=["remoto"])


def _ok(title, location=None, modality=None, searches=(ACADEMIES,)):
    offer = build_offer(title=title, url="https://e.com/1", source="t", company="X",
                        location=location, modality=modality)
    return evaluate(offer, list(searches), Exclusions(words=["senior", "lead"]), SYN, CAT,
                    datetime.now(timezone.utc)).ok


@pytest.mark.parametrize("title", [
    "Programa de Talento Joven - Ingeniería",
    "Recién titulado ingeniería",
    "New Grad SWE 2027",
    "Early Careers Programme - Software",
])
def test_trainee_sinonimos_completos(title):
    assert _ok(title, location="Granada")


def test_region_us_only_en_ubicacion_no_pasa():
    assert not _ok("Junior Python Engineer", "Remote (US only)", "remoto", (JUNIOR_REMOTO,))


def test_region_europa_en_ubicacion_pasa():
    assert _ok("Junior Backend Developer", "Remote - Europe", "remoto", (JUNIOR_REMOTO,))


def test_remoto_sin_region_pasa():
    assert _ok("Junior Backend Developer", "Remote", "remoto", (JUNIOR_REMOTO,))
