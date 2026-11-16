import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from jobradar import radar
from jobradar.config import HttpSettings, Settings, save_searches
from jobradar.filters import Catalog, Synonyms
from jobradar.http import Http
from jobradar.models import Exclusions, JobOffer, Search
from jobradar.paths import Paths
from jobradar.radar import (derive_locations, derive_terms, due_sources, init_baseline, reevaluate,
                            run_sources, scan)
from jobradar.sources import SourceContext
from jobradar.store import Store

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
DATA = radar._DATA


def offer(title, url, source="fake", company="Acme", **kw):
    return JobOffer(title=title, url=url, source=source, company=company, **kw)


@pytest.fixture
def paths(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "sources:\n  a: {enabled: true}\n  b: {enabled: true}\n  nada: {enabled: false}\n", encoding="utf-8")
    save_searches(tmp_path / "busquedas.yaml",
                  [Search(id="s1", name="Prácticas dev", tipos=["practicas"], areas=["programador"],
                          ubicaciones=["granada"])], Exclusions())
    return Paths(tmp_path)


@pytest.fixture
def http():
    return Http(HttpSettings(delay_seconds=[0, 0]),
                transport=httpx.MockTransport(lambda r: httpx.Response(200)))


def fixed(*offers):
    async def fetch(ctx):
        return list(offers)
    return fetch


async def boom(ctx):
    raise RuntimeError("se cayó")


async def slow(ctx):
    await asyncio.sleep(5)
    return []


GOOD = offer("Becario Developer", "https://a.com/1", location="Granada")
BAD = offer("Contable senior", "https://a.com/2", location="Granada")


def test_derive_terms_y_locations():
    syn = Synonyms.from_files(DATA / "sinonimos.yaml")
    cat = Catalog.from_file(DATA / "catalogo.yaml")
    s = Search(id="s", name="x", tipos=["practicas"], areas=["programador"], ubicaciones=["granada"])
    terms = derive_terms([s], syn, cat)
    assert terms[0] == "prácticas" and "intern" in terms and "developer" in terms
    assert len(terms) == len(set(terms)) <= 8
    assert derive_locations([s], cat) == ["Granada"]
    assert derive_locations([], cat) == ["España"]


def test_due_sources():
    store = Store(":memory:")
    settings = Settings(sources={"a": {"enabled": True}, "b": {"enabled": True, "min_interval_hours": 6},
                                 "c": {"enabled": True}, "nada": {"enabled": False}})
    store.record_run("a", NOW - timedelta(hours=3), True, 1)
    store.record_run("b", NOW - timedelta(hours=3), True, 1)
    assert due_sources(settings, store, NOW) == ["a", "c"]


async def test_fuente_falla_y_otra_se_guarda(paths, http):
    rep = await scan(paths, NOW, fetchers={"a": boom, "b": fixed(GOOD)}, http=http)
    assert rep.source_status["a"].error == "se cayó"
    assert rep.source_status["b"].error is None
    assert [j.title for j in rep.new_matched] == ["Becario Developer"]
    assert len(rep.health_alerts) == 1 and "a" in rep.health_alerts[0]


async def test_timeout_por_fuente(paths, http):
    ctx = SourceContext(http=http, settings=Settings())
    res = await run_sources(ctx, ["a", "b"], {"a": slow, "b": fixed(GOOD)}, timeout=0.05)
    assert "tiempo de espera" in res["a"].error and res["b"].offers == [GOOD]


async def test_watch_salta_filtros(paths, http):
    w = offer("Convocatoria cualquiera de cosas", "https://w.com/1", source="watch:ayto", company=None)
    rep = await scan(paths, NOW, only=["a"], fetchers={"a": fixed(w, BAD)}, http=http)
    assert [j.title for j in rep.new_matched] == ["Convocatoria cualquiera de cosas"]
    assert rep.new_matched[0].reasons[0].startswith("página vigilada: enlace nuevo")
    assert rep.new_discarded == 1


async def test_dry_run_no_escribe(paths, http):
    rep = await scan(paths, NOW, only=["a"], fetchers={"a": fixed(GOOD)}, http=http, dry_run=True)
    assert len(rep.new_matched) == 1
    assert not paths.db.exists() and not paths.state.exists()


