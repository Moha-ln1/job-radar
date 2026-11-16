"""Vigilancia de páginas: fixture recortado de 42 Málaga (2026-11-16)."""
from pathlib import Path

import httpx
import pytest

from jobradar.config import HttpSettings, Settings
from jobradar.http import Http, SourceBlocked
from jobradar.sources import SourceContext, watch

FIX = Path(__file__).parent / "fixtures"
FAST = HttpSettings(delay_seconds=[0, 0], timeout_seconds=5)
URL = "https://42malaga.com/"


def page() -> str:
    return (FIX / "watch_42malaga.html").read_text(encoding="utf-8")


def test_parse_extrae_solo_enlaces_del_contenido_principal():
    offers = watch._parse_watch(page(), URL, "42 Málaga")
    assert [(o.title, o.url) for o in offers] == [
        ("¡Sumérgete!", "https://candidatura.42malaga.com/users/sign_up"),
        ("Ven a conocer el campus", "https://conoce-42malaga-2026.eventbrite.es/"),
        ("Reserva tu plaza", "https://pdpython-diciembre-42malaga.eventbrite.es/"),
        ("Reserva tu plaza", "https://ddciber-diciembre-42malaga.eventbrite.es/"),
        ("Descubre más", "https://www.42malaga.com/programa/"),
        ("Ver mas FAQs", "https://42malaga.com/faqs/"),  # el primero gana: /faqs/#pregunta-3 sin ancla
        ("Ver mas FAQs", "https://www.42malaga.com/faqs/"),
    ]
    assert all(o.source == "watch:42 Málaga" and o.category == "vigilancia" and o.company is None for o in offers)


def test_parse_descarta_ruido():
    urls = {o.url for o in watch._parse_watch(page(), URL, "x")}
    for noise in ("linkedin", "x.com", "mailto", "tel:", ".pdf", "otraempresa", "/blog/", "/contacto/", "42barcelona"):
        assert not any(noise in u for u in urls), noise
    assert not any(u.endswith("/ok") for u in urls)  # texto de menos de 3 caracteres
    assert not any("#" in u for u in urls)


def test_parse_usa_atributo_title_si_el_enlace_no_tiene_texto():
    html = '<body><main><a href="/a" title="Programa de becas"><img src="x.png"></a></main></body>'
    (o,) = watch._parse_watch(html, URL, "x")
    assert (o.title, o.url) == ("Programa de becas", "https://42malaga.com/a")


async def test_fetch_vigila_cada_pagina_y_sigue_si_una_falla():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "roto.example":
            return httpx.Response(404)
        return httpx.Response(200, text=page())

    settings = Settings(watch=[{"name": "Roto", "url": "https://roto.example/"},
                               {"name": "42 Málaga", "url": URL}])
    async with Http(FAST, transport=httpx.MockTransport(handler)) as http:
        offers = await watch.fetch_watch(SourceContext(http=http, settings=settings))
    assert len(offers) == 7 and {o.source for o in offers} == {"watch:42 Málaga"}


async def test_fetch_propaga_bloqueo():
    settings = Settings(watch=[{"name": "A", "url": URL}])
    async with Http(FAST, transport=httpx.MockTransport(lambda r: httpx.Response(429))) as http:
        with pytest.raises(SourceBlocked):
            await watch.fetch_watch(SourceContext(http=http, settings=settings))


def test_registro():
    assert set(watch.FETCHERS) == {"watch"}
