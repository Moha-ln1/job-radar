"""Comandos y botones de seguimiento: /aplicadas, /candidatura, /estadisticas, /exportar, Guardar y Aplicar."""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from . import notify, seguimiento, telegram_io
from .seguimiento import CAND_FIELDS, TRACKS

_log = logging.getLogger("jobradar.bot")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _store(context):
    return context.bot_data["store"]


async def _say(update: Update, text: str, markup=None):
    return await update.effective_chat.send_message(
        text, parse_mode="HTML", reply_markup=markup, link_preview_options=telegram_io._NO_PREVIEW)


def track_keyboard(job_id: int, current: str | None = None, fav: bool = False) -> InlineKeyboardMarkup:
    """Botones de la ficha: favorita, pasar de ella y los estados de seguimiento."""
    top = [InlineKeyboardButton("☆ Quitar favorita" if fav else "⭐ Favorita", callback_data=f"fv:{job_id}"),
           InlineKeyboardButton("🗑 Pasar de ella", callback_data=f"n:{job_id}")]
    states = [InlineKeyboardButton(label, callback_data=f"t:{key}:{job_id}")
              for key, label in TRACKS.items() if key != current]
    rows = [top] + [states[i:i + 2] for i in range(0, len(states), 2)]
    if current:
        rows.append([InlineKeyboardButton("🗑 Quitar del seguimiento", callback_data=f"t:x:{job_id}")])
    return InlineKeyboardMarkup(rows)


async def cmd_aplicadas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texts = seguimiento.format_tracked(_store(context).tracked(), _now())
    for i, text in enumerate(texts):
        last = i == len(texts) - 1
        await _say(update, text, InlineKeyboardMarkup([[
            InlineKeyboardButton("⭐ Favoritas", callback_data="mn:favoritas"),
            InlineKeyboardButton("📊 Estadísticas", callback_data="mn:estadisticas"),
            InlineKeyboardButton("📤 Exportar", callback_data="mn:exportar")]]) if last else None)


async def cmd_favoritas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    for text in seguimiento.format_favorites(_store(context).favorites(), _now()):
        await _say(update, text)


async def on_fav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    store = _store(context)
    job = store.get_job(int(query.data.split(":")[1]))
    if job is None:
        await query.answer("Esa oferta ya no existe.")
        return
    store.set_fav(job.id, not job.fav)
    await query.answer("⭐ Añadida a favoritas" if not job.fav else "Quitada de favoritas")
    markup = query.message.reply_markup if query.message else None
    buttons = [b.callback_data or "" for row in markup.inline_keyboard for b in row] if markup else []
    if buttons and not any(c.startswith("h:") for c in buttons):  # el aviso original conserva sus botones
        try:
            await query.edit_message_reply_markup(track_keyboard(job.id, job.track, not job.fav))
        except BadRequest:
            pass


