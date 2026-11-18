"""Formato de mensajes de Telegram (HTML). Funciones puras: no hacen E/S."""
from __future__ import annotations

from datetime import datetime
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .models import Search

MAX_LEN = 4096
_MODALITY = {"presencial": "presencial", "hibrido": "híbrido", "remoto": "remoto"}
_NAMES = {
    "linkedin": "LinkedIn", "infojobs": "InfoJobs", "tecnoempleo": "Tecnoempleo",
    "infoempleo": "Infoempleo", "primerempleo": "Primer Empleo", "remotive": "Remotive",
    "remoteok": "RemoteOK", "weworkremotely": "We Work Remotely", "himalayas": "Himalayas",
    "arbeitnow": "Arbeitnow", "greenhouse": "Greenhouse", "lever": "Lever", "workday": "Workday",
    "smartrecruiters": "SmartRecruiters", "ashby": "Ashby", "workable": "Workable",
}
_SPECIAL_MATCHES = {"watch": "Página vigilada", "usuario": "Marcada por ti"}


def source_label(source: str) -> str:
    """Nombre legible de una fuente: 'greenhouse:x' -> Greenhouse, 'watch:Nombre' -> Nombre."""
    kind, _, rest = source.partition(":")
    if kind == "watch" and rest:
        return rest
    return _NAMES.get(kind.lower(), kind[:1].upper() + kind[1:])


def search_names(job, searches: list[Search]) -> list[str]:
    """Nombres legibles de las búsquedas que encajaron (los ids que ya no existen se omiten)."""
    by_id = {s.id: s.name for s in searches}
    out = []
    for sid in job.matched_searches:
        name = by_id.get(sid) or _SPECIAL_MATCHES.get(sid)
        if name and name not in out:
            out.append(name)
    return out


def _links(postings) -> str:
    seen, parts = set(), []
    for p in postings:
        if p.url in seen:
            continue
        seen.add(p.url)
        parts.append(f'<a href="{escape(p.url, quote=True)}">{escape(source_label(p.source))}</a>')
    return " · ".join(parts)


def format_job(job, postings, matched_names: list[str]) -> str:
    icon = "🔥" if job.priority == "alta" else "📰"
    head = f"{icon} <b>{escape(job.title)}</b>"
    if job.company:
        head += f" — {escape(job.company)}"
    if job.location:
        head += f" · {escape(job.location)}"
    if job.modality:
        head += f" ({_MODALITY.get(job.modality, escape(job.modality))})"
    elif job.location:
        # La oferta pasa los filtros de modalidad por no indicarla (ante la duda, se incluye): que se vea
        head += " (modalidad sin indicar)"
    lines = [head]
    if matched_names:
        lines.append("🔎 Búsqueda: " + escape(", ".join(matched_names)))
    links = _links(postings)
    if any(p.source == "remoteok" for p in postings):
        links += " · vía RemoteOK"
    if links:
        lines.append("🔗 " + links)
    return "\n".join(lines)


def _compact(job, postings) -> str:
    """Versión mínima (título recortado y un enlace) por si un bloque no cabe en un mensaje."""
    icon = "🔥" if job.priority == "alta" else "📰"
    text = f"{icon} <b>{escape(job.title[:120])}</b>"
    if postings:
        text += f' · <a href="{escape(postings[0].url[:500], quote=True)}">{escape(source_label(postings[0].source))}</a>'
    return text


def _chunk(blocks: list[str], header: str, limit: int = MAX_LEN) -> list[str]:
    messages: list[str] = []
    current = header
    for block in blocks:
        sep = "\n\n" if current else ""
        if len(current) + len(sep) + len(block) > limit:
            if current:
                messages.append(current)
            current = block
        else:
            current += sep + block
    if current:
        messages.append(current)
    return messages


def format_digest(items, title: str = "📰 Resumen de ofertas") -> list[str]:
    """items: lista de (job, postings, matched_names). Devuelve mensajes de ≤ 4096 caracteres."""
    if not items:
        return []
    blocks = []
    for job, postings, names in items:
        block = format_job(job, postings, names)
        blocks.append(block if len(block) <= MAX_LEN - 200 else _compact(job, postings))
    return _chunk(blocks, f"<b>{escape(title)}</b> ({len(items)})")


_DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


