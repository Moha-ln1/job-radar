from datetime import datetime, timezone
from types import SimpleNamespace

from jobradar import notify
from jobradar.models import Search

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def job(**kw):
    base = dict(id=1, title="Becario <Dev> & Co", company="Acme & Sons", location="Granada",
                modality="hibrido", priority="alta", matched_searches=["b1"])
    return SimpleNamespace(**(base | kw))


def posting(source, url):
    return SimpleNamespace(source=source, url=url)


def test_format_job_escapes_html_and_links():
    text = notify.format_job(job(), [posting("linkedin", "https://l.com/1?a=1&b=2"),
                                     posting("infojobs", "https://i.com/2")], ["Mi búsqueda"])
    assert text.startswith("🔥 <b>Becario &lt;Dev&gt; &amp; Co</b> — Acme &amp; Sons · Granada (híbrido)")
    assert "🔎 Búsqueda: Mi búsqueda" in text
    assert '<a href="https://l.com/1?a=1&amp;b=2">LinkedIn</a> · <a href="https://i.com/2">InfoJobs</a>' in text


def test_format_job_normal_priority_and_remoteok():
    text = notify.format_job(job(priority="normal", company=None, location=None, modality=None),
                             [posting("remoteok", "https://r.com/1")], [])
    assert text.startswith("📰 <b>")
    assert "vía RemoteOK" in text and "Búsqueda" not in text


def test_source_labels():
    assert notify.source_label("greenhouse:gitlab") == "Greenhouse"
    assert notify.source_label("watch:Factoría F5") == "Factoría F5"
    assert notify.source_label("tecnoempleo") == "Tecnoempleo"
    assert notify.source_label("algo") == "Algo"


def test_digest_chunks_under_limit():
    items = [(job(id=i, title=f"Becario número {i} " + "x" * 150), [posting("linkedin", f"https://l.com/{i}")],
              ["Búsqueda"]) for i in range(80)]
    messages = notify.format_digest(items)
    assert len(messages) > 1
    assert all(len(m) <= 4096 for m in messages)
    assert sum(m.count("Becario número") for m in messages) == 80
    assert notify.format_digest([]) == []


def test_digest_huge_block_is_compacted():
    giant = [posting("linkedin", "https://l.com/" + "a" * 5000)]
    messages = notify.format_digest([(job(), giant * 3, [])])
    assert all(len(m) <= 4096 for m in messages)


def test_new_portal_health_status_summary():
    assert notify.format_new_portal("infojobs") == "➕ También en InfoJobs"
    assert "&lt;b&gt;" in notify.format_health(["fuente <b>"])
    status = notify.format_status([{"source": "linkedin", "ts": NOW, "ok": True, "count": 5, "filled_pct": 80.0},
                                   {"source": "x", "ts": None}], NOW, NOW)
    assert "linkedin" in status and "OK" in status and "nunca" in status and "Silenciado" in status
    report = SimpleNamespace(new_jobs=[1, 2, 3], new_matched=[job(), job(priority="normal")],
                             new_discarded=1, source_status={"a": SimpleNamespace(error="roto")})
    summary = notify.format_summary(report)
    assert "3 ofertas nuevas" in summary and "roto" in summary


def test_keyboard_callback_data_short():
    kb = notify.job_keyboard(2 ** 40)
    data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert data == [f"h:{2 ** 40}", f"n:{2 ** 40}"]
    assert all(len(d.encode()) <= 64 for d in data)


def test_search_names():
    s = [Search(id="b1", name="Prácticas")]
    assert notify.search_names(job(matched_searches=["b1", "watch", "viejo"]), s) == ["Prácticas", "Página vigilada"]
