from datetime import datetime, timedelta, timezone

from jobradar.models import Decision, JobOffer
from jobradar.store import Store

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def o(title, url, **kw):
    return JobOffer(title=title, url=url, source="s", company="Acme", **kw)


def test_ciclo_completo():
    s = Store(":memory:")
    r = s.upsert([o("Becario Data", "https://a.com/1", location="Granada", category="IT",
                    posted_at=NOW - timedelta(days=1))], NOW)
    job = r.new_jobs[0]
    view = job.offer_view()
    assert view.title == "Becario Data" and view.category == "IT" and view.url == "https://a.com/1"
    s.set_decision(job.id, Decision(matched=["b1"], priority="alta", reasons=["encaja"]))
    j = s.get_job(job.id)
    assert j.status == "avisada" and j.matched_searches == ["b1"] and j.reasons == ["encaja"]
    s.mark_notified(job.id, 42, NOW)
    assert s.get_job(job.id).tg_message_id == 42
    assert len(s.recent(7, NOW, status="avisada")) == 1


def test_descartadas_y_ventanas():
    s = Store(":memory:")
    s.upsert([o("Contable", "https://a.com/1")], NOW - timedelta(hours=30))
    s.upsert([o("Cocinero", "https://a.com/2")], NOW - timedelta(hours=2))
    for j in s.jobs_since(3, NOW):
        s.set_decision(j.id, Decision(matched=[], reasons=["ninguna"]))
    assert [j.title for j in s.discarded(24, NOW)] == ["Cocinero"]
    assert len(s.jobs_since(3, NOW)) == 2


def test_runs_y_watch():
    s = Store(":memory:")
    s.record_run("x", NOW, True, 10, 95.0)
    s.record_run("x", NOW + timedelta(hours=1), False, 0, None, "boom")
    runs = s.last_runs("x", 5)
    assert runs[0]["error"] == "boom" and runs[0]["ok"] is False and runs[1]["count"] == 10
    assert s.watch_is_new("w", "h1", NOW) is True
    assert s.watch_is_new("w", "h1", NOW) is False


def test_fusion_ventana_30_dias():
    s = Store(":memory:")
    s.upsert([o("Trainee Java", "https://a.com/1")], NOW - timedelta(days=40))
    r = s.upsert([o("Trainee Java 2", "https://a.com/2")], NOW)  # distinta clave y fuera de ventana
    assert len(r.new_jobs) == 1


def test_pending_digest_only_unnotified_matches():
    s = Store(":memory:")
    res = s.upsert([JobOffer(title=f"Becario {n}", url=f"https://a.com/{n}", source="x", company=f"C{n}")
                    for n in "abc"], NOW)
    a, b, c = (j.id for j in res.new_jobs)
    s.set_decision(a, Decision(matched=["s"], priority="alta", reasons=[]))
    s.set_decision(b, Decision(matched=["s"], priority="normal", reasons=[]))
    s.set_decision(c, Decision(matched=[], reasons=["no"]))
    s.mark_notified(a, 1, NOW)
    assert [j.id for j in s.pending_digest()] == [b]
