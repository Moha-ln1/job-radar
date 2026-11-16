import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from telegram.error import Conflict

from jobradar import cli, telegram_link as tl


def upd(uid, text, chat_id=1, kind="private", name="Ana"):
    chat = NS(id=chat_id, type=kind, first_name=name, last_name=None, title=None, username=None)
    return NS(update_id=uid, message=NS(text=text, chat=chat))


async def test_picks_right_code_after_stranger():
    bot = NS(get_updates=AsyncMock(side_effect=[
        [upd(10, "/start MALCODE1", chat_id=99), upd(11, "hola", chat_id=98), upd(12, "/start BUENCOD2", chat_id=5)],
        [],
    ]))
    assert await tl.wait_for_start(bot, "BUENCOD2", timeout=5) == (5, "Ana")
    assert bot.get_updates.await_args_list[-1].kwargs["offset"] == 13  # confirma todo lo leído


async def test_start_with_bot_suffix_and_ignores_groups():
    bot = NS(get_updates=AsyncMock(side_effect=[
        [upd(1, "/start CODE2345", chat_id=-7, kind="group"), upd(2, "/start@mi_bot CODE2345", chat_id=3)], []]))
    assert await tl.wait_for_start(bot, "CODE2345", timeout=5) == (3, "Ana")


async def test_timeout_returns_none_and_confirms_offsets():
    calls = iter([[upd(4, "/start OTRO")]])

    async def fake(**kw):
        await asyncio.sleep(0.01)
        return next(calls, [])
    bot = NS(get_updates=AsyncMock(side_effect=fake))
    assert await tl.wait_for_start(bot, "CODE2345", timeout=0.05, poll=1) is None
    assert bot.get_updates.await_args_list[-1].kwargs["offset"] == 5


async def test_conflict_raises_spanish():
    bot = NS(get_updates=AsyncMock(side_effect=Conflict("terminated by other getUpdates request")))
    with pytest.raises(tl.LinkConflict, match="otro proceso"):
        await tl.wait_for_start(bot, "CODE2345", timeout=5)


def test_new_code_has_no_ambiguous_chars():
    for _ in range(200):
        c = tl.new_code()
        assert len(c) == 8 and c.isalnum() and c == c.upper()
        assert not set(c) & set("0O1I")


def test_deep_link_and_qr_text():
    assert tl.deep_link("b_bot", "ABCD2345") == "https://t.me/b_bot?start=ABCD2345"
    lines = tl.qr_text(tl.deep_link("b_bot", "ABCD2345")).splitlines()
    assert len(lines) > 10 and all(l.strip() for l in lines)


def test_cli_link_without_token(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert cli.main(["telegram", "link"]) == 2
