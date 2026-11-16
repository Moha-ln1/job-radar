"""Catálogo ampliado: cada opción tiene sinónimos, no se pisan entre áreas y el asistente lo explica."""
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, TimedOut

from jobradar import bot
from jobradar.filters import evaluate
from jobradar.models import Exclusions, Search, build_offer
from jobradar.normalize import fold
from jobradar.radar import _DATA
from jobradar.filters import Synonyms

CAT = bot.default_catalog()
SYN = Synonyms.from_files(_DATA / "sinonimos.yaml", None)
NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def test_every_option_has_a_synonym_group():
    for key in [*CAT.tipos, *CAT.areas, *bot.MODALIDADES]:
        assert fold(key) in SYN.groups, f"'{key}' no tiene grupo en sinonimos.yaml"


def test_area_terms_do_not_overlap():
    # Si un término estuviera en dos áreas, elegir una arrastraría todas las ofertas de la otra.
    owner: dict[str, str] = {}
    for key in CAT.areas:
        for term in SYN.groups[fold(key)]:
            assert term not in owner, f"'{term}' está en '{owner.get(term)}' y en '{key}'"
            owner[term] = key


@pytest.mark.parametrize("title,area", [
    ("Becario/a Departamento Financiero", "finanzas"),
    ("Prácticas en Recursos Humanos", "rrhh"),
    ("Sales Development Intern (SDR)", "ventas"),
    ("Trainee Customer Success", "atencion_cliente"),
    ("Prácticas Ingeniería Industrial - Mantenimiento", "ingenieria"),
    ("Embedded Software Intern", "electronica"),
    ("Junior Product Owner", "producto"),
    ("Graduate Program Consulting", "consultoria"),
    ("Becario Supply Chain", "logistica"),
    ("Prácticas Departamento Legal", "legal"),
    ("Becario/a Comunicación y Prensa", "comunicacion"),
    ("Prácticas Laboratorio I+D", "ciencia"),
    ("Trainee Hotel Management", "hosteleria"),
    ("Prácticas Arquitecto/a BIM", "arquitectura"),
    ("Junior Game Developer (Unity)", "videojuegos"),
])
def test_new_areas_match_real_titles(title, area):
    offer = build_offer(source="t", url="https://example.com/1", title=title)
    s = Search(id="s", name="s", areas=[area])
    assert evaluate(offer, [s], Exclusions(), SYN, CAT, NOW).ok


def test_provinces_include_their_towns_and_reject_others():
    s = Search(id="s", name="s", ubicaciones=["malaga"])
    ok = build_offer(source="t", url="https://example.com/1", title="Prácticas", location="Benalmádena")
    no = build_offer(source="t", url="https://example.com/2", title="Prácticas", location="Sevilla")
    assert evaluate(ok, [s], Exclusions(), SYN, CAT, NOW).ok
    assert not evaluate(no, [s], Exclusions(), SYN, CAT, NOW).ok


def test_wizard_shows_what_each_option_includes():
    s = bot.wizard_state_new()
    bot.toggle(s, "tipos", "practicas")
    text, _ = bot.render_step(s, CAT)
    assert "Incluye:" in text and "intern" in text and "becario" in text
    s["step"] = 3
    bot.toggle(s, "ubicaciones", "granada")
    bot.toggle(s, "ubicaciones", "andalucia")
    text, _ = bot.render_step(s, CAT)
    assert "Granada ya está incluida en Andalucía" in text and "Armilla" in text


def test_three_modalities_note_and_short_name():
    s = bot.wizard_state_new()
    for m in bot.MODALIDADES:
        bot.toggle(s, "modalidades", m)
    for t in ("practicas", "trainee", "bootcamp", "junior"):
        bot.toggle(s, "tipos", t)
    s["step"] = 2
    text, _ = bot.render_step(s, CAT)
    assert "equivalen a «cualquiera»" in text
    assert bot.auto_name(s, CAT) == "Prácticas/Trainee +2 · Presencial/Híbrido +1"


async def test_answer_ignores_network_and_stale_queries():
    for exc in (TimedOut(), BadRequest("Query is too old and response timeout expired")):
        q = NS(answer=AsyncMock(side_effect=exc))
        await bot._answer(q)  # no lanza
    q = NS(answer=AsyncMock(side_effect=BadRequest("Message to edit not found")))
    with pytest.raises(BadRequest):
        await bot._answer(q)


async def test_error_handler_does_not_message_user_on_network_error():
    send = AsyncMock()
    ctx = NS(error=TimedOut(), bot=NS(send_message=send))
    await bot.on_error(None, ctx)
    send.assert_not_awaited()