def format_week(items, title: str = "Ofertas de la última semana") -> list[str]:
    """Ofertas agrupadas por día (del más reciente al más antiguo; dentro de cada día, primero las 🔥)
    y en formato corto (dos líneas por oferta, sin nombres de búsqueda): una semana cabe en pocos mensajes.
    items: lista de (job, postings)."""
    if not items:
        return []

    def order(item):
        seen = item[0].first_seen
        day = seen.astimezone().date().toordinal() if seen else 0
        return (-day, item[0].priority != "alta", -(seen.timestamp() if seen else 0))

    items = sorted(items, key=order)
    hot = sum(1 for job, _ in items if job.priority == "alta")
    header = (f"<b>📅 {escape(title)}</b> ({len(items)})\n"
              f"🔥 {hot} al momento · 📰 {len(items) - hot} del resumen")
    blocks: list[str] = []
    day = None
    for job, postings in items:
        local = job.first_seen.astimezone() if job.first_seen else None
        label = f"{_DIAS[local.weekday()]} {local:%d/%m}" if local else "Sin fecha"
        if label != day:
            day = label
            blocks.append(f"<b>— {label} —</b>")
        icon = "🔥" if job.priority == "alta" else "📰"
        line = f"{icon} <b>{escape(job.title[:150])}</b>"
        where = " · ".join(escape(x) for x in (job.company, job.location) if x)
        if where:
            line += f" — {where}"
        if job.modality:
            line += f" ({_MODALITY.get(job.modality, escape(job.modality))})"
        links = _links(postings)
        if links:
            line += "\n   🔗 " + links
        blocks.append(line if len(line) <= MAX_LEN - 200 else _compact(job, postings))
    return _chunk(blocks, header)


def format_new_portal(source: str) -> str:
    return f"➕ También en {escape(source_label(source))}"


def format_health(alerts: list[str]) -> str:
    return "⚠️ <b>Estado de las fuentes</b>\n" + "\n".join(f"• {escape(a)}" for a in alerts)


def _local(dt: datetime | None) -> str:
    return dt.astimezone().strftime("%d/%m %H:%M") if dt else "nunca"


def format_status(rows: list[dict], next_scan: datetime | None = None,
                  silenced_until: datetime | None = None) -> str:
    """rows: dicts con source, ts (datetime|None), ok, count, filled_pct."""
    lines = [f"{'Fuente':<15}{'Última':<12}{'Estado':<7}{'Ofertas':>7}{'Datos':>6}"]
    for r in rows:
        if r.get("note"):
            lines.append(f"{r['source'][:14]:<15}{r['note']}")
            continue
        if r.get("ts") is None:
            lines.append(f"{r['source'][:14]:<15}{'nunca':<12}{'-':<7}{'-':>7}{'-':>6}")
            continue
        pct = f"{r['filled_pct']:.0f}%" if r.get("filled_pct") is not None else "-"
        lines.append(f"{r['source'][:14]:<15}{_local(r['ts']):<12}{'OK' if r['ok'] else 'FALLO':<7}"
                     f"{r['count']:>7}{pct:>6}")
    text = "<pre>" + escape("\n".join(lines)) + "</pre>"
    for r in rows:
        if r.get("paused_until"):
            text += (f"\n⏸ {escape(r['source'])}: nos ha bloqueado; descansa hasta "
                     f"{_local(r['paused_until'])} para no saturarla")
    text += f"\n⏱ Próximo escaneo: {_local(next_scan)}" if next_scan else ""
    if silenced_until:
        text += f"\n🔕 Silenciado hasta {_local(silenced_until)}"
    return text


def format_summary(report) -> str:
    """Resumen de un escaneo (ScanReport)."""
    alta = sum(1 for j in report.new_matched if j.priority == "alta")
    lines = [f"✅ Escaneo terminado: {len(report.new_jobs)} ofertas nuevas, "
             f"{len(report.new_matched)} encajan ({alta} 🔥, {len(report.new_matched) - alta} 📰), "
             f"{report.new_discarded} descartadas."]
    failed = [f"{n}: {r.error}" for n, r in report.source_status.items() if r.error]
    if failed:
        lines.append("⚠️ Fuentes con error: " + "; ".join(failed))
    return escape("\n".join(lines))


def job_keyboard(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📝 Aplicar", callback_data=f"a:{job_id}"),
        InlineKeyboardButton("💾 Guardar", callback_data=f"t:guardada:{job_id}"),
    ], [
        InlineKeyboardButton("🚫 Ocultar empresa", callback_data=f"h:{job_id}"),
        InlineKeyboardButton("👎 No me interesa", callback_data=f"n:{job_id}"),
    ]])
