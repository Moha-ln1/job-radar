"""Bot de Telegram: configuración con botones (búsquedas, exclusiones), revisión de descartadas y estado.

Todos los handlers solo atienden al chat_id configurado; el resto de chats no recibe respuesta."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html import escape

from telegram import (BotCommand, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update)
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError
from telegram.ext import (Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, TypeHandler, filters)

from . import notify, radar, scheduler, telegram_io
from .config import (ConfigError, add_user_synonym, load_env, load_searches, save_searches)
from .filters import Catalog
from .models import Decision, Exclusions, Search
from .normalize import fold, norm_company
from .paths import Paths
from .sources.official_apis import missing_keys
from .store import Store

_log = logging.getLogger("jobradar.bot")
STALE_MENU = "Este menú ha caducado, vuelve a abrir /busquedas"
_catalog_cache: Catalog | None = None

COMMANDS = [
    ("start", "Saludo y primeros pasos"),
    ("busquedas", "Crear, editar, pausar o borrar búsquedas"),
    ("excluir", "Palabras y empresas excluidas"),
    ("fuentes", "Activar o desactivar fuentes de ofertas"),
    ("empresas", "Webs de empleo de empresas que se leen"),
    ("paginas", "Páginas de convocatorias que se vigilan"),
    ("descartadas", "Ofertas descartadas en las últimas 24 h"),
    ("probar", "Probar un título: /probar <texto>"),
    ("recientes", "Ofertas encontradas últimamente"),
    ("estado", "Estado de las fuentes"),
    ("silencio", "Sin avisos hasta mañana a las 08:00"),
    ("escanear", "Escanear ahora"),
    ("ayuda", "Lista de comandos"),
]

# --- asistente de búsquedas: lógica pura ---
STEP_FIELDS = ["tipos", "areas", "modalidades", "ubicaciones", "prioridad"]
STEP_TITLES = ["Tipo", "Área", "Modalidad", "Ubicación", "Avisos"]
SUMMARY_STEP = len(STEP_FIELDS)
MODALIDADES = {"presencial": "Presencial", "hibrido": "Híbrido", "remoto": "Remoto"}
PRIORIDADES = {"alta": "🔥 Al momento", "normal": "📰 Resumen diario"}
_LIST_FIELDS = ("tipos", "areas", "modalidades", "ubicaciones")


def default_catalog() -> Catalog:
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = Catalog.from_file(radar._DATA / "catalogo.yaml")
    return _catalog_cache


def new_id(existing_ids) -> str:
    taken = set(existing_ids)
    n = 1
    while f"b{n}" in taken:
        n += 1
    return f"b{n}"


def wizard_state_new(existing_ids=()) -> dict:
    return {"id": new_id(existing_ids), "name": "", "name_custom": False, "step": 0,
            "tipos": [], "areas": [], "modalidades": [], "ubicaciones": [], "prioridad": "alta",
            "paused": False}


def toggle(state: dict, field: str, value: str) -> dict:
    """Marca/desmarca una opción (o fija la prioridad)."""
    if field == "prioridad":
        state["prioridad"] = value
    elif field in _LIST_FIELDS:
        if value in state[field]:
            state[field].remove(value)
        else:
            state[field].append(value)
    else:
        raise ValueError(f"campo desconocido: {field}")
    return state


def field_options(field: str, catalog: Catalog) -> dict[str, str]:
    return {
        "tipos": catalog.tipos, "areas": catalog.areas, "modalidades": MODALIDADES,
        "ubicaciones": {k: v.get("label", k) for k, v in catalog.ubicaciones.items()},
        "prioridad": PRIORIDADES,
    }[field]


def _labels(state: dict, field: str, catalog: Catalog) -> list[str]:
    opts = field_options(field, catalog)
    return [opts.get(v, v) for v in state[field]]


def _short(labels: list[str], keep: int = 2) -> str:
    return "/".join(labels[:keep]) + (f" +{len(labels) - keep}" if len(labels) > keep else "")


def auto_name(state: dict, catalog: Catalog | None = None) -> str:
    catalog = catalog or default_catalog()
    parts = [_short(_labels(state, f, catalog)) for f in _LIST_FIELDS if state[f]]
    return " · ".join(parts) or "Todas las ofertas"


STEP_HELP = {
    "tipos": "Qué tipo de puesto. Se busca en el título, en español e inglés.",
    "areas": "De qué trata el puesto. Se busca en el título y la categoría de la oferta.",
    "modalidades": "Si la oferta no indica modalidad, se incluye igualmente.",
    "ubicaciones": ("Cada zona incluye sus municipios. Si la ubicación de la oferta no se reconoce, "
                    "se incluye igualmente."),
    "prioridad": "🔥 Al momento: un mensaje en cuanto aparece. 📰 Resumen: todo junto a las 09:00.",
}
_raw_synonyms: dict[str, list[str]] | None = None


def _synonym_examples(key: str) -> list[str]:
    """Términos del grupo de sinónimos tal como están escritos (con tildes), sin la propia clave."""
    global _raw_synonyms
    if _raw_synonyms is None:
        import yaml
        _raw_synonyms = yaml.safe_load((radar._DATA / "sinonimos.yaml").read_text(encoding="utf-8")) or {}
    seen = {fold(key)}
    out = []
    for term in _raw_synonyms.get(key, []):
        if fold(term) not in seen:
            seen.add(fold(term))
            out.append(term)
    return out


def option_hint(field: str, key: str, catalog: Catalog, limit: int = 6) -> str | None:
    """Ejemplos de lo que cubre una opción marcada (para que se vea que no se pierden variantes)."""
    if field == "ubicaciones":
        entry = catalog.ubicaciones.get(key)
        if not entry:
            return None
        examples = [a.title() for a in entry.get("aliases", []) if fold(a) != fold(key)]
    elif field in ("tipos", "areas", "modalidades"):
        label = field_options(field, catalog).get(key, key)
        examples = [t for t in _synonym_examples(key) if fold(t) != fold(label)]
    else:
        return None
    if not examples:
        return None
    more = f" y {len(examples) - limit} más" if len(examples) > limit else ""
    return ", ".join(examples[:limit]) + more


def redundancy_notes(state: dict, catalog: Catalog) -> list[str]:
    """Selecciones que no aportan (no cambian el resultado, solo se explican)."""
    notes = []
    if set(MODALIDADES) <= set(state["modalidades"]):
        notes.append("Las tres modalidades equivalen a «cualquiera».")
    labels = field_options("ubicaciones", catalog)
    for u in state["ubicaciones"]:
        for v in state["ubicaciones"]:
            if u == v or v not in catalog.ubicaciones:
                continue
            terms = set(catalog.location_terms(v))
            if fold(u) in terms or fold(labels.get(u, u)) in terms:
                notes.append(f"{labels.get(u, u)} ya está incluida en {labels[v]}.")
                break
    return notes


def state_to_search(state: dict, catalog: Catalog | None = None) -> Search:
    name = state["name"] if state["name_custom"] and state["name"] else auto_name(state, catalog)
    return Search(id=state["id"], name=name, tipos=list(state["tipos"]), areas=list(state["areas"]),
                  modalidades=list(state["modalidades"]), ubicaciones=list(state["ubicaciones"]),
                  prioridad=state["prioridad"], paused=state.get("paused", False))


def search_to_state(search: Search, catalog: Catalog | None = None) -> dict:
    state = {"id": search.id, "name": search.name, "step": 0, "tipos": list(search.tipos),
             "areas": list(search.areas), "modalidades": list(search.modalidades),
             "ubicaciones": list(search.ubicaciones), "prioridad": search.prioridad,
             "paused": search.paused}
    state["name_custom"] = search.name != auto_name(state, catalog)
    state["orig"] = _content(state)
    return state


_CONTENT_FIELDS = ("tipos", "areas", "modalidades", "ubicaciones")


def _content(state: dict) -> list[list[str]]:
    return [sorted(state[f]) for f in _CONTENT_FIELDS]


def stale_name(state: dict) -> bool:
    """Nombre puesto a mano en una búsqueda cuyo contenido acabas de cambiar: probablemente ya no la describe."""
    return bool(state.get("orig")) and state["name_custom"] and _content(state) != state["orig"]


def advance(state: dict, delta: int) -> dict:
    """Cambia de paso; la ubicación se salta si solo se busca remoto."""
    step = state["step"] + delta
    if step == 3 and state["modalidades"] == ["remoto"]:
        step += delta
    state["step"] = max(0, min(SUMMARY_STEP, step))
    return state


def describe_lines(state: dict, catalog: Catalog) -> list[str]:
    def join(f: str) -> str:
        return ", ".join(_labels(state, f, catalog)) or "Cualquiera"
    lines = [f"Tipo: {join('tipos')}", f"Área: {join('areas')}", f"Modalidad: {join('modalidades')}"]
    if state["modalidades"] != ["remoto"]:
        lines.append(f"Ubicación: {join('ubicaciones')}")
    lines.append(f"Avisos: {PRIORIDADES[state['prioridad']]}")
    return lines


def _rows(buttons: list[InlineKeyboardButton], per_row: int = 2) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def render_step(state: dict, catalog: Catalog) -> tuple[str, InlineKeyboardMarkup]:
    """Texto y botones del paso actual del asistente."""
    step = state["step"]
    name = state["name"] if state["name_custom"] and state["name"] else auto_name(state, catalog)
    if step == SUMMARY_STEP:
        notes = redundancy_notes(state, catalog)
        if stale_name(state):
            notes.append(f"Has cambiado la búsqueda, pero el nombre sigue siendo el de antes. "
                         f"Pulsa 🔄 para llamarla «{auto_name(state, catalog)}» o ✏️ Nombre para elegir otro.")
        text = (f"📋 <b>{escape(name)}</b>\n" + "\n".join(escape(x) for x in describe_lines(state, catalog))
                + "".join(f"\nℹ️ {escape(n)}" for n in notes)
                + "\n\nCada opción incluye sus sinónimos en español e inglés.\n¿Guardar esta búsqueda?")
        kb = [[InlineKeyboardButton("💾 Guardar", callback_data="w:s"),
               InlineKeyboardButton("✏️ Cambiar", callback_data="w:c")],
              [InlineKeyboardButton("✏️ Nombre", callback_data="w:name"),
               InlineKeyboardButton("✖ Cancelar", callback_data="w:x")]]
        if stale_name(state):
            kb.insert(1, [InlineKeyboardButton("🔄 Nombre automático", callback_data="w:auto")])
        return text, InlineKeyboardMarkup(kb)
    field = STEP_FIELDS[step]
    opts = field_options(field, catalog)
    hint = ("Elige cuándo quieres el aviso." if field == "prioridad"
            else "Elige una o varias opciones (sin elegir = cualquiera).")
    text = f"<b>Paso {step + 1}/5 · {STEP_TITLES[step]}</b>\n{STEP_HELP[field]}\n{hint}\n📋 {escape(name)}"
    if field != "prioridad":
        details = [(opts[k], option_hint(field, k, catalog)) for k in state[field] if k in opts]
        details = [(label, h) for label, h in details if h]
        if details:
            text += "\n\n<b>Incluye:</b>" + "".join(f"\n• {escape(label)}: {escape(h)}" for label, h in details)
        notes = [n for n in redundancy_notes(state, catalog)
                 if field in ("modalidades", "ubicaciones")
                 and (field == "modalidades") == n.startswith("Las tres")]
        text += "".join(f"\nℹ️ {escape(n)}" for n in notes)
    buttons = []
    for key, label in opts.items():
        on = state[field] == key if field == "prioridad" else key in state[field]
        buttons.append(InlineKeyboardButton(f"{'✅' if on else '⬜'} {label}", callback_data=f"w:t:{key}"))
    kb = _rows(buttons)
    if field != "prioridad":
        free = [(i, v) for i, v in enumerate(state[field]) if v not in opts]
        kb += _rows([InlineKeyboardButton(f"✅ {v[:30]}", callback_data=f"w:f:{i}") for i, v in free])
        kb.append([InlineKeyboardButton("✏️ Otra…", callback_data="w:o")])
    back = (InlineKeyboardButton("✖ Cancelar", callback_data="w:x") if step == 0
            else InlineKeyboardButton("◀ Atrás", callback_data="w:b"))
    kb.append([back, InlineKeyboardButton("Siguiente ▶", callback_data="w:n")])
    return text, InlineKeyboardMarkup(kb)


# --- vistas puras de listas ---
def searches_view(searches: list[Search], catalog: Catalog) -> tuple[str, InlineKeyboardMarkup]:
    if not searches:
        text = "Aún no tienes búsquedas. Crea la primera con el botón."
    else:
        lines = ["<b>Tus búsquedas</b>"]
        for i, s in enumerate(searches, 1):
            state = search_to_state(s, catalog)
            detail = "; ".join(line for line in describe_lines(state, catalog))
            lines.append(f"{i}. {'⏸ ' if s.paused else ''}<b>{escape(s.name)}</b>\n    {escape(detail)}")
        text = "\n".join(lines)
    kb = []
    for s in searches:
        kb.append([InlineKeyboardButton(f"✏️ {s.name[:22]}", callback_data=f"s:e:{s.id}"),
                   InlineKeyboardButton("▶" if s.paused else "⏸", callback_data=f"s:p:{s.id}"),
                   InlineKeyboardButton("🗑", callback_data=f"s:d:{s.id}")])
    kb.append([InlineKeyboardButton("➕ Nueva búsqueda", callback_data="s:new")])
    return text, InlineKeyboardMarkup(kb)


def exclusions_view(excl: Exclusions) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["<b>Exclusiones</b>",
             "Palabras (en el título): " + (escape(", ".join(excl.words)) or "ninguna"),
             "Empresas: " + (escape(", ".join(excl.companies)) or "ninguna")]
    kb = [[InlineKeyboardButton(f"❌ {w[:28]}", callback_data=f"x:w:{i}")] for i, w in enumerate(excl.words)]
    kb += [[InlineKeyboardButton(f"❌ 🏢 {c[:26]}", callback_data=f"x:c:{i}")]
           for i, c in enumerate(excl.companies)]
    kb.append([InlineKeyboardButton("➕ Palabra", callback_data="x:aw"),
               InlineKeyboardButton("➕ Empresa", callback_data="x:ac")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)


_STOPWORDS = {"para", "with", "from", "that", "this", "your", "into", "como", "mas", "sobre", "entre",
              "desde", "hacia", "junto", "tipo", "area", "the", "and", "for", "los", "las", "una", "uno",
              "unos", "unas", "del", "por"}


def title_tokens(title: str, limit: int = 8) -> list[str]:
    """Palabras significativas del título (≥ 4 letras, sin palabras vacías, sin repetir)."""
    out: list[str] = []
    for w in re.findall(r"[^\W\d_]{4,}", title.lower()):
        if fold(w) not in _STOPWORDS and w not in out:
            out.append(w)
    return out[:limit]


def discarded_groups(jobs, limit: int = 20) -> dict[str, list]:
    """Descartadas agrupadas por motivo (máx. `limit` ofertas en total)."""
    groups: dict[str, list] = {}
    for job in jobs[:limit]:
        groups.setdefault(job.reasons[0] if job.reasons else "sin motivo", []).append(job)
    return groups


# --- utilidades de los handlers ---
def _paths(context) -> Paths:
    return context.bot_data["paths"]


def _store(context) -> Store:
    return context.bot_data["store"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _say(update: Update, text: str, markup=None):
    return await update.effective_chat.send_message(
        text, parse_mode=ParseMode.HTML, reply_markup=markup,
        link_preview_options=telegram_io._NO_PREVIEW)


async def _edit(bot, chat_id, message_id, text, markup=None) -> None:
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id,
                                    parse_mode=ParseMode.HTML, reply_markup=markup,
                                    link_preview_options=telegram_io._NO_PREVIEW)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


async def _answer(query, text: str | None = None) -> None:
    """Responde a la pulsación (quita el reloj del botón). Es solo visual: un corte de red o una
    pulsación antigua no deben impedir que se aplique lo que el usuario ha pedido."""
    try:
        await query.answer(text)
    except BadRequest as exc:
        if "too old" not in str(exc).lower() and "invalid" not in str(exc).lower():
            raise
        _log.info("pulsación sin responder: %s", exc)
    except NetworkError as exc:
        _log.warning("no se pudo responder a la pulsación (red): %s", exc)


async def _ask(update: Update, context, awaiting: tuple, prompt: str) -> None:
    context.user_data["await"] = awaiting
    await update.effective_chat.send_message(prompt, reply_markup=ForceReply(input_field_placeholder="Escribe aquí"))


def _load(context) -> tuple[list[Search], Exclusions]:
    return load_searches(_paths(context).searches)


def _save(context, searches: list[Search], excl: Exclusions) -> None:
    save_searches(_paths(context).searches, searches, excl)


# --- comandos ---
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _say(update, "📡 <b>Job Radar</b>\n"
                       "Rastreo portales y webs de empresas en busca de prácticas, trainee y empleo junior.\n\n"
                       "🔥 Lo que encaja con tus búsquedas te llega al momento.\n"
                       "📰 Lo demás, en un resumen diario.\n\n"
                       "👉 Empieza con /busquedas para decirme qué buscas.\n"
                       "❓ /ayuda lista todos los comandos.")


# /ayuda agrupada; lo que no esté aquí sale al final
_HELP_GROUPS = [
    ("🎯 Qué busco", ("busquedas", "excluir", "probar")),
    ("📬 Ofertas", ("recientes", "descartadas", "escanear", "silencio")),
    ("🛰 Dónde busco", ("fuentes", "empresas", "paginas", "estado")),
]


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    desc = dict(COMMANDS)
    shown: set[str] = set()
    parts = []
    for title, cmds in _HELP_GROUPS:
        lines = [f"/{c} — {escape(desc[c])}" for c in cmds if c in desc]
        shown.update(cmds)
        parts.append(f"<b>{title}</b>\n" + "\n".join(lines))
    rest = [f"/{c} — {escape(d)}" for c, d in COMMANDS if c not in shown]
    if rest:
        parts.append("<b>ℹ️ Otros</b>\n" + "\n".join(rest))
    await _say(update, "\n\n".join(parts))


async def cmd_busquedas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, kb = searches_view(_load(context)[0], default_catalog())
    await _say(update, text, kb)


async def cmd_excluir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, kb = exclusions_view(_load(context)[1])
    await _say(update, text, kb)


async def cmd_probar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args or []).strip()
    if not text:
        await _say(update, "Uso: /probar &lt;título de una oferta&gt;")
        return
    decision = radar.probe(_paths(context), text)
    if decision is None:
        await _say(update, "Ese texto no es un título válido (3 a 200 caracteres, sin HTML).")
        return
    head = "✅ Esta oferta te avisaría" if decision.ok else "❌ Esta oferta se descartaría"
    await _say(update, head + "\n" + "\n".join(f"• {escape(r)}" for r in decision.reasons))


async def cmd_recientes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    searches = _load(context)[0]
    store = _store(context)
    jobs = store.recent(3, _now(), "avisada")[:15]
    items = [(j, store.postings(j.id), notify.search_names(j, searches)) for j in jobs]
    messages = notify.format_digest(items, "🕑 Ofertas de los últimos 3 días")
    if not messages:
        await _say(update, "No hay ofertas que encajen en los últimos 3 días.")
    for m in messages:
        await _say(update, m)


async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    paths, store, now = _paths(context), _store(context), _now()
    rows = []
    settings = scheduler._settings(paths)
    env = load_env(paths.env) if paths.env.exists() else {}
    for name, opts in settings.sources.items():
        runs = store.last_runs(name, 1)
        # Sin clave o apagada no consulta nada: "OK, 0 ofertas" haría pensar que funciona y no encuentra
        note = ("apagada" if not opts.get("enabled", True)
                else "sin clave (opcional)" if missing_keys(name, env) else None)
        if note:
            rows.append({"source": name, "note": note})
        elif runs:
            r = runs[0]
            pause = radar.cooldown_until(settings, store, name)
            rows.append({"source": name, "ts": datetime.fromisoformat(r["ts"]), "ok": r["ok"],
                         "count": r["count"], "filled_pct": r["filled_pct"],
                         "paused_until": pause if pause and pause > now else None})
        else:
            rows.append({"source": name, "ts": None})
    await _say(update, notify.format_status(rows, scheduler.next_scan(paths),
                                            scheduler.silenced_until(paths, now)))


async def cmd_silencio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    paths, now = _paths(context), _now()
    if scheduler.silenced_until(paths, now):
        scheduler.update_state(paths, silence_until=None)
        await _say(update, "🔔 Avisos reactivados.")
        return
    until = scheduler.next_morning(now)
    scheduler.update_state(paths, silence_until=until.isoformat())
    await _say(update, "🔕 Sin avisos hasta mañana a las 08:00. Las ofertas se guardan y llegarán en el "
                       "resumen. Vuelve a escribir /silencio para reactivarlos antes.")


async def cmd_escanear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app, chat = context.application, update.effective_chat.id

    async def run() -> None:
        try:
            report = await scheduler.cycle(app, _paths(context))
            text = "Ya hay un escaneo en marcha." if report is None else notify.format_summary(report)
        except Exception as exc:
            _log.exception("el escaneo manual ha fallado")
            text = f"❌ El escaneo ha fallado: {escape(str(exc))}"
        await telegram_io.send_text(app.bot, chat, text)

    await _say(update, "🔎 Escaneando… te cuento el resultado al terminar.")
    app.create_task(run(), update=update)


async def cmd_descartadas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    jobs = _store(context).discarded(24, _now())
    if not jobs:
        await _say(update, "No se ha descartado nada en las últimas 24 h.")
        return
    for reason, group in discarded_groups(jobs).items():
        lines = [f"📂 <b>{escape(reason)}</b> ({len(group)})"]
        kb = []
        for j in group:
            lines.append(f"• {escape(j.title[:90])}" + (f" — {escape(j.company[:40])}" if j.company else ""))
            kb.append([InlineKeyboardButton(f"➕ Era buena: {j.title[:30]}", callback_data=f"g:{j.id}")])
        await _say(update, "\n".join(lines), InlineKeyboardMarkup(kb))


# --- callbacks ---
async def on_job_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    action, _, raw = query.data.partition(":")
    store = _store(context)
    job = store.get_job(int(raw)) if raw.isdigit() else None
    if job is None:
        await _answer(query, "Esa oferta ya no existe.")
        return
    if action == "h":
        if not job.company:
            await _answer(query, "Esta oferta no tiene empresa.")
            return
        searches, excl = _load(context)
        if norm_company(job.company) not in {norm_company(c) for c in excl.companies}:
            excl.companies.append(job.company)
            _save(context, searches, excl)
        await _answer(query, f"🚫 {job.company} ocultada")
    else:
        store.set_decision(job.id, Decision(matched=[], reasons=["usuario: no me interesa"]))
        await _answer(query, "👎 Descartada")
    await query.edit_message_reply_markup(None)


async def on_era_buena(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    store = _store(context)
    job = store.get_job(int(query.data.split(":")[1]))
    if job is None:
        await _answer(query, "Esa oferta ya no existe.")
        return
    store.set_decision(job.id, Decision(matched=["usuario"], priority="alta",
                                        reasons=["usuario: era buena"]))
    await _answer(query, "Marcada como buena")
    job = store.get_job(job.id)
    await telegram_io.send_job(context.bot, query.message.chat_id, store, job, ["Marcada por ti"])
    tokens = title_tokens(job.title)
    context.user_data["good"] = {"job": job.id, "tokens": tokens}
    kb = [[InlineKeyboardButton(t, callback_data=f"k:{i}")] for i, t in enumerate(tokens)]
    kb.append([InlineKeyboardButton("Ninguna", callback_data="k:x")])
    await _say(update, "¿Qué palabra debería haberla encontrado?", InlineKeyboardMarkup(kb))


async def on_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    good = context.user_data.get("good")
    pick = query.data.split(":")[1]
    if not good or pick == "x" or not pick.isdigit() or int(pick) >= len(good["tokens"]):
        context.user_data.pop("good", None)
        if not good and pick != "x":
            await _answer(query, STALE_MENU)
            return
        await _answer(query)
        await query.edit_message_text("Vale, solo la he marcado como buena.")
        return
    good["token"] = good["tokens"][int(pick)]
    catalog = default_catalog()
    buttons = [InlineKeyboardButton(label, callback_data=f"m:{key}")
               for key, label in {**catalog.tipos, **catalog.areas}.items()]
    await _answer(query)
    await query.edit_message_text(f"¿A qué grupo pertenece «{good['token']}»?",
                                  reply_markup=InlineKeyboardMarkup(_rows(buttons, 3)))


async def on_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    good = context.user_data.pop("good", None)
    key = query.data.split(":", 1)[1]
    catalog = default_catalog()
    label = {**catalog.tipos, **catalog.areas}.get(key)
    if not good or "token" not in good or label is None:
        await _answer(query, STALE_MENU)
        return
    add_user_synonym(_paths(context).user_synonyms, key, good["token"])
    await _answer(query)
    await query.edit_message_text(f"✅ Añadido «{good['token']}» al grupo {label}. "
                                  "Lo tendré en cuenta desde el próximo escaneo.")


async def on_see(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    sid = query.data.split(":", 1)[1]
    store = _store(context)
    searches = _load(context)[0]
    jobs = [j for j in store.recent(14, _now(), "avisada") if sid in j.matched_searches][:20]
    await _answer(query)
    for job in jobs:
        await telegram_io.send_job(context.bot, query.message.chat_id, store, job,
                                   notify.search_names(job, searches))
    if not jobs:
        await _say(update, "No hay ofertas guardadas para esa búsqueda.")


async def on_exclusion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, kind, *rest = query.data.split(":")
    if kind in ("aw", "ac"):
        await _answer(query)
        what = "palabra" if kind == "aw" else "empresa"
        await _ask(update, context, ("excl", kind), f"Escribe la {what} que quieres excluir:")
        return
    searches, excl = _load(context)
    items = excl.words if kind == "w" else excl.companies
    idx = int(rest[0])
    if idx < len(items):
        items.pop(idx)
        _save(context, searches, excl)
    await _answer(query, "Quitada")
    text, kb = exclusions_view(excl)
    await _edit(context.bot, query.message.chat_id, query.message.message_id, text, kb)


async def on_search_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, action, *rest = query.data.split(":")
    sid = rest[0] if rest else None
    searches, excl = _load(context)
    catalog = default_catalog()
    msg = query.message
    await _answer(query)
    if action in ("new", "e"):
        if action == "new":
            state = wizard_state_new(s.id for s in searches)
        else:
            found = next((s for s in searches if s.id == sid), None)
            if found is None:
                return
            state = search_to_state(found, catalog)
        context.user_data["wiz"] = state
        context.user_data["wiz_msg"] = (msg.chat_id, msg.message_id)
        text, kb = render_step(state, catalog)
    else:
        target = next((s for s in searches if s.id == sid), None)
        if target is not None and action == "p":
            target.paused = not target.paused
            _save(context, searches, excl)
        elif target is not None and action == "d":
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Sí, borrar", callback_data=f"s:dd:{sid}"),
                                        InlineKeyboardButton("No", callback_data="s:l")]])
            await _edit(context.bot, msg.chat_id, msg.message_id,
                        f"¿Borrar la búsqueda «{escape(target.name)}»?", kb)
            return
        elif target is not None and action == "dd":
            searches = [s for s in searches if s.id != sid]
            _save(context, searches, excl)
        text, kb = searches_view(searches, catalog)
    await _edit(context.bot, msg.chat_id, msg.message_id, text, kb)


async def _render_wizard(context) -> None:
    state, (chat_id, message_id) = context.user_data["wiz"], context.user_data["wiz_msg"]
    text, kb = render_step(state, default_catalog())
    await _edit(context.bot, chat_id, message_id, text, kb)


async def on_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    state = context.user_data.get("wiz")
    if state is None:
        await _answer(query, STALE_MENU)
        return
    _, action, *rest = query.data.split(":")
    step = state["step"]
    await _answer(query)
    if action == "t" and step < SUMMARY_STEP:
        toggle(state, STEP_FIELDS[step], rest[0])
    elif action == "f" and step < SUMMARY_STEP:
        values = state[STEP_FIELDS[step]]
        if rest[0].isdigit() and int(rest[0]) < len(values):
            values.pop(int(rest[0]))
    elif action == "n":
        advance(state, 1)
    elif action == "b":
        advance(state, -1)
    elif action == "c":
        state["step"] = 0
    elif action == "o":
        await _ask(update, context, ("wiz_other", STEP_FIELDS[step]), "Escribe el término que quieres añadir:")
        return
    elif action == "auto":
        state["name_custom"] = False
    elif action == "name":
        await _ask(update, context, ("wiz_name",), "Escribe el nombre de la búsqueda:")
        return
    elif action == "x":
        context.user_data.pop("wiz", None)
        text, kb = searches_view(_load(context)[0], default_catalog())
        await _edit(context.bot, *context.user_data.pop("wiz_msg"), text, kb)
        return
    elif action == "s":
        await _finish_wizard(update, context, state)
        return
    await _render_wizard(context)


async def _finish_wizard(update: Update, context, state: dict) -> None:
    paths = _paths(context)
    search = state_to_search(state, default_catalog())
    searches, excl = _load(context)
    searches = [search if s.id == search.id else s for s in searches]
    if search.id not in {s.id for s in searches}:
        searches.append(search)
    _save(context, searches, excl)
    found = radar.reevaluate(paths, [search.id])
    chat_id, message_id = context.user_data.pop("wiz_msg")
    context.user_data.pop("wiz", None)
    text = f"✅ Búsqueda «{escape(search.name)}» guardada."
    kb = None
    if found:
        text += f"\nEsta búsqueda ya encaja con {len(found)} ofertas guardadas."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("👀 Ver", callback_data=f"v:{search.id}")]])
    await _edit(context.bot, chat_id, message_id, text, kb)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respuestas a las preguntas con ForceReply."""
    waiting = context.user_data.pop("await", None)
    text = (update.message.text or "").strip()
    if not waiting or not text:
        return
    kind = waiting[0]
    if kind in ("empresa", "pagina"):
        from . import bot_fuentes
        await bot_fuentes.on_reply(update, context, waiting, text)
        return
    if kind == "excl":
        searches, excl = _load(context)
        target = excl.words if waiting[1] == "aw" else excl.companies
        if fold(text) not in {fold(x) for x in target}:
            target.append(text)
            _save(context, searches, excl)
        view_text, kb = exclusions_view(excl)
        await _say(update, view_text, kb)
        return
    state = context.user_data.get("wiz")
    if state is None or "wiz_msg" not in context.user_data:
        await _say(update, STALE_MENU)
        return
    if kind == "wiz_other":
        if text not in state[waiting[1]]:
            state[waiting[1]].append(text)
    elif kind == "wiz_name":
        state["name"], state["name_custom"] = text[:60], True
    await _render_wizard(context)


