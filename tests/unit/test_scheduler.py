import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jobradar import radar, scheduler
from jobradar.config import save_searches
from jobradar.models import Decision, Exclusions, JobOffer, Search
from jobradar.paths import Paths
from jobradar.radar import ScanReport
from jobradar.store import Store

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


@pytest.fixture
def paths(tmp_path):
    save_searches(tmp_path / "busquedas.yaml", [Search(id="b1", name="Prácticas")], Exclusions())
    return Paths(tmp_path)


def make_app(paths):
    bot = AsyncMock()
    bot.send_message.return_value = SimpleNamespace(message_id=77)
    return SimpleNamespace(bot=bot, bot_data={"chat_id": 5, "paths": paths})


def seed(paths, title, priority):
    store = Store(paths.db)
    res = store.upsert([JobOffer(title=title, url=f"https://a.com/{title}", source="linkedin",
                                 company="Acme")], NOW)
    job = res.new_jobs[0]
    store.set_decision(job.id, Decision(matched=["b1"], priority=priority, reasons=["ok"]))
    job = store.get_job(job.id)
    store.close()
    return job


def fake_scan(monkeypatch, jobs, portals=(), alerts=()):
    async def scan(paths, now=None, **kw):
        return ScanReport(new_matched=list(jobs), new_jobs=list(jobs),
                          new_postings_for_notified=list(portals), health_alerts=list(alerts))
    monkeypatch.setattr(radar, "scan", scan)


async def test_alta_is_sent_normal_waits_for_digest(paths, monkeypatch):
    alta, normal = seed(paths, "Alta", "alta"), seed(paths, "Normal", "normal")
    fake_scan(monkeypatch, [alta, normal], alerts=["fuente rota"])
    app = make_app(paths)
    await scheduler.cycle(app, paths, NOW)
    texts = [c.kwargs["text"] for c in app.bot.send_message.await_args_list]
    assert len(texts) == 2 and "Alta" in texts[0] and "fuente rota" in texts[1]
    store = Store(paths.db)
    assert store.get_job(alta.id).tg_message_id == 77
    assert [j.id for j in store.pending_digest()] == [normal.id]
    store.close()
    assert scheduler.last_scan(paths) == NOW

    app.bot.send_message.reset_mock()
    assert await scheduler.send_digest(app.bot, 5, paths, NOW) == 1
    assert "Normal" in app.bot.send_message.await_args.kwargs["text"]
    assert await scheduler.send_digest(app.bot, 5, paths, NOW) == 0


async def test_silence_sends_nothing_until_digest(paths, monkeypatch):
    alta = seed(paths, "Alta", "alta")
    fake_scan(monkeypatch, [alta])
    scheduler.update_state(paths, silence_until=(datetime.now(timezone.utc) + timedelta(hours=5)).isoformat())
    app = make_app(paths)
    await scheduler.cycle(app, paths)
    app.bot.send_message.assert_not_called()
    assert await scheduler.send_digest(app.bot, 5, paths) == 0  # sigue en silencio
    assert await scheduler.send_digest(app.bot, 5, paths, force=True) == 1


async def test_quiet_first_run_goes_to_digest(paths, monkeypatch):
    fake_scan(monkeypatch, [seed(paths, "Alta", "alta")])
    app = make_app(paths)
    await scheduler.cycle(app, paths, NOW, quiet=True)
    app.bot.send_message.assert_not_called()


async def test_send_failure_keeps_job_pending(paths, monkeypatch):
    alta = seed(paths, "Alta", "alta")
    fake_scan(monkeypatch, [alta])
    app = make_app(paths)
    app.bot.send_message.side_effect = RuntimeError("red caída")
    await scheduler.cycle(app, paths, NOW)
    store = Store(paths.db)
    assert [j.id for j in store.pending_digest()] == [alta.id]
    store.close()


async def test_new_portal_edits_original(paths, monkeypatch):
    job = seed(paths, "Alta", "alta")
    store = Store(paths.db)
    store.mark_notified(job.id, 10, NOW)
    res = store.upsert([JobOffer(title="Alta", url="https://b.com/x", source="infojobs", company="Acme")], NOW)
    (j, p), = res.new_postings
    store.close()
    fake_scan(monkeypatch, [], portals=[(j, p)])
    app = make_app(paths)
    await scheduler.cycle(app, paths, NOW)
    edit = app.bot.edit_message_text.await_args.kwargs
    assert edit["message_id"] == 10 and "InfoJobs" in edit["text"]
    assert "También en InfoJobs" in app.bot.send_message.await_args.kwargs["text"]


async def test_cycles_do_not_overlap(paths, monkeypatch):
    gate = asyncio.Event()

    async def slow_scan(paths, now=None, **kw):
        await gate.wait()
        return ScanReport()
    monkeypatch.setattr(radar, "scan", slow_scan)
    app = make_app(paths)
    first = asyncio.create_task(scheduler.cycle(app, paths, NOW))
    await asyncio.sleep(0)
    assert await scheduler.cycle(app, paths, NOW) is None
    gate.set()
    assert await first is not None


async def test_tick_only_runs_when_due(paths, monkeypatch):
    calls = []

    async def fake_cycle(app, paths, now=None, quiet=False):
        calls.append(quiet)
    monkeypatch.setattr(scheduler, "cycle", fake_cycle)
    ctx = SimpleNamespace(application=make_app(paths))
    scheduler.update_state(paths, last_scan=datetime.now(timezone.utc).isoformat())
    await scheduler.tick(ctx)
    assert calls == []
    scheduler.update_state(paths, last_scan=(datetime.now(timezone.utc) - timedelta(hours=3)).isoformat())
    await scheduler.tick(ctx)
    assert calls == [False]
    scheduler.update_state(paths, last_scan=None)
    await scheduler.tick(ctx)
    assert calls == [False, True]


def test_state_and_next_morning(paths):
    scheduler.update_state(paths, a=1, b=2)
    scheduler.update_state(paths, a=None)
    assert json.loads(paths.state.read_text(encoding="utf-8")) == {"b": 2}
    nm = scheduler.next_morning(NOW)
    assert nm > NOW and nm - NOW <= timedelta(hours=24)
    assert nm.astimezone(scheduler._local_tz()).hour == 8
