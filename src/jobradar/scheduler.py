"""Programador interno: escaneo periódico, resumen diario y recuperación tras suspensión."""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, time, timedelta, timezone

from . import notify, radar, seguimiento, telegram_io
from .bot_seguimiento import track_keyboard
from .config import ConfigError, load_searches, load_settings
from .paths import Paths
from .store import Store

_log = logging.getLogger("jobradar.scheduler")
TICK_SECONDS = 600
TIMEZONE = "Europe/Madrid"


# --- estado persistente (estado.json) ---
def read_state(paths: Paths) -> dict:
    try:
        return json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def update_state(paths: Paths, **changes) -> dict:
    """Fija o borra (valor None) claves de estado.json, conservando el resto."""
    state = read_state(paths)
    for k, v in changes.items():
        if v is None:
            state.pop(k, None)
        else:
            state[k] = v
    paths.state.parent.mkdir(parents=True, exist_ok=True)
    paths.state.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return state


def _state_time(paths: Paths, key: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(read_state(paths)[key])
    except (KeyError, ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def last_scan(paths: Paths) -> datetime | None:
    return _state_time(paths, "last_scan")


def silenced_until(paths: Paths, now: datetime) -> datetime | None:
    until = _state_time(paths, "silence_until")
    return until if until and until > now else None


def _local_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TIMEZONE)
    except Exception:  # sin tzdata: hora local del sistema
        return datetime.now().astimezone().tzinfo


def next_morning(now: datetime, hour: int = 8) -> datetime:
    """Próximas 08:00 (hora local de Madrid) estrictamente posteriores a now."""
    tz = _local_tz()
    local = now.astimezone(tz)
    target = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)


def _settings(paths: Paths):
    from .config import Settings
    return load_settings(paths.config) if paths.config.exists() else Settings()


def next_scan(paths: Paths) -> datetime | None:
    last = last_scan(paths)
    return last + timedelta(hours=_settings(paths).scan.every_hours) if last else None


def is_due(paths: Paths, now: datetime) -> bool:
    nxt = next_scan(paths)
    return nxt is None or now >= nxt


# --- entrega ---
async def _safely(coro, what: str) -> bool:
    try:
        await coro
        return True
    except Exception as exc:  # un fallo de Telegram no debe perder la oferta: queda en el resumen
        _log.warning("no se pudo enviar %s: %r", what, exc)
        return False


async def deliver(bot, chat_id, paths: Paths, report, now: datetime, *, quiet: bool = False) -> int:
    """Envía lo del escaneo: prioridad alta al momento, el resto queda para el resumen."""
    searches = load_searches(paths.searches)[0] if paths.searches.exists() else []
    silent = quiet or silenced_until(paths, now) is not None
    store = Store(paths.db)
    sent = 0
    try:
        if not silent:
            for job in report.new_matched:
                if job.priority == "alta":
                    names = notify.search_names(job, searches)
                    if await _safely(telegram_io.send_job(bot, chat_id, store, job, names),
                                     f"la oferta {job.id}"):
                        sent += 1
            for job, posting in report.new_postings_for_notified:
                await _safely(telegram_io.add_portal(bot, chat_id, store, job, posting,
                                                     notify.search_names(job, searches)),
                              f"el portal nuevo de {job.id}")
        if report.health_alerts:
            await _safely(telegram_io.send_text(bot, chat_id, notify.format_health(report.health_alerts)),
                          "las alertas de salud")
    finally:
        store.close()
    return sent


async def send_digest(bot, chat_id, paths: Paths, now: datetime | None = None, *,
                      force: bool = False) -> int:
    """Manda el resumen con lo pendiente y lo marca como avisado. Devuelve el nº de ofertas."""
    now = now or datetime.now(timezone.utc)
    if not force and silenced_until(paths, now):
        return 0
    searches = load_searches(paths.searches)[0] if paths.searches.exists() else []
    store = Store(paths.db)
    try:
        pending = store.pending_digest()
        if not pending:
            return 0
        items = [(j, store.postings(j.id), notify.search_names(j, searches)) for j in pending]
        for text in notify.format_digest(items):
            await telegram_io.send_text(bot, chat_id, text)
        for j in pending:
            store.mark_notified(j.id, None, now)
        return len(pending)
    finally:
        store.close()