async def test_segundo_scan_sin_novedades_y_postings_nuevos(paths, http):
    f = {"a": fixed(GOOD)}
    first = await scan(paths, NOW, only=["a"], fetchers=f, http=http)
    store = Store(paths.db)
    store.mark_notified(first.new_matched[0].id, 7, NOW)
    store.close()
    again = await scan(paths, NOW, only=["a"], fetchers=f, http=http)
    assert again.new_matched == [] and again.new_discarded == 0
    twin = offer("Becario Developer", "https://b.com/9", source="otra", location="Granada")
    third = await scan(paths, NOW, only=["a"], fetchers={"a": fixed(GOOD, twin)}, http=http)
    assert third.new_matched == []
    assert [(j.title, p.url) for j, p in third.new_postings_for_notified] == [
        ("Becario Developer", "https://b.com/9")]


async def test_init_baseline_no_avisa(paths, http):
    rep = await init_baseline(paths, NOW, only=["a"], fetchers={"a": fixed(GOOD, BAD)}, http=http)
    assert rep.new_matched == []
    store = Store(paths.db)
    assert all(j.notified_at for j in store.jobs_since(1, NOW + timedelta(hours=1)))
    store.close()


async def test_reevaluate_recupera_descartado(paths, http):
    other = offer("Becario de Marketing", "https://a.com/3", location="Granada")
    await scan(paths, NOW, only=["a"], fetchers={"a": fixed(other)}, http=http)
    save_searches(paths.searches, [
        Search(id="s1", name="Prácticas dev", tipos=["practicas"], areas=["programador"]),
        Search(id="s2", name="Prácticas marketing", tipos=["practicas"], areas=["marketing"])], Exclusions())
    found = reevaluate(paths, ["s2"], 14, NOW)
    assert [j.title for j in found] == ["Becario de Marketing"] and found[0].status == "avisada"
    assert reevaluate(paths, ["s2"], 14, NOW) == []


def test_enfriamiento_tras_bloqueos_seguidos(tmp_path):
    from datetime import datetime, timedelta, timezone
    from jobradar.config import Settings
    from jobradar.radar import cooldown_until, due_sources
    from jobradar.store import Store

    st = Settings(sources={"infojobs": {"enabled": True, "min_interval_hours": 6}})
    store = Store(tmp_path / "db.sqlite")
    t0 = datetime(2026, 11, 16, 8, tzinfo=timezone.utc)
    store.record_run("infojobs", t0, False, 0, None, "www.infojobs.net bloquea las peticiones (HTTP 200)")
    assert cooldown_until(st, store, "infojobs") == t0 + timedelta(hours=6)
    t1 = t0 + timedelta(hours=7)
    store.record_run("infojobs", t1, False, 0, None, "www.infojobs.net bloquea las peticiones (HTTP 403)")
    assert cooldown_until(st, store, "infojobs") == t1 + timedelta(hours=12)   # se duplica
    assert "infojobs" not in due_sources(st, store, t1 + timedelta(hours=8))
    assert "infojobs" in due_sources(st, store, t1 + timedelta(hours=13))
    store.record_run("infojobs", t1 + timedelta(hours=13), True, 40, 90.0, None)
    assert cooldown_until(st, store, "infojobs") is None                      # vuelve a cero


def test_un_error_que_no_es_bloqueo_no_enfria(tmp_path):
    from datetime import datetime, timezone
    from jobradar.config import Settings
    from jobradar.radar import cooldown_until
    from jobradar.store import Store

    st = Settings(sources={"x": {"enabled": True}})
    store = Store(tmp_path / "db.sqlite")
    store.record_run("x", datetime(2026, 11, 16, tzinfo=timezone.utc), False, 0, None, "tiempo de espera agotado (90 s)")
    assert cooldown_until(st, store, "x") is None


def test_enlaces_vigilados_convocatoria_urgente_y_resto_al_resumen():
    from jobradar.models import build_offer
    from jobradar.radar import watch_decision

    def prio(title, url):
        return watch_decision(build_offer(title=title, url=url, source="watch:X", category="vigilancia")).priority
    assert prio("Reserva tu plaza", "https://pdpython-42malaga.eventbrite.es/") == "alta"
    assert prio("¡Sumérgete!", "https://candidatura.42malaga.com/users/sign_up") == "alta"
    assert prio("Inscripciones abiertas", "https://factoriaf5.org/bootcamp-ia") == "alta"
    assert prio("Escríbenos", "https://spain.generation.org/contacto/") == "normal"
    assert prio("Más Prensa", "https://spain.generation.org/press/") == "normal"
