"""Envío real a Telegram: respeta los límites de frecuencia (RetryAfter) y guarda el id del mensaje."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from telegram import LinkPreviewOptions, ReplyParameters
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter

from . import notify
from .config import load_env
from .paths import Paths

_log = logging.getLogger("jobradar.telegram")
_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
MISSING_CREDENTIALS = (
    "Falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el archivo .env. Crea el bot con @BotFather, "
    "pon el token en .env, escríbele /start y ejecuta 'jobradar telegram chat-id' para ver tu chat_id."
)


def credentials(paths: Paths) -> tuple[str | None, str | None]:
    """(token, chat_id) del .env; si no están, de las variables de entorno."""
    env = load_env(paths.env) if paths.env.exists() else {}
    token = env.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or None
    chat = env.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or None
    return token, chat


async def _call(fn, **kwargs):
    """Llama a un método del bot reintentando una vez si Telegram pide esperar."""
    for attempt in range(3):
        try:
            return await fn(**kwargs)
        except RetryAfter as exc:
            wait = exc.retry_after
            wait = wait.total_seconds() if isinstance(wait, timedelta) else float(wait)
            if attempt == 2:
                raise
            _log.warning("Telegram pide esperar %.0f s", wait)
            await asyncio.sleep(wait + 1)


async def send_text(bot, chat_id, text: str, parse_mode: str | None = ParseMode.HTML, **kwargs):
    return await _call(bot.send_message, chat_id=chat_id, text=text, parse_mode=parse_mode,
                       link_preview_options=_NO_PREVIEW, **kwargs)


async def send_job(bot, chat_id, store, job, names: list[str]):
    postings = store.postings(job.id)
    msg = await send_text(bot, chat_id, notify.format_job(job, postings, names),
                          reply_markup=notify.job_keyboard(job.id))
    store.mark_notified(job.id, msg.message_id, datetime.now(timezone.utc))
    return msg


async def add_portal(bot, chat_id, store, job, posting, names: list[str] | None = None):
    """Un portal nuevo en una oferta ya avisada: edita el mensaje original y responde a él."""
    job = store.get_job(job.id) or job
    names = names if names is not None else job.matched_searches
    if job.tg_message_id is None:
        return await send_job(bot, chat_id, store, job, names)
    text = notify.format_job(job, store.postings(job.id), names)
    try:
        await _call(bot.edit_message_text, chat_id=chat_id, message_id=job.tg_message_id, text=text,
                    parse_mode=ParseMode.HTML, link_preview_options=_NO_PREVIEW,
                    reply_markup=notify.job_keyboard(job.id))
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            _log.info("no se pudo editar el mensaje de la oferta %s (%s): se envía uno nuevo", job.id, exc)
            return await send_job(bot, chat_id, store, job, names)
    return await send_text(bot, chat_id, notify.format_new_portal(posting.source),
                           reply_parameters=ReplyParameters(job.tg_message_id,
                                                            allow_sending_without_reply=True))
