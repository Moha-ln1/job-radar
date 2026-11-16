"""Conjunto de referencia (docs/ARQUITECTURA.md 1.1.7): recall 100 %, precisión solo informativa."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from jobradar.filters import Catalog, Synonyms, evaluate
from jobradar.models import Exclusions, Search, build_offer

DATA = Path(__file__).resolve().parents[2] / "src" / "jobradar" / "data"
SYN = Synonyms.from_files(DATA / "sinonimos.yaml", None)
CAT = Catalog.from_file(DATA / "catalogo.yaml")
# Fecha fija = oferta más reciente (2026-11-16) + 1 día: el test no caduca.
NOW = datetime(2026, 11, 17, 2, 47, 54, tzinfo=timezone.utc)

SEARCHES = [
    Search(id="A", name="Academies tech", tipos=["practicas", "trainee", "bootcamp"],
           ubicaciones=["granada", "andalucia"], modalidades=[], prioridad="alta"),
    Search(id="J", name="Junior dev", tipos=["junior"], areas=["programador", "data"],
           modalidades=["remoto"], prioridad="normal"),
]
EXCL = Exclusions(words=["senior", "lead", "director"])


def _load():
    rows = yaml.safe_load((Path(__file__).parent / "titulos.yaml").read_text(encoding="utf-8"))
    results = []
    for i, r in enumerate(rows):
        fields = {k: r.get(k) for k in ("source", "title", "company", "location", "modality",
                                       "remote_region", "category", "posted_at")}
        offer = build_offer(url=f"https://example.com/job/{i}", **fields)
        assert offer is not None, f"oferta inválida en el conjunto: {r['title']}"
        # build_offer descarta fechas > 1 año respecto a la hora real: restauramos la del fichero
        if r.get("posted_at") and offer.posted_at is None:
            offer = offer.model_copy(update={"posted_at": r["posted_at"]})
        d = evaluate(offer, SEARCHES, EXCL, SYN, CAT, NOW)
        results.append((r, offer, d))
    return results


RESULTS = _load()


def test_tamano_minimo():
    assert len(RESULTS) >= 150


def test_precision_informativa(capsys):
    neg = [(r, d) for r, _, d in RESULTS if not r["expected"]]
    fp = [(r, d) for r, d in neg if d.ok]
    pos = [(r, d) for r, _, d in RESULTS if r["expected"]]
    tp = [1 for r, d in pos if d.ok]
    with capsys.disabled():
        print(f"\nPRECISION: {len(tp)}/{len(tp) + len(fp)} = "
              f"{len(tp) / max(1, len(tp) + len(fp)):.1%}; "
              f"expected=false que encajan: {len(fp)}/{len(neg)}")
        for r, d in fp:
            print(f"  FP: {r['title']} | {d.reasons[:1]}")


def test_recall_100():
    missed = [(r, d) for r, _, d in RESULTS if r["expected"] and not d.ok]
    msg = "\n".join(
        f"- {r['title']} | {r['location']} | {r['modality']} | {'; '.join(d.reasons)}"
        for r, d in missed)
    assert not missed, f"{len(missed)} ofertas esperadas descartadas:\n{msg}"
