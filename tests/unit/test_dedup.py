from datetime import datetime, timezone

from jobradar.dedup import SIMILARITY, job_key, similar
from jobradar.models import JobOffer
from jobradar.store import Store

NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def offer(title, company, url, source="a"):
    return JobOffer(title=title, company=company, url=url, source=source)


def test_job_key_y_similar():
    assert job_key("Trainee Java (H/M)", "NTT DATA Spain S.L.") == "ntt data|trainee java"
    assert SIMILARITY == 0.90
    assert similar("Java Trainee", "Trainee Java") == 1.0
    assert similar("Trainee Java", "Trainee QA") < SIMILARITY


def test_fusion_misma_oferta_dos_fuentes():
    s = Store(":memory:")
    r = s.upsert([offer("Trainee Java (H/M)", "NTT DATA Spain S.L.", "https://a.com/1"),
                  offer("Trainee Java", "NTT Data", "https://b.com/2", "b")], NOW)
    assert len(r.new_jobs) == 1 and r.new_postings == []
    assert len(s.postings(r.new_jobs[0].id)) == 2
    r2 = s.upsert([offer("Trainee Java", "NTT Data", "https://c.com/3", "c")], NOW)
    assert r2.new_jobs == [] and len(r2.new_postings) == 1


def test_titulos_distintos_no_se_fusionan():
    s = Store(":memory:")
    r = s.upsert([offer("Trainee Java", "NTT Data", "https://a.com/1"),
                  offer("Trainee QA", "NTT Data", "https://a.com/2")], NOW)
    assert len(r.new_jobs) == 2


def test_sin_empresa_no_fusiona():
    s = Store(":memory:")
    r = s.upsert([offer("Trainee Java", None, "https://a.com/1"),
                  offer("Trainee Java", None, "https://a.com/2")], NOW)
    assert len(r.new_jobs) == 2


def test_misma_url_dos_veces():
    s = Store(":memory:")
    s.upsert([offer("Trainee Java", "Acme", "https://a.com/1")], NOW)
    r = s.upsert([offer("Trainee Java", "Acme", "https://a.com/1")], NOW)
    assert r.new_jobs == [] and r.new_postings == []
    assert len(s.postings(1)) == 1
