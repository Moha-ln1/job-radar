"""Seguimiento de candidaturas: estados, datos para preparar solicitudes, estadísticas y exportación."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from html import escape

import yaml

from . import notify
from .paths import Paths

TRACKS = {"guardada": "💾 Guardada", "aplicada": "📨 Aplicada", "entrevista": "🗣 Entrevista",
          "oferta": "🎉 Oferta", "rechazada": "❌ Rechazada"}
REMINDER_DAYS = 7

# Datos de la persona para preparar solicitudes; se editan desde /candidatura
CAND_FIELDS = {"nombre": "Nombre", "presentacion": "Presentación (1-2 frases)",
               "disponibilidad": "Disponibilidad", "salario": "Expectativa salarial",
               "idiomas": "Idiomas", "otros": "Permiso de trabajo u otros datos"}


def load_candidatura(paths: Paths) -> dict[str, str]:
    try:
        data = yaml.safe_load(paths.candidatura.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {k: str(v).strip() for k, v in data.items() if k in CAND_FIELDS and str(v).strip()} \
        if isinstance(data, dict) else {}


def save_candidatura(paths: Paths, data: dict[str, str]) -> None:
    paths.candidatura.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                                 encoding="utf-8")


def cover_letter(job, data: dict[str, str]) -> str:
    """Carta corta con lo que haya en el perfil; lo que falta se omite, no se inventa."""
    name = data.get("nombre", "")
    greeting = f"Hola, equipo de {job.company}:" if job.company else "Hola:"
    body = [f"Me llamo {name} y me interesa el puesto de {job.title}." if name
            else f"Me interesa el puesto de {job.title}."]
    if data.get("presentacion"):
        body.append(data["presentacion"])
    if data.get("disponibilidad"):
        body.append(f"Disponibilidad: {data['disponibilidad']}.")
    body.append("Adjunto mi currículum y quedo a su disposición para ampliar cualquier detalle.")
    closing = "Un saludo" + (f",\n{name}" if name else "")
    return f"{greeting}\n\n" + "\n\n".join(body) + f"\n\n{closing}"


def quick_answers(data: dict[str, str]) -> str:
    rows = [f"{CAND_FIELDS[k]}: {data[k]}" for k in ("disponibilidad", "salario", "idiomas", "otros")
            if data.get(k)]
    return "\n".join(rows)


def apply_kit(job, postings, data: dict[str, str]) -> str:
    links = notify._links(postings)
    parts = [f"📝 <b>{escape(job.title)}</b>" + (f" — {escape(job.company)}" if job.company else ""),
             "🔗 " + links if links else "", "<b>Carta</b>", f"<pre>{escape(cover_letter(job, data))}</pre>"]
    answers = quick_answers(data)
    if answers:
        parts += ["<b>Respuestas habituales</b>", f"<pre>{escape(answers)}</pre>"]
    if not data:
        parts.append("💡 Rellena tus datos con /candidatura y la carta saldrá completa.")
    return "\n".join(p for p in parts if p)


def _days(now: datetime, since: datetime | None) -> str:
    if since is None:
        return ""
    n = (now - since).days
    return "hoy" if n <= 0 else f"hace {n} d"


def format_tracked(jobs, now: datetime, limit: int = 3800) -> list[str]:
    """Mensajes de /aplicadas, agrupados por estado y partidos para no pasar el límite de Telegram."""
    if not jobs:
        return ["Aún no sigues ninguna oferta. Pulsa 💾 Guardar o 📝 Aplicar en un aviso."]
    lines: list[str] = []
    for track, label in TRACKS.items():
        group = [j for j in jobs if j.track == track]
        if group:
            lines += ["", f"<b>{label} ({len(group)})</b>"]
            lines += [f"• {escape(j.title)}" + (f" — {escape(j.company)}" if j.company else "")
                      + f" · {_days(now, j.track_at)}  /oferta_{j.id}" for j in group]
    messages, current = [], ""
    for line in lines:
        if len(current) + len(line) + 1 > limit and current.strip():
            messages.append(current.strip())
            current = ""
        current += line + "\n"
    messages.append(current.strip())
    return messages


def format_favorites(jobs, now: datetime, limit: int = 3800) -> list[str]:
    """Mensajes de /favoritas: una línea por oferta, con su estado de seguimiento si lo tiene."""
    if not jobs:
        return ["Aún no tienes favoritas. Pulsa ⭐ en un aviso o en la ficha de una oferta."]
    lines = [f"<b>⭐ Favoritas</b> ({len(jobs)})"]
    for j in jobs:
        state = f" · {TRACKS[j.track]}" if j.track in TRACKS else ""
        lines.append(f"• {escape(j.title)}" + (f" — {escape(j.company)}" if j.company else "")
                     + f"{state}  /oferta_{j.id}")
    messages, current = [], ""
    for line in lines:
        if len(current) + len(line) + 1 > limit and current:
            messages.append(current.strip())
            current = ""
        current += line + "\n"
    messages.append(current.strip())
    return messages


def format_stats(stats: dict, days: int = 30) -> str:
    tr = stats["seguimiento"]
    lines = [f"📊 <b>Últimos {days} días</b>",
             f"Ofertas vistas: {stats['vistas']} · que encajan: {stats['encajan']}"]
    if stats["fuentes"]:
        lines.append("Por fuente: " + ", ".join(f"{escape(notify.source_label(s))} {n}"
                                                 for s, n in stats["fuentes"][:8]))
    if tr:
        lines.append("Seguimiento (total): " + " · ".join(f"{TRACKS[t]} {n}" for t, n in tr.items() if t in TRACKS))
        sent = sum(tr.get(t, 0) for t in ("aplicada", "entrevista", "oferta", "rechazada"))
        replies = sum(tr.get(t, 0) for t in ("entrevista", "oferta"))
        if sent:
            lines.append(f"Respuesta positiva: {replies} de {sent} candidaturas ({round(100 * replies / sent)} %)")
    return "\n".join(lines)


def reminder_text(job, now: datetime) -> str:
    return (f"⏰ Llevas {_days(now, job.track_at).removeprefix('hace ')} sin novedades de "
            f"<b>{escape(job.title)}</b>" + (f" ({escape(job.company)})" if job.company else "")
            + ". ¿Qué ha pasado?")


def _safe(value: str) -> str:
    """Evita que una hoja de cálculo ejecute como fórmula un texto que empieza por = + - @."""
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


def to_csv(jobs, store) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["estado", "fecha", "puesto", "empresa", "ubicación", "enlace"])
    for j in jobs:
        posts = store.postings(j.id)
        w.writerow([j.track or "", (j.track_at or j.first_seen).date().isoformat(), _safe(j.title),
                    _safe(j.company or ""), _safe(j.location or ""), posts[0].url if posts else ""])
    return out.getvalue()
