"""Contrato de los portales HTML: fixtures recortados de peticiones reales (2026-11-16)."""
import base64
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from jobradar.config import HttpSettings, Settings
from jobradar.http import Http, SourceBlocked
from jobradar.sources import SourceContext, html_portals as hp

FIX = Path(__file__).parent / "fixtures"
FAST = HttpSettings(delay_seconds=[0, 0], timeout_seconds=5)


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def by_url(offers, fragment):
    return next(o for o in offers if fragment in o.url)


def assert_recent(dt, delta):
    assert dt is not None and dt.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - delta) - dt) < timedelta(minutes=2)


async def run(fetcher, handler, *, terms=("prácticas",), locations=("Granada",), env=None, sources=None):
    async with Http(FAST, transport=httpx.MockTransport(handler)) as http:
        ctx = SourceContext(http=http, settings=Settings(sources=sources or {}), terms=list(terms),
                            locations=list(locations), env=env or {})
        return await fetcher(ctx)


# ----------------------------------------------------------------------------- parsers
def test_linkedin_campo_a_campo():
    offers = hp._parse_linkedin(fixture("linkedin_search.html"))
    assert len(offers) == 3
    o = offers[0]
    assert o.title == "Software Engineer, Intern"
    assert o.company == "Real-Time Innovations (RTI)"
    assert o.location == "Granada y alrededores"
    assert o.url == "https://es.linkedin.com/jobs/view/software-engineer-intern-at-real-time-innovations-rti-4470439633"
    assert o.posted_at == datetime(2026, 11, 10, tzinfo=timezone.utc)
    assert o.source == "linkedin"
    assert by_url(offers, "4480495911").company == "Enterprise"


def test_infojobs_json_embebido_campo_a_campo():
    offers = hp._parse_infojobs(fixture("infojobs_search.html"))
    assert len(offers) == 2
    o = offers[0]
    assert o.title == "Prácticas Investigación mercados"
    assert o.company == "GfK Retail and Technology España"
    assert o.location == "Valencia"
    assert o.modality == "hibrido"
    assert o.url == ("https://www.infojobs.net/valencia/practicas-investigacion-mercados/"
                     "of-i50b25c4bf54906a0712ff678667340")
    assert o.posted_at == datetime(2026, 11, 10, 12, 0, 7, tzinfo=timezone.utc)
    assert offers[1].company == "CLARIANE" and offers[1].location == "Benalmádena"


def test_infojobs_via_enlaces_sin_json():
    offers = hp._parse_infojobs(fixture("infojobs_cards.html"))
    assert [o.title for o in offers] == ["Prácticas Investigación mercados", "Prácticas Administración y Finanzas"]
    o = offers[0]
    assert o.company == "GfK Retail and Technology España"
    assert o.location == "Valencia"
    assert o.modality == "hibrido"
    assert o.url.endswith("/valencia/practicas-investigacion-mercados/of-i50b25c4bf54906a0712ff678667340")
    assert_recent(o.posted_at, timedelta(days=5))  # "Hace 5d"


def test_infojobs_api_oficial_con_fixture_sintetico():
    data = {"offers": [{
        "id": "abc123", "title": "Becario de marketing", "province": {"id": 33, "value": "Granada"},
        "city": "Granada",
        "link": "https://www.infojobs.net/granada/becario-marketing/of-i0123456789abcdef0123456789abcd",
        "published": "2026-11-12T09:30:00.000Z", "author": {"id": "x", "name": "Acme SL", "uri": "u"},
        "teleworking": {"id": 2, "value": "Solo teletrabajo"},
    }], "currentPage": 1, "totalPages": 1}
    (o,) = hp._parse_infojobs_api(data)
    assert (o.title, o.company, o.location, o.modality) == ("Becario de marketing", "Acme SL", "Granada", "remoto")
    assert o.url == "https://www.infojobs.net/granada/becario-marketing/of-i0123456789abcdef0123456789abcd"
    assert o.posted_at == datetime(2026, 11, 12, 9, 30, tzinfo=timezone.utc)


