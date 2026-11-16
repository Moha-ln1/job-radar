"""APIs oficiales: fixtures sintéticos fieles a la doc pública (no hay claves para petición real)."""
import logging
from datetime import datetime, timezone

import httpx
import pytest

from jobradar.sources import all_fetchers, html_portals as hp, official_apis as oa
from test_html_portals import fixture, run

ADZUNA = {"count": 2, "results": [
    {"id": "1", "title": "Becario <b>Python</b> &amp; datos", "company": {"display_name": "Acme SL"},
     "location": {"display_name": "Granada, Andalucía", "area": ["España", "Andalucía", "Granada"]},
     "redirect_url": "https://www.adzuna.es/land/ad/123?se=abc&utm_source=x", "created": "2026-11-12T09:30:00Z",
     "category": {"label": "Trabajos de TI", "tag": "it-jobs"}, "contract_time": "full_time",
     "description": "Prácticas de <b>desarrollo</b>"},
    {"id": "2", "title": "Otro puesto", "company": {"display_name": "Beta"}, "location": {"display_name": "Madrid"},
     "redirect_url": "https://www.adzuna.es/land/ad/456", "created": "2026-11-10T00:00:00Z"},
]}
JOOBLE = {"totalCount": 1, "jobs": [
    {"title": "Prácticas <b>Marketing</b>", "location": "Granada", "snippet": "Se busca &nbsp;becario",
     "salary": "", "source": "x.com", "type": "Internship", "link": "https://es.jooble.org/desc/-123",
     "company": "Gamma SA", "updated": "2026-11-13T10:00:00.0000000", "id": 123}]}


def test_adzuna_campo_a_campo():
    a, b = oa._parse_adzuna(ADZUNA)
    assert a.title == "Becario Python & datos"
    assert (a.company, a.location, a.category, a.source) == ("Acme SL", "Granada, Andalucía", "Trabajos de TI", "adzuna")
    assert a.url == "https://www.adzuna.es/land/ad/123?se=abc"
    assert a.posted_at == datetime(2026, 11, 12, 9, 30, tzinfo=timezone.utc)
    assert a.description == "Prácticas de desarrollo" and b.category is None


def test_jooble_campo_a_campo_y_titulo_limpio():
    (o,) = oa._parse_jooble(JOOBLE)
    assert o.title == "Prácticas Marketing"
    assert (o.company, o.location, o.source) == ("Gamma SA", "Granada", "jooble")
    assert o.url == "https://es.jooble.org/desc/-123"
    assert o.posted_at == datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)
    assert "becario" in o.description


@pytest.mark.parametrize("name", ["adzuna", "jooble"])
async def test_sin_clave_devuelve_vacio_y_no_pide_nada(name, caplog):
    def handler(req):
        raise AssertionError("no debe haber peticiones")

    with caplog.at_level(logging.INFO, logger="jobradar.sources"):
        assert await run(oa.FETCHERS[name], handler) == []
    assert "sin clave: fuente desactivada" in caplog.text


async def test_adzuna_peticion_y_topes():
    seen = []

    def handler(req):
        seen.append(req.url)
        return httpx.Response(200, json=ADZUNA)

    offers = await run(oa.fetch_adzuna, handler, terms=list("abcdef"), locations=["Granada", "España", "Madrid"],
                       env={"ADZUNA_APP_ID": "i", "ADZUNA_APP_KEY": "k"})
    assert len(seen) == 8 and len(offers) == 2
    u = seen[0]
    assert u.host == "api.adzuna.com" and u.path == "/v1/api/jobs/es/search/1"
    assert dict(u.params) == {"app_id": "i", "app_key": "k", "what": "a", "where": "Granada",
                              "results_per_page": "50", "max_days_old": "14"}


async def test_jooble_post_con_clave_en_ruta():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=JOOBLE)

    offers = await run(oa.fetch_jooble, handler, env={"JOOBLE_API_KEY": "KEY"})
    assert seen[0].method == "POST" and seen[0].url.host == "es.jooble.org" and seen[0].url.path == "/api/KEY"
    assert b'"page":1' in seen[0].read()
    assert len(offers) == 1


def test_registrado():
    assert {"adzuna", "jooble"} <= set(all_fetchers())


# ------------------------------------------------------------------------------------------ InfoJobs
IJ = {"offers": [
    {"id": "a", "title": "Becario de marketing", "province": {"id": 33, "value": "Granada"}, "city": "Granada",
     "link": "https://www.infojobs.net/granada/becario-marketing/of-i0123456789abcdef0123456789abcd",
     "published": "2026-11-12T09:30:00.000Z", "updated": "2026-11-13T09:30:00.000Z",
     "author": {"id": "x", "name": "Acme SL", "uri": "u"}, "teleworking": {"id": 2, "value": "Solo teletrabajo"},
     "category": {"id": 1, "value": "Marketing y Comunicación"}, "experienceMin": {"id": 1, "value": "Sin experiencia"}},
    {"id": "b", "title": "Becario IT", "province": {"value": "Madrid"},
     "link": "https://www.infojobs.net/madrid/becario-it/of-i1123456789abcdef0123456789abcd",
     "published": "2026-11-12T09:30:00.000Z", "author": {"name": "Beta"}, "teleworking": {"value": "Híbrido"}},
    {"id": "c", "title": "Becario RRHH", "province": {"value": "Sevilla"},
     "link": "https://www.infojobs.net/sevilla/becario-rrhh/of-i2123456789abcdef0123456789abcd",
     "published": "2026-11-12T09:30:00.000Z", "author": {"name": "Gamma"}, "teleworking": {"value": "Presencial"}},
]}


def test_infojobs_api_campos_ampliados():
    a, b, c = hp._parse_infojobs_api(IJ)
    assert (a.modality, b.modality, c.modality) == ("remoto", "hibrido", "presencial")
    assert a.category == "Marketing y Comunicación" and a.description == "Experiencia mínima: Sin experiencia"
    assert b.location == "Madrid"


async def test_infojobs_con_clave_usa_solo_api_y_params():
    seen = []

    def handler(req):
        seen.append(req.url)
        return httpx.Response(200, json=IJ)

    offers = await run(hp.fetch_infojobs, handler, env={"INFOJOBS_CLIENT_ID": "i", "INFOJOBS_CLIENT_SECRET": "s"})
    assert len(seen) == 1 and seen[0].host == "api.infojobs.net" and len(offers) == 3
    assert dict(seen[0].params) == {"q": "prácticas", "maxResults": "50", "order": "updated-desc",
                                    "sinceDate": "_7_DAYS"}


async def test_infojobs_401_avisa_y_cae_a_html(caplog):
    seen = []

    def handler(req):
        seen.append(req.url.host)
        if req.url.host == "api.infojobs.net":
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(200, text=fixture("infojobs_search.html"))

    with caplog.at_level(logging.WARNING, logger="jobradar.sources"):
        offers = await run(hp.fetch_infojobs, handler, env={"INFOJOBS_CLIENT_ID": "i", "INFOJOBS_CLIENT_SECRET": "bad"})
    assert seen == ["api.infojobs.net", "www.infojobs.net"] and len(offers) == 2
    assert "clave de InfoJobs no válida" in caplog.text
