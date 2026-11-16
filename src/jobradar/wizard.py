"""Asistente de terminal (`jobradar configurar`): mismas preguntas y catálogo que el bot."""
from __future__ import annotations

import sys

import questionary

from . import bot, radar
from .config import load_searches, save_searches
from .paths import Paths

OTHER = "__otra__"


class _Cancelled(Exception):
    pass


def _ask(question):
    answer = question.ask()
    if answer is None:  # Ctrl+C
        raise _Cancelled
    return answer


def _pick_many(state: dict, field: str, title: str, catalog) -> None:
    opts = bot.field_options(field, catalog)
    free = [v for v in state[field] if v not in opts]
    choices = [questionary.Choice(label, value=key, checked=key in state[field]) for key, label in opts.items()]
    choices += [questionary.Choice(v, value=v, checked=True) for v in free]
    choices.append(questionary.Choice("✏️  Otra…", value=OTHER))
    answer = _ask(questionary.checkbox(f"{title} (espacio marca, Enter sigue; sin marcar = cualquiera)",
                                       choices=choices))
    extra = []
    if OTHER in answer:
        text = _ask(questionary.text("Escribe los términos que quieres añadir (separados por comas):"))
        extra = [t.strip() for t in text.split(",") if t.strip()]
    chosen = [v for v in answer if v != OTHER]
    state[field] = chosen + [t for t in extra if t not in chosen]


def run_questions(state: dict, catalog) -> dict:
    """Recorre los pasos del asistente rellenando `state` (lanza _Cancelled si se aborta)."""
    _pick_many(state, "tipos", "Tipo", catalog)
    _pick_many(state, "areas", "Área", catalog)
    _pick_many(state, "modalidades", "Modalidad", catalog)
    if state["modalidades"] != ["remoto"]:  # misma regla que el bot (bot.advance)
        _pick_many(state, "ubicaciones", "Ubicación", catalog)
    prio = bot.field_options("prioridad", catalog)
    answer = _ask(questionary.select(
        "Avisos", choices=[questionary.Choice(label, value=key) for key, label in prio.items()],
        default="alta"))
    bot.toggle(state, "prioridad", answer)
    default_name = bot.auto_name(state, catalog)
    name = _ask(questionary.text("Nombre de la búsqueda:", default=default_name)).strip()
    if name and name != default_name:
        state["name"], state["name_custom"] = name[:60], True
    return state


def main(paths: Paths | None = None) -> int:
    if not sys.stdin.isatty():
        print("El asistente necesita una terminal interactiva. Crea las búsquedas desde Telegram con /busquedas.")
        return 2
    paths = paths or Paths.default()
    catalog = bot.default_catalog()
    searches, excl = load_searches(paths.searches)
    state = bot.wizard_state_new(s.id for s in searches)
    try:
        run_questions(state, catalog)
        print()
        print("Resumen de la búsqueda:")
        print(f"  Nombre: {bot.state_to_search(state, catalog).name}")
        for line in bot.describe_lines(state, catalog):
            print(f"  {line}")
        if not _ask(questionary.confirm("¿Guardar esta búsqueda?", default=True)):
            print("Cancelado: no se ha guardado nada.")
            return 0
    except (_Cancelled, KeyboardInterrupt):
        print("\nCancelado: no se ha guardado nada.")
        return 0
    search = bot.state_to_search(state, catalog)
    save_searches(paths.searches, [*searches, search], excl)
    found = radar.reevaluate(paths, [search.id])
    print(f"Búsqueda «{search.name}» guardada." +
          (f" Ya encaja con {len(found)} ofertas guardadas." if found else ""))
    print("Puedes crear más desde Telegram con /busquedas")
    return 0
