from datetime import datetime, timedelta, timezone

from jobradar import health
from jobradar.models import JobOffer
from jobradar.paths import Paths
from jobradar.radar import SourceResult
from jobradar.store import Store

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def full(i):
    return JobOffer(title=f"Becario {i}", url=f"https://a.com/{i}", source="s", company="Acme",
                    location="Granada", posted_at=NOW)


def bare(i):
    return JobOffer(title=f"Becario {i}", url=f"https://a.com/{i}", source="s")


def seeded(name="x", n=5, count=10, pct=100.0):
    s = Store(":memory:")
    for i in range(n):
        s.record_run(name, NOW - timedelta(hours=n - i), True, count, pct)
    return s


def test_filled_pct():
    assert health.filled_pct([]) == 0
    assert health.filled_pct([full(1), bare(2)]) == 50


def test_cero_ofertas_alerta_y_no_repite(tmp_path):
    paths, s = Paths(tmp_path), seeded()
    msg = health.check(s, "x", SourceResult("x"), NOW, paths)
    assert msg and "x" in msg
    assert health.check(s, "x", SourceResult("x"), NOW + timedelta(hours=2), paths) is None
    assert health.check(s, "x", SourceResult("x"), NOW + timedelta(days=1), paths)


def test_error_alerta(tmp_path):
    msg = health.check(seeded(), "x", SourceResult("x", error="HTTP 500"), NOW, Paths(tmp_path))
    assert msg and "HTTP 500" in msg


def test_caida_de_campos_rellenos(tmp_path):
    msg = health.check(seeded(n=3, count=5), "x", SourceResult("x", offers=[bare(1), bare(2)]),
                       NOW, Paths(tmp_path))
    assert msg and "rellena menos" in msg


def test_sin_alerta_si_todo_normal(tmp_path):
    assert health.check(seeded(), "x", SourceResult("x", offers=[full(1)]), NOW, Paths(tmp_path)) is None
    assert health.check(Store(":memory:"), "n", SourceResult("n"), NOW, Paths(tmp_path)) is None