async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Corta el procesamiento de cualquier actualización que no venga del chat autorizado."""
    chat = update.effective_chat
    if chat is None or chat.id != context.bot_data["chat_id"]:
        raise ApplicationHandlerStop
    if update.callback_query is not None:
        _log.info("botón recibido: callback %s", (update.callback_query.data or "").split(":")[0])
    elif update.message is not None and (update.message.text or "").startswith("/"):
        _log.info("comando recibido: %s", update.message.text.split()[0].split("@")[0])


async def on_error(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    if isinstance(error, BadRequest) and "not modified" in str(error).lower():
        return  # el mensaje ya mostraba ese contenido (doble pulsación): no es un fallo
    if isinstance(error, NetworkError) and not isinstance(error, BadRequest):
        # Corte momentáneo con Telegram: la librería reintenta sola; avisar también fallaría.
        _log.warning("problema de red con Telegram: %s", error)
        return
    _log.exception("error en un handler", exc_info=error)
    chat = update.effective_chat if isinstance(update, Update) else None
    if chat is not None:
        try:
            await context.bot.send_message(chat.id, "⚠️ Algo ha fallado; está anotado en logs/jobradar.log")
        except Exception:
            _log.exception("no se pudo avisar del error al usuario")


async def _post_init(app: Application) -> None:
    await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])


def build_application(paths: Paths) -> Application:
    token, chat = telegram_io.credentials(paths)
    if not token or not chat:
        raise ConfigError(telegram_io.MISSING_CREDENTIALS)
    try:
        chat_id = int(chat)
    except ValueError:
        raise ConfigError("TELEGRAM_CHAT_ID debe ser un número (mira 'jobradar telegram chat-id').") from None
    # Timeouts amplios: en redes domésticas lentas los 5 s por defecto cortan pulsaciones válidas.
    app = (Application.builder().token(token).post_init(_post_init)
           .connect_timeout(15).read_timeout(20).write_timeout(20).pool_timeout(10)
           .get_updates_connect_timeout(15).get_updates_read_timeout(30).build())
    app.bot_data.update(paths=paths, chat_id=chat_id, store=Store(paths.db))
    auth = filters.Chat(chat_id=chat_id)
    app.add_handler(TypeHandler(Update, guard), group=-1)
    commands = {"start": cmd_start, "busquedas": cmd_busquedas, "excluir": cmd_excluir,
                "descartadas": cmd_descartadas, "probar": cmd_probar, "recientes": cmd_recientes,
                "estado": cmd_estado, "silencio": cmd_silencio, "escanear": cmd_escanear,
                "ayuda": cmd_ayuda}
    from . import bot_fuentes
    commands.update(bot_fuentes.HANDLERS)
    for name, fn in commands.items():
        app.add_handler(CommandHandler(name, fn, filters=auth))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & auth, on_text))
    for pattern, fn in [(r"^[hn]:\d+$", on_job_action), (r"^g:\d+$", on_era_buena), (r"^k:", on_token),
                        (r"^m:", on_group), (r"^v:", on_see), (r"^x:", on_exclusion),
                        (r"^s:", on_search_action), (r"^w:", on_wizard), *bot_fuentes.CALLBACKS]:
        app.add_handler(CallbackQueryHandler(fn, pattern=pattern))
    app.add_error_handler(on_error)
    return app
