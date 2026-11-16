"""Recorrido completo del bot con la Application real y la API de Telegram simulada (sin red)."""
import asyncio
import json
import re
import time
from datetime import datetime, timezone

import pytest
import yaml
from telegram import Update
from telegram.request import BaseRequest

from jobradar import bot, notify, radar
from jobradar.config import load_searches
from jobradar.models import Decision, JobOffer
from jobradar.paths import Paths
from jobradar.radar import ScanReport
from jobradar.store import Store

CHAT = 4242
OTHER_CHAT = 999
TOKEN = "123456:TEST-TOKEN"
USER = {"id": CHAT, "is_bot": False, "first_name": "Tester"}
_ALLOWED = ("b", "i", "u", "s", "code", "pre")
_TAG = re.compile(r"</?(?:%s)>|<a href=\"[^\"<>]*\">|</a>" % "|".join(_ALLOWED))


# --- API de Telegram simulada ---
class FakeRequest(BaseRequest):
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._next_id = 1000
        self._shown: dict[tuple, str] = {}

    @property
    def read_timeout(self):
        return 5.0

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    @staticmethod
    def _message(chat_id, message_id, text):
        return {"message_id": message_id, "date": int(time.time()),
                "chat": {"id": int(chat_id), "type": "private", "first_name": "Tester"},
                "from": {"id": 1, "is_bot": True, "first_name": "bot", "username": "jobradar_bot"},
                "text": text}

    @staticmethod
    def _sig(params):
        return json.dumps([params.get("text"), params.get("reply_markup")], sort_keys=True, default=str)

    async def do_request(self, url, method, request_data=None, read_timeout=None, write_timeout=None,
                         connect_timeout=None, pool_timeout=None):
        name = url.rsplit("/", 1)[-1]
        params = dict(request_data.parameters) if request_data else {}
        self.calls.append((name, params))

        def reply(result):
            return 200, json.dumps({"ok": True, "result": result}).encode()

        if name == "getMe":
            return reply({"id": 1, "is_bot": True, "first_name": "bot", "username": "jobradar_bot"})
        if name == "sendMessage":
            self._next_id += 1
            params["_message_id"] = self._next_id
            self._shown[(params["chat_id"], self._next_id)] = self._sig(params)
            return reply(self._message(params["chat_id"], self._next_id, params["text"]))
        if name == "editMessageText":
            key = (params["chat_id"], params["message_id"])
            params["_message_id"] = params["message_id"]
            sig = self._sig(params)
            if self._shown.get(key) == sig:  # Telegram rechaza editar con el mismo contenido
                body = {"ok": False, "error_code": 400,
                        "description": "Bad Request: message is not modified: specified new message "
                                       "content and reply markup are exactly the same"}
                return 400, json.dumps(body).encode()
            self._shown[key] = sig
            return reply(self._message(params["chat_id"], params["message_id"], params["text"]))
        return reply(True)

    def names(self):
        return [n for n, _ in self.calls]


# --- validaciones de formato ---
def check_html(text: str) -> None:
    stack = []
    for m in re.finditer(r"<[^>]*>", text):
        tag = m.group(0)
        assert _TAG.fullmatch(tag), f"etiqueta no permitida en HTML de Telegram: {tag!r}"
        name = re.match(r"</?(\w+)", tag).group(1)
        if tag.startswith("</"):
            assert stack and stack.pop() == name, f"etiquetas mal anidadas en {text!r}"
        else:
            stack.append(name)
    assert not stack, f"etiquetas sin cerrar: {stack}"
    bare = _TAG.sub("", text)
    assert "<" not in bare and ">" not in bare, f"< o > sin escapar: {text!r}"
    assert not re.search(r"&(?!(amp|lt|gt|quot|#\d+);)", bare), f"& sin escapar: {text!r}"


def markup_buttons(markup):
    rows = markup.get("inline_keyboard", []) if isinstance(markup, dict) else []
    return [b for row in rows for b in row]


