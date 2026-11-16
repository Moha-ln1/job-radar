"""Perfil del bot en Telegram (nombre, descripciones y foto), aplicado una sola vez por bot.

Se aplica en el primer arranque y se anota el id del bot: si después lo cambias en BotFather, se respeta.
"""
from __future__ import annotations

import logging
from pathlib import Path

from telegram import Bot, InputProfilePhotoStatic
from telegram.error import TelegramError

_log = logging.getLogger("jobradar.perfil")

AVATAR = Path(__file__).parent / "data" / "avatar.png"
NAME = "Job Radar"
SHORT_DESCRIPTION = "📡 Prácticas, trainee y empleo junior en tech. Te aviso en cuanto aparecen."
DESCRIPTION = (
    "📡 Job Radar rastrea LinkedIn, InfoJobs, webs de empresas y portales de empleo cada pocas horas.\n\n"
    "🔥 Lo que encaja con tus búsquedas te llega al momento.\n"
    "📰 Lo demás, en un resumen diario.\n"
    "➕ Si una oferta aparece en varios portales, llega una sola vez con todos sus enlaces.\n\n"
    "Pulsa Iniciar y configura qué buscas con /busquedas."
)


async def apply_profile(bot: Bot, marker: Path) -> bool:
    """Pone nombre, descripciones y foto si este bot aún no los tiene. Devuelve si los ha aplicado."""
    bot_id = str(bot.id)
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == bot_id:
        return False
    try:
        await bot.set_my_name(NAME)
        await bot.set_my_short_description(SHORT_DESCRIPTION)
        await bot.set_my_description(DESCRIPTION)
        with AVATAR.open("rb") as photo:
            await bot.set_my_profile_photo(InputProfilePhotoStatic(photo))
    except TelegramError as exc:  # p. ej. límite de cambios de nombre: se reintenta en el próximo arranque
        _log.warning("no se pudo aplicar el perfil del bot: %s", exc)
        return False
    marker.write_text(bot_id, encoding="utf-8")
    _log.info("perfil del bot aplicado (nombre, descripción y foto)")
    return True
