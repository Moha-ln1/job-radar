"""Menús del bot para configurar sin tocar archivos: /fuentes, /empresas y /paginas.

Los cambios se guardan en ajustes_bot.yaml (config.save_bot_settings), que tiene prioridad sobre config.yaml.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlsplit

import httpx
from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from . import ats_detect, notify, radar, telegram_io
from .config import Settings, load_env, load_settings, save_bot_settings
from .http import Http, SourceBlocked
from .paths import Paths
from .sources.official_apis import REQUIRED_KEYS, missing_keys

_log = logging.getLogger("jobradar.bot")

# Qué es cada fuente, en una línea (para que se entienda qué se activa o desactiva)
SOURCE_INFO = {
    "linkedin": "LinkedIn (empleo general)",
    "infojobs": "InfoJobs (empleo general, España)",
    "tecnoempleo": "Tecnoempleo (tecnología, España)",
    "infoempleo": "Infoempleo (empleo general, España)",
    "primerempleo": "Primer Empleo (prácticas y primer empleo)",
    "ats": "Webs de empleo de empresas (/empresas)",
    "remotive": "Remotive (remoto)",
    "remoteok": "RemoteOK (remoto)",
    "weworkremotely": "We Work Remotely (remoto)",
    "himalayas": "Himalayas (remoto)",
    "arbeitnow": "Arbeitnow (Alemania y remoto)",
    "adzuna": "Adzuna (API oficial, necesita clave)",
    "jooble": "Jooble (API oficial, necesita clave)",
    "watch": "Páginas vigiladas (/paginas)",
}
SUPPORTED_ATS = "Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Recruitee, Personio y Teamtailor"


def _paths(context) -> Paths:
    return context.bot_data["paths"]


def _settings(paths: Paths) -> Settings:
    return load_settings(paths.config) if paths.config.exists() else Settings()


async def _show(update: Update, text: str, markup: InlineKeyboardMarkup | None, edit: bool) -> None:
    if edit and update.callback_query is not None:
        msg = update.callback_query.message
        try:
            await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except BadRequest as exc:  # "message is not modified" al pulsar dos veces
            if "not modified" not in str(exc).lower():
                raise
        return
    await update.effective_chat.send_message(text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                             link_preview_options=telegram_io._NO_PREVIEW)


async def _answer(update: Update, text: str | None = None) -> None:
    from .bot import _answer as safe_answer

    await safe_answer(update.callback_query, text)  # mismo manejo de cortes de red que el resto del bot


# --- /fuentes ---------------------------------------------------------------------------------------
def sources_view(settings: Settings, env: dict) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["<b>Fuentes</b>", "Pulsa una para activarla o desactivarla."]
    buttons = []
    for name, opts in settings.sources.items():
        on = opts.get("enabled", True)
        label = SOURCE_INFO.get(name, notify.source_label(name))
        if name in REQUIRED_KEYS and missing_keys(name, env):
            label += " · sin clave"
        buttons.append([InlineKeyboardButton(f"{'✅' if on else '⬜'} {label}"[:60], callback_data=f"f:t:{name}")])
    lines.append("Las que necesitan clave se configuran con <code>jobradar env set</code> (docs/APIS.md).")
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def cmd_fuentes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    paths = _paths(context)
    env = load_env(paths.env) if paths.env.exists() else {}
    text, kb = sources_view(_settings(paths), env)
    await _show(update, text, kb, edit=False)


async def on_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    paths = _paths(context)
    name = update.callback_query.data.split(":", 2)[2]
    settings = _settings(paths)
    if name not in settings.sources:
        await _answer(update, "Esa fuente ya no existe.")
        return
    enabled = not settings.sources[name].get("enabled", True)
    save_bot_settings(paths.config, source_enabled=(name, enabled))
    await _answer(update, f"{SOURCE_INFO.get(name, name)}: {'activada' if enabled else 'desactivada'}")
    env = load_env(paths.env) if paths.env.exists() else {}
    text, kb = sources_view(_settings(paths), env)
    await _show(update, text, kb, edit=True)


# --- /empresas --------------------------------------------------------------------------------------
def companies_view(settings: Settings) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["<b>Webs de empleo de empresas</b>",
             "Se leen directamente de su portal de empleo: solo ofertas abiertas."]
    if not settings.companies:
        lines.append("Aún no hay ninguna.")
    kb = [[InlineKeyboardButton(f"🗑 {c.get('name', c.get('slug'))} ({c.get('ats')})"[:60],
                                callback_data=f"e:d:{i}")] for i, c in enumerate(settings.companies)]
    kb.append([InlineKeyboardButton("➕ Añadir empresa", callback_data="e:a")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def cmd_empresas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, kb = companies_view(_settings(_paths(context)))
    await _show(update, text, kb, edit=False)


async def on_company(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    paths = _paths(context)
    _, action, *rest = update.callback_query.data.split(":")
    if action == "a":
        await _answer(update)
        context.user_data["await"] = ("empresa",)
        await update.effective_chat.send_message(
            "Pega el enlace de la página de ofertas de la empresa (la de «Trabaja con nosotros»).\n"
            f"Funciona si usa {SUPPORTED_ATS}.",
            reply_markup=ForceReply(input_field_placeholder="https://..."))
        return
    companies = list(_settings(paths).companies)
    if action == "d" and rest and rest[0].isdigit() and int(rest[0]) < len(companies):
        removed = companies.pop(int(rest[0]))
        save_bot_settings(paths.config, companies=companies)
        await _answer(update, f"Quitada: {removed.get('name')}")
    else:
        await _answer(update, "Ese menú ha caducado.")
    text, kb = companies_view(_settings(paths))
    await _show(update, text, kb, edit=True)


async def add_company(update: Update, context, url: str) -> None:
    paths = _paths(context)
    settings = _settings(paths)
    async with Http(settings.http) as http:
        try:
            found = await ats_detect.detect_url(http, url)
        except (httpx.HTTPError, SourceBlocked, ValueError) as exc:
            _log.info("no se pudo abrir %s: %s", url, exc)
            found = None
    if not found:
        await update.effective_chat.send_message(
            "No he reconocido el portal de empleo de esa página. Prueba con el enlace de la lista de ofertas "
            f"de la empresa. Funciona con {SUPPORTED_ATS}.")
        return
    companies = list(settings.companies)
    if any(c.get("ats") == found["ats"] and c.get("slug") == found["slug"] for c in companies):
        await update.effective_chat.send_message(f"{found['name']} ya estaba en la lista.")
    else:
        companies.append(found)
        save_bot_settings(paths.config, companies=companies)
        await update.effective_chat.send_message(
            f"✅ Añadida {escape(found['name'])} ({found['ats']}). Sus ofertas entrarán en el próximo escaneo.",
            parse_mode=ParseMode.HTML)
    text, kb = companies_view(_settings(paths))
    await _show(update, text, kb, edit=False)


# --- /paginas ---------------------------------------------------------------------------------------
def pages_view(settings: Settings) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["<b>Páginas vigiladas</b>",
             "Te aviso cuando aparece un enlace nuevo (convocatorias, plazas, inscripciones).",
             "📢 = te llegan todos sus enlaces nuevos · 🔎 = solo los que encajan con tus búsquedas."]
    if not settings.watch:
        lines.append("Aún no hay ninguna.")
    kb = []
    for i, w in enumerate(settings.watch):
        mode = "🔎" if w.get("filtrar") else "📢"
        kb.append([InlineKeyboardButton(f"{mode} {w.get('name')}"[:40], callback_data=f"p:f:{i}"),
                   InlineKeyboardButton("🗑", callback_data=f"p:d:{i}")])
    kb.append([InlineKeyboardButton("➕ Añadir página", callback_data="p:a")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def cmd_paginas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, kb = pages_view(_settings(_paths(context)))
    await _show(update, text, kb, edit=False)


async def on_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    paths = _paths(context)
    _, action, *rest = update.callback_query.data.split(":")
    if action == "a":
        await _answer(update)
        context.user_data["await"] = ("pagina",)
        await update.effective_chat.send_message(
            "Pega el enlace de la página que quieres vigilar (p. ej. la de convocatorias de una academia).",
            reply_markup=ForceReply(input_field_placeholder="https://..."))
        return
    watch = [dict(w) for w in _settings(paths).watch]
    idx = int(rest[0]) if rest and rest[0].isdigit() else -1
    if not 0 <= idx < len(watch):
        await _answer(update, "Ese menú ha caducado.")
    elif action == "d":
        removed = watch.pop(idx)
        save_bot_settings(paths.config, watch=watch)
        await _answer(update, f"Quitada: {removed.get('name')}")
    elif action == "f":
        watch[idx]["filtrar"] = not watch[idx].get("filtrar", False)
        save_bot_settings(paths.config, watch=watch)
        await _answer(update, "Solo enlaces que encajan con tus búsquedas" if watch[idx]["filtrar"]
                      else "Te llegarán todos sus enlaces nuevos")
    text, kb = pages_view(_settings(paths))
    await _show(update, text, kb, edit=True)


async def add_page(update: Update, context, url: str) -> None:
    from .sources.watch import _parse_watch
    paths = _paths(context)
    settings = _settings(paths)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    name = (urlsplit(url).hostname or url).removeprefix("www.")
    if any(w.get("url") == url for w in settings.watch):
        await update.effective_chat.send_message("Esa página ya estaba en la lista.")
        return
    try:
        async with Http(settings.http) as http:
            resp = await http.get(url)
        links = _parse_watch(resp.text, str(resp.url), name)
    except (httpx.HTTPError, SourceBlocked, ValueError) as exc:
        await update.effective_chat.send_message(f"No he podido abrir esa página ({escape(str(exc))[:150]}).")
        return
    watch = [*settings.watch, {"name": name, "url": url}]
    save_bot_settings(paths.config, watch=watch)
    # Lo que ya hay en la página no es nuevo: se marca como visto para no recibirlo todo de golpe
    seen = radar.mark_seen(paths, links, datetime.now(timezone.utc))
    await update.effective_chat.send_message(
        f"✅ Vigilando {escape(name)}: tiene {len(links)} enlaces ahora mismo ({seen} marcados como vistos). "
        "Te avisaré de los nuevos.", parse_mode=ParseMode.HTML)
    text, kb = pages_view(_settings(paths))
    await _show(update, text, kb, edit=False)


async def on_reply(update: Update, context, waiting: tuple, text: str) -> None:
    """Respuestas a «Añadir empresa» / «Añadir página» (texto escrito por el usuario)."""
    url = text.split()[0] if text.split() else ""
    if waiting[0] == "empresa":
        await add_company(update, context, url)
    else:
        await add_page(update, context, url)


HANDLERS = {"fuentes": cmd_fuentes, "empresas": cmd_empresas, "paginas": cmd_paginas}
CALLBACKS = [(r"^f:t:", on_source), (r"^e:", on_company), (r"^p:", on_page)]