async def cmd_oferta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/oferta_12: la ficha de una oferta seguida, con botones para cambiar su estado."""
    m = re.match(r"^/oferta_(\d+)", update.message.text or "")
    store = _store(context)
    job = store.get_job(int(m.group(1))) if m else None
    if job is None:
        await _say(update, "Esa oferta ya no existe.")
        return
    text = notify.format_job(job, store.postings(job.id), [])
    if job.track:
        text += f"\n{TRACKS[job.track]} · {seguimiento._days(_now(), job.track_at)}"
    await _say(update, text, track_keyboard(job.id, job.track, job.fav))


async def on_track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, state, raw = query.data.split(":")
    store = _store(context)
    job = store.get_job(int(raw))
    if job is None or (state != "x" and state not in TRACKS):
        await query.answer("Esa oferta ya no existe.")
        return
    if state == job.track:
        await query.answer(f"Ya está como {TRACKS[state]}")  # no reinicia la fecha ni el recordatorio
        return
    if state == "guardada" and job.track:
        await query.answer(f"Ya la sigues como {TRACKS[job.track]}")  # un botón antiguo no hace retroceder
        return
    new = None if state == "x" else state
    store.set_track(job.id, new, _now())
    await query.answer("Quitada del seguimiento" if state == "x" else TRACKS[state])
    markup = query.message.reply_markup if query.message else None
    buttons = [b.callback_data or "" for row in markup.inline_keyboard for b in row] if markup else []
    if buttons and not any(c.startswith("h:") for c in buttons):  # el aviso original conserva sus botones
        try:
            await query.edit_message_reply_markup(track_keyboard(job.id, new, job.fav))
        except BadRequest:
            pass


async def on_apply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    store = _store(context)
    job = store.get_job(int(query.data.split(":")[1]))
    if job is None:
        await query.answer("Esa oferta ya no existe.")
        return
    await query.answer()
    data = seguimiento.load_candidatura(context.bot_data["paths"])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📨 Ya he aplicado", callback_data=f"t:aplicada:{job.id}"),
        InlineKeyboardButton("💾 Guardar", callback_data=f"t:guardada:{job.id}")]])
    await _say(update, seguimiento.apply_kit(job, store.postings(job.id), data), kb)


def candidatura_view(data: dict[str, str]):
    lines = ["<b>🧾 Tus datos para solicitar</b>", "Se usan en la carta y las respuestas de 📝 Aplicar."]
    for key, label in CAND_FIELDS.items():
        lines.append(f"• {label}: {notify.escape(data[key]) if data.get(key) else '—'}")
    rows = [[InlineKeyboardButton(f"✏️ {label.split(' (')[0]}", callback_data=f"c:{key}")]
            for key, label in CAND_FIELDS.items()]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def cmd_candidatura(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _say(update, *candidatura_view(seguimiento.load_candidatura(context.bot_data["paths"])))


async def on_candidatura(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    field = query.data.split(":")[1]
    if field not in CAND_FIELDS:
        await query.answer()
        return
    await query.answer()
    context.user_data["await"] = ("cand", field)
    await update.effective_chat.send_message(f"{CAND_FIELDS[field]}: escríbelo (o '-' para borrarlo).",
                                             reply_markup=ForceReply(selective=True))


async def on_candidatura_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str, text: str) -> None:
    paths = context.bot_data["paths"]
    data = seguimiento.load_candidatura(paths)
    if text.strip() == "-":
        data.pop(field, None)
    else:
        data[field] = text.strip()[:300]
    seguimiento.save_candidatura(paths, data)
    await _say(update, *candidatura_view(data))


async def cmd_estadisticas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _say(update, seguimiento.format_stats(_store(context).stats(_now())))


async def cmd_exportar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = _store(context)
    jobs = {j.id: j for j in store.recent(30, _now(), "avisada")}
    jobs.update({j.id: j for j in store.tracked()})
    if not jobs:
        await _say(update, "No hay ofertas que exportar todavía.")
        return
    ordered = sorted(jobs.values(), key=lambda j: j.track_at or j.first_seen, reverse=True)
    # utf-8 con BOM para que Excel respete los acentos
    data = ("\ufeff" + seguimiento.to_csv(ordered, store)).encode("utf-8")
    await update.effective_chat.send_document(io.BytesIO(data), filename="ofertas.csv",
                                              caption=f"{len(ordered)} ofertas (últimos 30 días y las que sigues)")


HANDLERS = {"aplicadas": cmd_aplicadas, "favoritas": cmd_favoritas, "candidatura": cmd_candidatura,
            "estadisticas": cmd_estadisticas, "exportar": cmd_exportar}
CALLBACKS = [(r"^fv:\d+$", on_fav), (r"^t:(x|[a-z]+):\d+$", on_track), (r"^a:\d+$", on_apply), (r"^c:[a-z]+$", on_candidatura)]
OFERTA_PATTERN = r"^/oferta_\d+"