def test_tecnoempleo_campo_a_campo():
    offers = hp._parse_tecnoempleo(fixture("tecnoempleo_search.html"))
    assert len(offers) == 3
    o = offers[0]
    assert o.title == "Desarrollador/a Oracle APEX"
    assert o.company == "PANEL Sistemas Informáticos"
    assert o.url == ("https://www.tecnoempleo.com/desarrollador-oracle-apex-panel-sistemas-informati/"
                     "pl-sql-sql/rf-ea781ea882a1639ee646")
    assert o.posted_at == datetime(2026, 11, 15, tzinfo=timezone.utc)
    assert o.modality == "remoto" and o.location is None
    h = by_url(offers, "rf-ad371151a2f7b3c2134a")
    assert (h.location, h.modality) == ("Valencia", "hibrido")


def test_infoempleo_campo_a_campo():
    offers = hp._parse_infoempleo(fixture("infoempleo_search.html"))
    assert len(offers) == 4
    o = by_url(offers, "3171348")
    assert o.title == "PRACTICAS auxiliar de administración"
    assert o.company == "Importante empresa del sector de distribución de combustible"
    assert o.location == "A Coruña"
    assert o.url == "https://www.infoempleo.com/ofertasdetrabajo/practicas-auxiliar-de-administracion/3171348/"
    assert_recent(o.posted_at, timedelta(hours=27))  # "Hace 27 horas"
    assert_recent(by_url(offers, "3132561").posted_at, timedelta(hours=3))


def test_primerempleo_campo_a_campo():
    offers = hp._parse_primerempleo(fixture("primerempleo_home.html"))
    assert len(offers) == 4
    o = by_url(offers, "1437095")
    assert o.title == "Contable Fiscalista Gestoria de Empresas"
    assert o.company == "Sanz Vega Abogados"
    assert o.location == "Madrid"
    assert o.url == "https://www.primerempleo.com/primer-empleo/madrid/contable-fiscalista-gestoria-de-empresas/1437095"
    assert o.posted_at is None
    assert by_url(offers, "1437063").url.endswith(
        "/trabajo-estudiantes/madrid/becario-a-campana-de-la-renta-2027-practicas-retribuidas/1437063")


@pytest.mark.parametrize("text,delta", [
    ("Hace 5 días", timedelta(days=5)), ("hace 3 horas", timedelta(hours=3)), ("Hace 5d", timedelta(days=5)),
    ("Hace 2 semanas", timedelta(weeks=2)), ("Hace 12 min", timedelta(minutes=12)),
])
def test_fecha_relativa(text, delta):
    assert_recent(hp._relative_date(text), delta)


def test_fecha_relativa_desconocida():
    assert hp._relative_date("ayer") is None and hp._relative_date(None) is None


# ----------------------------------------------------------------------------- fetch
def _linkedin_page(n: int, start: int) -> str:
    li = re.search(r"<li>.*?</li>", fixture("linkedin_search.html"), re.S).group(0)
    return "<ul>" + "".join(li.replace("4470439633", str(4470000000 + start + i)) for i in range(n)) + "</ul>"


async def test_linkedin_pagina_hasta_tarjetas_menores_de_10():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.url.params))
        start = int(req.url.params["start"])
        return httpx.Response(200, text=_linkedin_page(10 if start < 10 else 4, start))

    offers = await run(hp.fetch_linkedin, handler, sources={"linkedin": {"max_pages": 5}})
    assert [p["start"] for p in seen] == ["0", "10"]
    assert seen[0]["keywords"] == "prácticas" and seen[0]["location"] == "Granada, Spain" and seen[0]["f_TPR"] == "r604800"
    assert len(offers) == 14


