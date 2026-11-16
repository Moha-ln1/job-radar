import logging
from datetime import datetime, timedelta, timezone

from jobradar.models import Decision, JobOffer, build_offer


def ok(**kw):
    base = dict(title="Becario Data", url="https://x.com/job/1", source="x", company="Acme")
    return build_offer(**{**base, **kw})


def test_valida_y_limpia():
    o = ok(title="  Becario   &amp; Data ", url="https://x.com/job/1?utm_source=a&id=7&trk=z&ref=q")
    assert o.title == "Becario & Data"
    assert o.url == "https://x.com/job/1?id=7"


def test_rechazos(caplog):
    with caplog.at_level(logging.WARNING, logger="jobradar.extract"):
        assert ok(title="<b>Becario</b> Data") is None
        assert ok(url="/job/1") is None
        assert ok(url="https://otro.com/1", expected_domains={"x.com"}) is None
        assert ok(title="Acme", company="ACME") is None
        assert ok(title="ab") is None
    assert len(caplog.records) == 5


def test_dominio_con_subdominio():
    assert ok(url="https://es.x.com/1", expected_domains={"x.com"}) is not None


def test_fechas():
    now = datetime.now(timezone.utc)
    assert ok(posted_at=now + timedelta(days=5)).posted_at is None
    assert ok(posted_at=now - timedelta(days=400)).posted_at is None
    assert ok(posted_at=now - timedelta(days=3)).posted_at is not None


def test_description_no_se_rechaza():
    o = JobOffer(title="Becario", url="https://x.com/1", source="x", description="<p>Hola</p>")
    assert o.description == "<p>Hola</p>"


def test_decision_ok():
    assert Decision(matched=["a"], priority="alta", reasons=[]).ok
    assert not Decision(matched=[], reasons=["x"]).ok


def test_repara_texto_doblemente_codificado():
    from jobradar.models import build_offer
    o = build_offer(title="Ingeniero en MÃ¼nchen", url="https://e.com/1", source="remoteok",
                    location="Ciudad de MÃ©xico, Mexico")
    assert o.title == "Ingeniero en München" and o.location == "Ciudad de México, Mexico"
    assert build_offer(title="Ãrea técnica", url="https://e.com/2", source="x").title == "Ãrea técnica"
