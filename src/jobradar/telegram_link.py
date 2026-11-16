"""Vinculación de Telegram por QR: enlace profundo con un código de un solo uso (t.me/<bot>?start=<código>)."""
from __future__ import annotations

import asyncio
import io
import re
import secrets
import time

# Sin 0/O/1/I para que el código no se confunda si hay que teclearlo.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class LinkConflict(RuntimeError):
    """Otro proceso está haciendo polling con el mismo bot (Telegram responde 409)."""


def new_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(8))


def deep_link(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start={code}"


def qr_text(url: str) -> str:
    import qrcode
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    out = io.StringIO()
    qr.print_ascii(out=out, invert=True)
    return out.getvalue()


def _display_name(chat) -> str:
    name = " ".join(filter(None, [getattr(chat, "first_name", None), getattr(chat, "last_name", None)]))
    return name or getattr(chat, "title", None) or getattr(chat, "username", None) or "?"


async def wait_for_start(bot, code: str, timeout: float = 300, poll: int = 25) -> tuple[int, str] | None:
    """Espera `/start <code>` en un chat privado. Devuelve (chat_id, nombre) o None si se agota el tiempo."""
    from telegram.error import Conflict
    pattern = re.compile(rf"^/start(?:@\w+)?\s+{re.escape(code)}$")
    deadline = time.monotonic() + timeout
    offset: int | None = None
    found: tuple[int, str] | None = None
    try:
        while found is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                updates = await bot.get_updates(offset=offset, timeout=max(0, min(poll, int(remaining))),
                                                allowed_updates=["message"])
            except Conflict as exc:
                raise LinkConflict(
                    "Hay otro proceso usando este bot (probablemente 'jobradar run'). "
                    "Páralo con 'jobradar stop' y repite el comando.") from exc
            for u in updates:
                offset = u.update_id + 1 if offset is None else max(offset, u.update_id + 1)
                m = u.message
                if found or m is None or not m.text or m.chat is None or m.chat.type != "private":
                    continue
                if pattern.match(m.text.strip()):
                    found = (m.chat.id, _display_name(m.chat))
            if not updates:
                await asyncio.sleep(0)
    finally:
        if offset is not None:  # confirma lo leído para que el bot no lo reprocese
            try:
                await bot.get_updates(offset=offset, timeout=0, allowed_updates=["message"])
            except Exception:
                pass
    return found
