import pytest
from telegram import Chat, Message, Update, User
from telegram.ext import ApplicationHandlerStop, CommandHandler

from jobradar import bot
from jobradar.config import ConfigError, save_searches
from jobradar.models import Exclusions, Search
from jobradar.paths import Paths

CAT = bot.default_catalog()


def all_callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_toggle_and_priority():
    s = bot.wizard_state_new()
    bot.toggle(s, "tipos", "practicas")
    bot.toggle(s, "tipos", "trainee")
    bot.toggle(s, "tipos", "practicas")
    assert s["tipos"] == ["trainee"]
    bot.toggle(s, "prioridad", "normal")
    assert s["prioridad"] == "normal"
    with pytest.raises(ValueError):
        bot.toggle(s, "nada", "x")


def test_render_step_marks_selected_and_fits_telegram():
    s = bot.wizard_state_new()
    bot.toggle(s, "tipos", "practicas")
    bot.toggle(s, "tipos", "mi término libre")
    text, kb = bot.render_step(s, CAT)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert "✅ Prácticas" in labels and "⬜ Trainee" in labels and "✅ mi término libre" in labels
    assert "✏️ Otra…" in labels and "Paso 1/5" in text
    assert all(len(c.encode()) <= 64 for c in all_callbacks(kb))


def test_every_step_renders_and_remote_skips_location():
    s = bot.wizard_state_new()
    for _ in range(6):
        text, kb = bot.render_step(s, CAT)
        assert text and all(len(c.encode()) <= 64 for c in all_callbacks(kb))
        bot.advance(s, 1)
    assert s["step"] == bot.SUMMARY_STEP
    s = bot.wizard_state_new()
    bot.toggle(s, "modalidades", "remoto")
    s["step"] = 2
    assert bot.advance(s, 1)["step"] == 4
    assert bot.advance(s, -1)["step"] == 2


def test_summary_step_has_save_buttons():
    s = bot.wizard_state_new()
    s["step"] = bot.SUMMARY_STEP
    text, kb = bot.render_step(s, CAT)
    assert {"w:s", "w:c", "w:x", "w:name"} <= set(all_callbacks(kb))
    assert "Guardar" in text


def test_auto_name_and_roundtrip():
    s = bot.wizard_state_new(["b1"])
    assert s["id"] == "b2"
    for f, v in [("tipos", "practicas"), ("tipos", "trainee"), ("areas", "programador"),
                 ("ubicaciones", "granada"), ("modalidades", "hibrido")]:
        bot.toggle(s, f, v)
    bot.toggle(s, "areas", "otra cosa")
    search = bot.state_to_search(s)
    assert search.name == "Prácticas/Trainee · Programación/otra cosa · Híbrido · Granada"
    assert search.tipos == ["practicas", "trainee"] and search.modalidades == ["hibrido"]
    back = bot.search_to_state(search)
    assert back["name_custom"] is False
    assert bot.state_to_search(back) == search


def test_custom_name_roundtrip():
    s = bot.wizard_state_new()
    bot.toggle(s, "tipos", "junior")
    s["name"], s["name_custom"] = "Mi búsqueda", True
    search = bot.state_to_search(s)
    assert search.name == "Mi búsqueda"
    assert bot.search_to_state(search)["name_custom"] is True


def test_views():
    searches = [Search(id="b1", name="Una", tipos=["practicas"]), Search(id="b2", name="Dos", paused=True)]
    text, kb = bot.searches_view(searches, CAT)
    assert {"s:e:b1", "s:p:b1", "s:d:b1", "s:new"} <= set(all_callbacks(kb))
    assert "⏸" in text
    _, kb = bot.exclusions_view(Exclusions(words=["senior"], companies=["Acme"]))
    assert {"x:w:0", "x:c:0", "x:aw", "x:ac"} == set(all_callbacks(kb))


def test_title_tokens():
    assert bot.title_tokens("Becaria Data Analyst (H/M) para Granada - Becaria") == [
        "becaria", "data", "analyst", "granada"]
    assert len(bot.title_tokens(" ".join(f"palabra{c}" for c in "abcdefghijklmnop"))) == 8


def make_app(tmp_path):
    save_searches(tmp_path / "busquedas.yaml", [], Exclusions())
    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=123:ABC\nTELEGRAM_CHAT_ID=42\n", encoding="utf-8")
    return bot.build_application(Paths(tmp_path))


def update_from(chat_id):
    chat = Chat(chat_id, "private")
    msg = Message(1, None, chat, from_user=User(chat_id, "x", False), text="/estado")
    return Update(1, message=msg)


def test_missing_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(ConfigError):
        bot.build_application(Paths(tmp_path))


def test_only_configured_chat_is_authorized(tmp_path):
    app = make_app(tmp_path)
    own, foreign = update_from(42), update_from(99)
    commands = [h for group in app.handlers.values() for h in group if isinstance(h, CommandHandler)]
    assert {next(iter(h.commands)) for h in commands} == {c for c, _ in bot.COMMANDS}
    for h in commands:
        assert h.filters.check_update(own)
        assert not h.filters.check_update(foreign)


async def test_guard_stops_foreign_chat(tmp_path):
    app = make_app(tmp_path)
    ctx = type("C", (), {"bot_data": app.bot_data})()
    await bot.guard(update_from(42), ctx)
    with pytest.raises(ApplicationHandlerStop):
        await bot.guard(update_from(99), ctx)