async def cycle(app, paths: Paths, now: datetime | None = None, *, quiet: bool = False,
                baseline: bool = False):
    """Un escaneo completo y su entrega. Devuelve el ScanReport, o None si ya había uno en marcha.

    baseline=True (primer arranque): lo encontrado se marca como ya visto y no se avisa de nada,
    para no recibir de golpe todas las ofertas y enlaces que ya existían."""
    lock = app.bot_data.setdefault("scan_lock", asyncio.Lock())
    if lock.locked():
        return None
    async with lock:
        now = now or datetime.now(timezone.utc)
        if baseline:
            report = await radar.init_baseline(paths, now)
            update_state(paths, last_scan=now.isoformat())
            _log.info("primer escaneo: %d ofertas marcadas como vistas (sin avisos)",
                      len(report.new_jobs))
            return report
        report = await radar.scan(paths, now)
        update_state(paths, last_scan=now.isoformat())
        await deliver(app.bot, app.bot_data["chat_id"], paths, report, now, quiet=quiet)
        return report


# --- tareas del JobQueue ---
async def tick(context) -> None:
    app = context.application
    paths = app.bot_data["paths"]
    now = datetime.now(timezone.utc)
    try:
        await _daily_reminders(app, paths, now)
        if not is_due(paths, now):
            return
        # Primera ejecución: línea base (lo existente queda como visto, sin avisos).
        await cycle(app, paths, now, baseline=last_scan(paths) is None)
    except ConfigError as exc:
        _log.error("configuración no válida: %s", exc)
    except Exception:
        _log.exception("el escaneo ha fallado")


async def daily_digest(context) -> None:
    app = context.application
    try:
        await send_digest(app.bot, app.bot_data["chat_id"], app.bot_data["paths"])
    except Exception:
        _log.exception("el resumen diario ha fallado")


async def send_reminders(bot, chat_id, paths: Paths, now: datetime) -> int:
    """Avisa de las candidaturas enviadas hace una semana sin novedades (una sola vez cada una)."""
    if silenced_until(paths, now):
        return 0
    store = Store(paths.db)
    sent = 0
    try:
        for job in store.due_reminders(now, seguimiento.REMINDER_DAYS):
            if await _safely(telegram_io.send_text(bot, chat_id, seguimiento.reminder_text(job, now),
                                                   reply_markup=track_keyboard(job.id, job.track, job.fav)),
                             f"el recordatorio de {job.id}"):
                store.mark_reminded(job.id)
                sent += 1
    except sqlite3.Error:
        _log.exception("los recordatorios han fallado")
    finally:
        store.close()
    return sent


async def _daily_reminders(app, paths: Paths, now: datetime) -> None:
    """Una vez al día pasadas las 10:00; si el PC estaba apagado a esa hora, al arrancar."""
    local = now.astimezone(_local_tz())
    if local.hour < 10 or read_state(paths).get("last_reminders") == local.date().isoformat():
        return
    await send_reminders(app.bot, app.bot_data["chat_id"], paths, now)
    update_state(paths, last_reminders=local.date().isoformat())


def _digest_time(paths: Paths) -> time:
    try:
        hour, minute = (int(x) for x in _settings(paths).scan.digest_time.split(":"))
        return time(hour, minute, tzinfo=_local_tz())
    except (ValueError, ConfigError):
        return time(9, 0, tzinfo=_local_tz())


def register_jobs(app, paths: Paths) -> None:
    app.bot_data["paths"] = paths
    queue = app.job_queue
    queue.run_repeating(tick, interval=TICK_SECONDS, first=5, name="tick")  # también recupera tras suspensión
    queue.run_daily(daily_digest, _digest_time(paths), name="digest")
