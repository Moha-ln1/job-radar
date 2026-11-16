"""Catálogo ampliado: cada opción tiene sinónimos, no se pisan entre áreas y el asistente lo explica."""
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, TimedOut

from jobradar import bot
from jobradar.filters import Synonyms, evaluate
from jobradar.models import Exclusions, Search, build_offer
from jobradar.normalize import fold
from jobradar.radar import _DATA

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


@pytest.mark.parametrize("location", ["Seattle, Washington, Estados Unidos", "Gran Londres, Inglaterra, Reino Unido",
                                      "Toronto, Ontario, Canadá", "Dubái, Emiratos Árabes Unidos"])
def test_linkedin_foreign_locations_in_spanish_are_rejected(location):
    s = Search(id="s", name="s", tipos=["practicas"], ubicaciones=["espana"])
    o = build_offer(source="linkedin", url="https://example.com/1", title="Cybersecurity Intern", location=location)
    assert not evaluate(o, [s], Exclusions(), SYN, CAT, NOW).ok


def test_ambiguous_synonyms_fixed():
    def ok(title, area):
        o = build_offer(source="t", url="https://example.com/1", title=title)
        return evaluate(o, [Search(id="s", name="s", areas=[area])], Exclusions(), SYN, CAT, NOW).ok
    assert not ok("Prácticas Marketing Digital: Web, Redes Sociales, SEO", "sistemas")
    assert ok("Prácticas Técnico de Redes", "sistemas")
    assert not ok("Prácticas técnico control de calidad", "qa")
    assert ok("Prácticas técnico control de calidad", "ingenieria")
    assert ok("QA Tester Junior", "qa")


def test_espana_includes_towns_listed_only_in_provinces():
    s = Search(id="s", name="s", tipos=["junior"], ubicaciones=["espana"])
    o = build_offer(source="linkedin", url="https://example.com/1", title="Jr. Software Engineer", location="Tomares")
    assert evaluate(o, [s], Exclusions(), SYN, CAT, NOW).ok
    assert "granada ya está incluida" in " ".join(bot.redundancy_notes(
        {"modalidades": [], "ubicaciones": ["granada", "espana"]}, CAT)).lower()


def test_unknown_area_passes_to_digest_but_other_area_is_rejected():
    s = [Search(id="s", name="s", tipos=["practicas"], areas=["programador", "data"], prioridad="alta")]
    unknown = build_offer(source="t", url="https://example.com/1", title="Estudiante en prácticas_Departamento TEF 7")
    d = evaluate(unknown, s, Exclusions(), SYN, CAT, NOW)
    assert d.ok and d.priority == "normal" and "área no indicada" in d.reasons[0]
    other = build_offer(source="t", url="https://example.com/2", title="Prácticas en PRL")
    assert not evaluate(other, s, Exclusions(), SYN, CAT, NOW).ok
    known = build_offer(source="t", url="https://example.com/3", title="Prácticas Desarrollador Python")
    assert evaluate(known, s, Exclusions(), SYN, CAT, NOW).priority == "alta"


def test_desarrollo_web_is_programacion():
    o = build_offer(source="t", url="https://example.com/1", title="PRÁCTICAS EN EMPRESA + DISEÑO Y DESARROLLO WEB")
    assert evaluate(o, [Search(id="s", name="s", tipos=["practicas"], areas=["programador"])],
                    Exclusions(), SYN, CAT, NOW).ok


def test_infojobs_uses_configured_keywords_max_three():
    from jobradar.config import Settings
    from jobradar.sources import SourceContext
    from jobradar.sources.html_portals import _infojobs_terms
    ctx = SourceContext(http=None, settings=Settings(sources={"infojobs": {"keywords": ["a", "b", "c", "d"]}}),
                        terms=["prácticas"])
    assert _infojobs_terms(ctx) == ["a", "b", "c"]
    ctx = SourceContext(http=None, settings=Settings(), terms=["prácticas", "intern"])
    assert _infojobs_terms(ctx) == ["prácticas", "intern"]


def test_tecnico_informatico_is_sistemas():
    o = build_offer(source="t", url="https://example.com/1", title="Técnico Informático Junior – Granada")
    assert evaluate(o, [Search(id="s", name="s", tipos=["junior"], areas=["sistemas"])],
                    Exclusions(), SYN, CAT, NOW).ok


def test_company_boards_are_not_discarded_by_age():
    old = datetime(2026, 10, 1, tzinfo=timezone.utc)
    s = [Search(id="s", name="s", tipos=["practicas"])]
    board = build_offer(source="greenhouse:bitpanda", url="https://example.com/1", title="Intern, Data Engineer",
                        posted_at=old)
    portal = build_offer(source="linkedin", url="https://example.com/2", title="Intern, Data Engineer",
                         posted_at=old)
    assert evaluate(board, s, Exclusions(), SYN, CAT, NOW).ok
    assert not evaluate(portal, s, Exclusions(), SYN, CAT, NOW).ok


def test_linkedin_location_names():
    from jobradar.sources.html_portals import linkedin_location
    assert linkedin_location("España") == "Spain"
    assert linkedin_location("Sevilla") == "Sevilla, Spain"
    assert linkedin_location("País Vasco") == "Basque Country, Spain"
    assert linkedin_location("Lisboa") == "Lisboa"  # texto libre: tal cual
    for key, entry in CAT.ubicaciones.items():
        assert entry.get("linkedin"), f"'{key}' sin nombre para LinkedIn"


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