async def test_linkedin_respeta_max_pages_y_limita_combinaciones():
    seen = []

    def handler(req):
        seen.append((req.url.params["keywords"], req.url.params["location"], req.url.params["start"]))
        return httpx.Response(200, text=_linkedin_page(10, int(req.url.params["start"])))

    await run(hp.fetch_linkedin, handler, terms=list("abcdef"), locations=["Granada", "España", "Madrid"],
              sources={"linkedin": {"max_pages": 2}})
    assert len(seen) == 5 * 3 * 2  # 5 términos × 3 ubicaciones × 2 páginas
    assert {s[0] for s in seen} == set("abcde") and {s[1] for s in seen} == {"Granada, Spain", "Spain", "Madrid, Spain"}


async def test_linkedin_bloqueo_se_propaga():
    with pytest.raises(SourceBlocked):
        await run(hp.fetch_linkedin, lambda r: httpx.Response(429))


async def test_linkedin_bloqueo_a_mitad_conserva_lo_anterior():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429) if len(calls) > 2 else httpx.Response(200, text=_linkedin_page(4, len(calls) * 10))

    with pytest.raises(SourceBlocked) as info:
        await run(hp.fetch_linkedin, handler, terms=["a", "b"], locations=["Granada", "España"])
    assert len(info.value.partial) == 8  # 2 búsquedas buenas × 4 tarjetas


async def test_infojobs_html_envia_keyword():
    seen = []

    def handler(req):
        seen.append(req.url)
        return httpx.Response(200, text=fixture("infojobs_search.html"))

    offers = await run(hp.fetch_infojobs, handler, terms=["prácticas", "trainee"])
    assert seen[0].host == "www.infojobs.net" and seen[0].params["keyword"] == "prácticas"
    assert len(seen) == 2 and len(offers) == 2  # misma oferta en ambas búsquedas: dedup


async def test_infojobs_usa_api_con_basic_auth_si_hay_claves():
    seen = []
    body = {"offers": [{"title": "Becario de marketing", "city": "Granada", "author": {"name": "Acme SL"},
                        "link": "https://www.infojobs.net/granada/becario/of-iabcdef0123456789abcdef0123456789",
                        "published": "2026-11-12T09:30:00.000Z"}]}

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=body)

    offers = await run(hp.fetch_infojobs, handler,
                       env={"INFOJOBS_CLIENT_ID": "id", "INFOJOBS_CLIENT_SECRET": "sec"})
    assert seen[0].url.host == "api.infojobs.net" and seen[0].url.path == "/api/9/offer"
    assert seen[0].headers["authorization"] == "Basic " + base64.b64encode(b"id:sec").decode()
    assert [o.company for o in offers] == ["Acme SL"]


@pytest.mark.parametrize("fetcher,fix,host,param,expected", [
    (hp.fetch_tecnoempleo, "tecnoempleo_search.html", "www.tecnoempleo.com", "te", 3),
    (hp.fetch_infoempleo, "infoempleo_search.html", "www.infoempleo.com", "q", 4),
])
async def test_fetch_busca_por_termino(fetcher, fix, host, param, expected):
    seen = []

    def handler(req):
        seen.append(req.url)
        return httpx.Response(200, text=fixture(fix))

    offers = await run(fetcher, handler, terms=["prácticas"])
    assert len(offers) == expected and seen[0].host == host and seen[0].params[param] == "prácticas"


async def test_primerempleo_consulta_portada_y_etiquetas_sin_repetir():
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, text=fixture("primerempleo_home.html"))

    offers = await run(hp.fetch_primerempleo, handler, terms=["prácticas"], locations=["Granada", "España"])
    assert seen == ["https://www.primerempleo.com/", "https://www.primerempleo.com/?q=practicas",
                    "https://www.primerempleo.com/?q=granada"]
    assert len(offers) == 4


def test_registro_de_fuentes():
    assert set(hp.FETCHERS) == {"linkedin", "infojobs", "tecnoempleo", "infoempleo", "primerempleo"}
