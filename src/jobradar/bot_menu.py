"""Menú general (/menu): todo a un toque, con un resumen de dónde estás."""
from __future__ import annotations

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from . import seguimiento

# clave del botón -> (texto, módulo, función)
_ACTIONS = {
    "recientes": ("🆕 Últimos 3 días", "bot", "cmd_recientes"),
    "semana": ("🗓 Semana", "bot", "cmd_semana"),
    "favoritas": ("⭐ Favoritas", "bot_seguimiento", "cmd_favoritas"),
    "aplicadas": ("📨 Seguimiento", "bot_seguimiento", "cmd_aplicadas"),
    "estadisticas": ("📊 Estadísticas", "bot_seguimiento", "cmd_estadisticas"),
    "exportar": ("📤 Exportar CSV", "bot_seguimiento", "cmd_exportar"),
    "candidatura": ("🧾 Mis datos", "bot_seguimiento", "cmd_candidatura"),
    "busquedas": ("🎯 Búsquedas", "bot", "cmd_busquedas"),
    "excluir": ("🚫 Excluir", "bot", "cmd_excluir"),
    "descartadas": ("🗑 Descartadas", "bot", "cmd_descartadas"),
    "fuentes": ("🛰 Fuentes", "bot_fuentes", "cmd_fuentes"),
    "empresas": ("🏢 Empresas", "bot_fuentes", "cmd_empresas"),
    "paginas": ("📄 Páginas", "bot_fuentes", "cmd_paginas"),
    "estado": ("🩺 Estado", "bot", "cmd_estado"),
    "silencio": ("🔕 Silencio", "bot", "cmd_silencio"),
    "escanear": ("🔎 Escanear", "bot", "cmd_escanear"),
    "ayuda": ("❓ Ayuda", "bot", "cmd_ayuda"),
}
_LAYOUT = [("recientes", "semana"), ("favoritas", "aplicadas"), ("estadisticas", "exportar", "candidatura"),
           ("busquedas", "excluir", "descartadas"), ("fuentes", "empresas", "paginas"),
           ("estado", "silencio", "escanear"), ("ayuda",)]


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(_ACTIONS[k][0], callback_data=f"mn:{k}") for k in row]
                                 for row in _LAYOUT])


def menu_text(store, now: datetime) -> str:
    tr = store.stats(now)["seguimiento"]
    today = len(store.recent(1, now, "avisada"))
    parts = [f"🆕 {today} hoy", f"⭐ {len(store.favorites())} favoritas"]
    parts += [f"{seguimiento.TRACKS[t]} {tr[t]}" for t in ("aplicada", "entrevista", "oferta") if tr.get(t)]
    return "📡 <b>Menú</b>\n" + " · ".join(parts) + "\n\nPulsa lo que necesites. Para probar un título: /probar &lt;texto&gt;"


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import importlib
    query = update.callback_query
    key = query.data.removeprefix("mn:")
    from .bot import _answer
    await _answer(query)
    if key not in _ACTIONS:
        return
    _, module, func = _ACTIONS[key]
    await getattr(importlib.import_module(f"jobradar.{module}"), func)(update, context)
