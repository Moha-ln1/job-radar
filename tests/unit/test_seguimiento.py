from datetime import datetime, timedelta, timezone

from jobradar import seguimiento
from jobradar.bot_seguimiento import candidatura_view, track_keyboard
from jobradar.models import Decision, JobOffer
from jobradar.paths import Paths
from jobradar.store import Store

NOW = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def _store(tmp_path, n=2):
    store = Store(tmp_path / "t.db")
    store.upsert([JobOffer(title=f"Junior Python {i}", url=f"https://e.invalid/{i}", source="t",
                           company=f"Empresa {i}", location="Madrid") for i in range(n)], NOW)
    for j in range(1, n + 1):
        store.set_decision(j, Decision(matched=["b1"], reasons=[]))
    return store


def test_seguimiento_y_recordatorio_una_sola_vez(tmp_path):
    s = _store(tmp_path)
    s.set_track(1, "aplicada", NOW - timedelta(days=8))
    s.set_track(2, "aplicada", NOW - timedelta(days=2))
    assert [j.id for j in s.due_reminders(NOW, 7)] == [1]
    s.mark_reminded(1)
    assert s.due_reminders(NOW, 7) == []
    s.set_track(1, "entrevista", NOW)           # cambiar de estado reinicia el aviso
    assert s.get_job(1).track == "entrevista" and not s.get_job(1).reminded
    s.set_track(1, None, NOW)
    assert s.get_job(1).track is None and [j.id for j in s.tracked()] == [2]


def test_migracion_de_base_antigua(tmp_path):
    import sqlite3
    db = sqlite3.connect(tmp_path / "old.db")
    db.executescript("CREATE TABLE jobs (id INTEGER PRIMARY KEY, key TEXT NOT NULL, title TEXT NOT NULL,"
                     " company TEXT, company_norm TEXT NOT NULL DEFAULT '', location TEXT, modality TEXT,"
                     " remote_region TEXT, category TEXT, first_seen TEXT NOT NULL,"
                     " status TEXT NOT NULL DEFAULT 'pending', priority TEXT,"
                     " reasons TEXT NOT NULL DEFAULT '[]', matched_searches TEXT NOT NULL DEFAULT '[]',"
                     " notified_at TEXT, tg_message_id INTEGER);")
    db.commit()
    db.close()
    Store(tmp_path / "old.db").set_track(1, "guardada", NOW)  # no revienta: columnas añadidas


def test_estadisticas_y_csv(tmp_path):
    s = _store(tmp_path)
    s.set_track(1, "aplicada", NOW)
    s.set_track(2, "entrevista", NOW)
    text = seguimiento.format_stats(s.stats(NOW))
    assert "que encajan: 2" in text and "1 de 2 candidaturas (50 %)" in text
    csv_text = seguimiento.to_csv(s.tracked(), s)
    assert csv_text.splitlines()[0].startswith("estado,fecha,puesto")
    assert "Junior Python 0" in csv_text and "https://e.invalid/1" in csv_text


def test_carta_con_y_sin_datos(tmp_path):
    job = _store(tmp_path).get_job(1)
    vacia = seguimiento.cover_letter(job, {})
    assert "Empresa 0" in vacia and "Junior Python 0" in vacia and "Me llamo" not in vacia
    llena = seguimiento.cover_letter(job, {"nombre": "Ana", "disponibilidad": "inmediata"})
    assert "Me llamo Ana" in llena and "inmediata" in llena
    kit = seguimiento.apply_kit(job, [], {"salario": "24k"})
    assert "24k" in kit and "<pre>" in kit


def test_candidatura_se_guarda_y_ignora_basura(tmp_path):
    paths = Paths(tmp_path)
    seguimiento.save_candidatura(paths, {"nombre": "Ana", "otros": "  "})
    paths.candidatura.write_text("nombre: Ana\nextra: x\notros: ' '\n", encoding="utf-8")
    assert seguimiento.load_candidatura(paths) == {"nombre": "Ana"}
    paths.candidatura.write_text("- lista\n", encoding="utf-8")
    assert seguimiento.load_candidatura(paths) == {}
    assert "Ana" not in candidatura_view({})[0]


def test_botones_de_seguimiento_caben_en_callback():
    kb = track_keyboard(2 ** 40, "aplicada")
    data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "t:aplicada:%d" % 2 ** 40 not in data and f"t:x:{2 ** 40}" in data
    assert all(len(d.encode()) <= 64 for d in data)


def test_aplicadas_se_parte_en_mensajes_y_csv_es_seguro(tmp_path):
    s = Store(tmp_path / "g.db")
    s.upsert([JobOffer(title=f"=Puesto {i} " + "x" * 80, url=f"https://e.invalid/{i}", source="t",
                       company=f"Empresa{i}" + "C" * 40) for i in range(80)], NOW)
    for j in range(1, 81):
        s.set_decision(j, Decision(matched=["b1"], reasons=[]))
        s.set_track(j, "rechazada", NOW)
    msgs = seguimiento.format_tracked(s.tracked(), NOW)
    assert len(msgs) > 1 and all(len(m) <= 4096 for m in msgs)
    assert "'=Puesto" in seguimiento.to_csv(s.tracked(), s)


def test_estado_repetido_o_antiguo_no_pisa_el_seguimiento(tmp_path):
    import asyncio
    from types import SimpleNamespace

    from jobradar.bot_seguimiento import on_track
    s = _store(tmp_path)
    s.set_track(1, "aplicada", NOW - timedelta(days=8))
    s.set_track(2, "entrevista", NOW)
    answers = []

    class Q:
        message = None

        def __init__(self, data):
            self.data = data

        async def answer(self, text=None):
            answers.append(text)
    ctx = SimpleNamespace(bot_data={"store": s})
    asyncio.run(on_track(SimpleNamespace(callback_query=Q("t:aplicada:1")), ctx))
    assert [j.id for j in s.due_reminders(NOW, 7)] == [1] and "Ya está" in answers[-1]
    asyncio.run(on_track(SimpleNamespace(callback_query=Q("t:guardada:2")), ctx))
    assert s.get_job(2).track == "entrevista"