class Harness:
    def __init__(self, app, fake, paths):
        self.app, self.fake, self.paths = app, fake, paths
        self.update_id = 0

    def mark(self):
        return len(self.fake.calls)

    @staticmethod
    def _msg_dict(chat_id, message_id, text, **extra):
        return {"message_id": message_id, "date": int(time.time()),
                "chat": {"id": chat_id, "type": "private"}, "from": USER, "text": text, **extra}

    async def _feed(self, payload):
        self.update_id += 1
        update = Update.de_json({"update_id": self.update_id, **payload}, self.app.bot)
        await self.app.process_update(update)
        for _ in range(5):  # deja correr las tareas en segundo plano (p. ej. /escanear)
            await asyncio.sleep(0.01)
        self.check_calls()

    def check_calls(self):
        for name, p in self.fake.calls:
            if name in ("sendMessage", "editMessageText"):
                if p.get("parse_mode") == "HTML":
                    check_html(p["text"])
                assert len(p["text"]) <= 4096
            for b in markup_buttons(p.get("reply_markup")):
                if "callback_data" in b:
                    assert len(b["callback_data"].encode()) <= 64, b

    async def say(self, text, chat_id=CHAT):
        extra = {}
        if text.startswith("/"):
            extra["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        await self._feed({"message": self._msg_dict(chat_id, 1, text, **extra)})

    def last_markup(self):
        """(message_id, botones) del último mensaje enviado o editado con teclado."""
        for name, p in reversed(self.fake.calls):
            if name in ("sendMessage", "editMessageText") and markup_buttons(p.get("reply_markup")):
                return p["_message_id"], markup_buttons(p["reply_markup"])
        raise AssertionError("el bot no ha enviado ningún teclado")

    async def press(self, label, data=None, message_id=None, chat_id=CHAT, user_id=CHAT):
        """Pulsa el botón cuyo texto contiene `label`, con el callback_data que envió el bot."""
        mid, buttons = self.last_markup() if data is None or message_id is None else (message_id, [])
        if data is None:
            found = [b for b in buttons if label in b["text"]]
            assert found, f"no hay botón {label!r} entre {[b['text'] for b in buttons]}"
            data = found[0]["callback_data"]
        await self._feed({"callback_query": {
            "id": str(self.update_id + 1), "from": {**USER, "id": user_id}, "chat_instance": "ci",
            "data": data, "message": self._msg_dict(chat_id, message_id or mid, "menu")}})
        return data

    def sent_texts(self, mark=0):
        return [p["text"] for n, p in self.fake.calls[mark:] if n in ("sendMessage", "editMessageText")]

    def last_text(self):
        return self.sent_texts()[-1]

    def answers(self, mark=0):
        return [p.get("text") for n, p in self.fake.calls[mark:] if n == "answerCallbackQuery"]


@pytest.fixture
async def h(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    (tmp_path / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID={CHAT}\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("sources:\n  infojobs: {}\n  remotive: {}\n", encoding="utf-8")
    paths = Paths(tmp_path)
    app = bot.build_application(paths)
    fake = FakeRequest()
    app.bot._request = (fake, fake)
    await app.initialize()
    await bot._post_init(app)
    yield Harness(app, fake, paths)
    await app.shutdown()
    app.bot_data["store"].close()


_seq = iter(range(1, 10_000))


def seed(paths, title, company, location, modality, matched=None):
    store = Store(paths.db)
    offer = JobOffer(title=title, url=f"https://ejemplo.invalid/{next(_seq)}", source="infojobs",
                     company=company, location=location, modality=modality)
    job = store.upsert([offer], datetime.now(timezone.utc)).new_jobs[0]
    if matched:
        store.set_decision(job.id, Decision(matched=matched, priority="alta", reasons=["ok"]))
    else:
        store.set_decision(job.id, Decision(matched=[], reasons=["no es de ninguna de tus búsquedas"]))
    store.close()
    return job.id


async def create_search(h):
    await h.say("/busquedas")
    await h.press("Nueva")
    await h.press("Prácticas")
    await h.press("Trainee")
    await h.press("Siguiente")
    await h.press("Datos")
    await h.press("Siguiente")
    await h.press("Presencial")
    await h.press("Remoto")
    await h.press("Siguiente")
    await h.press("Granada")
    await h.press("Siguiente")
    await h.press("Al momento")
    await h.press("Siguiente")


# --- pruebas ---
async def test_startup_registers_commands_and_getme(h):
    assert "getMe" in h.fake.names() and "setMyCommands" in h.fake.names()


async def test_start_and_ayuda(h):
    await h.say("/start")
    assert "/busquedas" in h.last_text()
    await h.say("/ayuda")
    assert all(f"/{c}" in h.last_text() for c, _ in bot.COMMANDS)


async def test_create_search_with_wizard(h):
    seed(h.paths, "Prácticas de Data Analyst", "Acme", "Granada", "presencial")
    await create_search(h)
    await h.press("Guardar")
    searches, _ = load_searches(h.paths.searches)
    assert len(searches) == 1
    s = searches[0]
    assert s.tipos == ["practicas", "trainee"] and s.areas == ["data"]
    assert s.modalidades == ["presencial", "remoto"] and s.ubicaciones == ["granada"]
    assert s.prioridad == "alta"
    assert "ya encaja con 1 ofertas" in h.last_text()


async def test_free_text_other_in_type(h):
    await h.say("/busquedas")
    await h.press("Nueva")
    await h.press("Otra")
    assert h.fake.calls[-1][0] == "sendMessage"
    assert "force_reply" in json.dumps(h.fake.calls[-1][1]["reply_markup"])
    await h.say("becas")
    assert any("becas" in b["text"] for b in h.last_markup()[1])
    for _ in range(5):
        await h.press("Siguiente")
    await h.press("Guardar")
    assert "becas" in load_searches(h.paths.searches)[0][0].tipos


async def test_edit_pause_delete(h):
    await create_search(h)
    await h.press("Guardar")
    await h.say("/busquedas")
    await h.press("✏️ ")
    await h.press("Junior")
    for _ in range(5):
        await h.press("Siguiente")
    await h.press("Guardar")
    searches = load_searches(h.paths.searches)[0]
    assert len(searches) == 1 and "junior" in searches[0].tipos
    await h.say("/busquedas")
    await h.press("⏸")
    assert load_searches(h.paths.searches)[0][0].paused is True
    assert "⏸" in h.last_text()
    await h.press("▶")
    assert load_searches(h.paths.searches)[0][0].paused is False
    await h.press("🗑")
    assert "¿Borrar" in h.last_text()
    await h.press("Sí, borrar")
    assert load_searches(h.paths.searches)[0] == []


async def test_exclusions(h):
    await h.say("/excluir")
    await h.press("Palabra")
    assert "force_reply" in json.dumps(h.fake.calls[-1][1]["reply_markup"])
    await h.say("senior")
    assert "senior" in h.last_text()
    assert load_searches(h.paths.searches)[1].words == ["senior"]
    await h.press("❌")
    assert load_searches(h.paths.searches)[1].words == []
    assert "ninguna" in h.last_text()


async def test_probar(h):
    await h.say("/probar Becaria Data (H/M) - Granada")
    assert "Esta oferta" in h.last_text()
    await h.say("/probar")
    assert "Uso:" in h.last_text()


async def test_recientes_and_discarded_flow(h):
    await h.say("/recientes")
    assert "No hay ofertas" in h.last_text()
    seed(h.paths, "Prácticas Python", "Acme", "Granada", "presencial", matched=["b1"])
    await h.say("/recientes")
    assert "Prácticas Python" in h.last_text()
    bad = seed(h.paths, "Becaria Estadística avanzada", "Otra SL", "Granada", "presencial")
    await h.say("/descartadas")
    assert "Becaria" in h.last_text()
    await h.press("Era buena")
    store = Store(h.paths.db)
    assert store.get_job(bad).status == "avisada"
    store.close()
    await h.press("estadística")
    await h.press("Datos")
    syn = yaml.safe_load(h.paths.user_synonyms.read_text(encoding="utf-8"))
    assert "estadística" in syn["data"]
    assert "Añadido" in h.last_text()


async def test_job_buttons_hide_company_and_dislike(h):
    a = seed(h.paths, "Prácticas A", "Empresa Uno", "Granada", "presencial", matched=["b1"])
    b = seed(h.paths, "Prácticas B", "Empresa Dos", "Granada", "presencial", matched=["b1"])
    cbs = [x.callback_data for x in notify.job_keyboard(a).inline_keyboard[0]]
    assert cbs == [f"h:{a}", f"n:{a}"]
    await h.press("", data=f"h:{a}", message_id=50)
    assert load_searches(h.paths.searches)[1].companies == ["Empresa Uno"]
    await h.press("", data=f"n:{b}", message_id=51)
    store = Store(h.paths.db)
    assert store.get_job(b).status == "descartada"
    store.close()


async def test_estado_with_cooldown(h):
    store = Store(h.paths.db)
    store.record_run("infojobs", datetime.now(timezone.utc), False, 0, None,
                     "InfoJobs bloquea las peticiones (403)")
    store.record_run("remotive", datetime.now(timezone.utc), True, 5, 80.0, None)
    store.close()
    await h.say("/estado")
    assert "descansa hasta" in h.last_text()


async def test_silencio_toggle(h):
    await h.say("/silencio")
    assert "Sin avisos" in h.last_text()
    await h.say("/silencio")
    assert "reactivados" in h.last_text()


async def test_escanear(h, monkeypatch):
    async def fake_scan(paths, now=None, **kw):
        return ScanReport()
    monkeypatch.setattr(radar, "scan", fake_scan)
    await h.say("/escanear")
    assert "Escaneando" in h.sent_texts()[0]
    assert "Escaneo terminado" in h.last_text()


async def test_other_chat_gets_nothing(h):
    mark = h.mark()
    await h.say("/start", chat_id=OTHER_CHAT)
    await h.say("/busquedas", chat_id=OTHER_CHAT)
    await h.press("", data="s:new", message_id=5, chat_id=OTHER_CHAT, user_id=OTHER_CHAT)
    assert h.fake.calls[mark:] == []


async def test_stale_menu_gets_friendly_notice(h):
    for data in ("w:t:practicas", "w:n", "k:0", "m:data"):
        mark = h.mark()
        await h.press("", data=data, message_id=7)
        assert any("caducado" in (a or "") for a in h.answers(mark)), data


async def test_not_modified_is_silent_and_errors_are_reported(h, caplog):
    await create_search(h)
    mid, _ = h.last_markup()
    mark = h.mark()
    await h.press("", data="w:n", message_id=mid)  # ya en el resumen: mismo contenido
    assert not any("Algo ha fallado" in t for t in h.sent_texts(mark))
    h.paths.searches.write_text("busquedas: [no, es: valido", encoding="utf-8")  # fallo real
    with caplog.at_level("INFO"):
        await h.say("/busquedas")
    assert "Algo ha fallado" in h.last_text() and "logs/jobradar.log" in h.last_text()
    assert any(r.levelname == "ERROR" and r.exc_info for r in caplog.records)


async def test_commands_and_buttons_are_logged(h, caplog):
    with caplog.at_level("INFO", logger="jobradar.bot"):
        await h.say("/busquedas")
        await h.press("Nueva")
        await h.say("texto libre privado")
    msgs = [r.getMessage() for r in caplog.records if r.name == "jobradar.bot"]
    assert any("/busquedas" in m for m in msgs) and any("callback s" in m for m in msgs)
    assert not any("privado" in m for m in msgs)


# --- configuración sin archivos: /fuentes, /empresas, /paginas ---
async def test_fuentes_toggle_saves_bot_settings_not_config(h):
    from jobradar.config import load_settings
    before = (h.paths.root / "config.yaml").read_text(encoding="utf-8")
    await h.say("/fuentes")
    assert "Fuentes" in h.last_text()
    await h.press("InfoJobs")
    assert load_settings(h.paths.config).sources["infojobs"]["enabled"] is False
    assert (h.paths.root / "config.yaml").read_text(encoding="utf-8") == before
    await h.press("InfoJobs")
    assert load_settings(h.paths.config).sources["infojobs"]["enabled"] is True


async def test_empresas_add_by_url_and_delete(h):
    from jobradar.config import load_settings
    await h.say("/empresas")
    await h.press("Añadir")
    assert "force_reply" in json.dumps(h.fake.calls[-1][1]["reply_markup"])
    await h.say("https://boards.greenhouse.io/acmecorp")
    companies = load_settings(h.paths.config).companies
    assert companies == [{"name": "Acmecorp", "ats": "greenhouse", "slug": "acmecorp"}]
    await h.say("/empresas")
    await h.press("🗑")
    assert load_settings(h.paths.config).companies == []


async def test_empresas_unknown_portal_explains(h, monkeypatch):
    from jobradar import bot_fuentes

    async def nothing(http, url):
        return None
    monkeypatch.setattr(bot_fuentes.ats_detect, "detect_url", nothing)
    await h.say("/empresas")
    await h.press("Añadir")
    await h.say("https://ejemplo.invalid/empleo")
    assert "No he reconocido" in h.last_text() or "Webs de empleo" in h.last_text()
    assert any("No he reconocido" in t for t in h.sent_texts())


async def test_paginas_add_marks_existing_links_seen_then_toggle_and_delete(h, monkeypatch):
    from jobradar import bot_fuentes
    from jobradar.config import load_settings

    class FakeResp:
        url = "https://academia.invalid/"
        text = ('<body><main><a href="/convocatoria-2027">Convocatoria 2027</a>'
                '<a href="/curso">Curso de Python</a></main></body>')

    class FakeHttp:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url):
            return FakeResp()
    monkeypatch.setattr(bot_fuentes, "Http", FakeHttp)
    await h.say("/paginas")
    await h.press("Añadir")
    await h.say("academia.invalid")
    assert any("Vigilando academia.invalid" in t for t in h.sent_texts())
    watch = load_settings(h.paths.config).watch
    assert watch == [{"name": "academia.invalid", "url": "https://academia.invalid"}]
    store = Store(h.paths.db)
    assert store.pending_digest() == []  # lo que ya había no se envía
    store.close()
    await h.say("/paginas")
    await h.press("📢")
    assert load_settings(h.paths.config).watch[0]["filtrar"] is True
    await h.press("🗑")
    assert load_settings(h.paths.config).watch == []
