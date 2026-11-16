"""Normalización de textos para comparar y deduplicar ofertas."""
from __future__ import annotations

import re
from datetime import datetime, timezone
import unicodedata

_GENDER = re.compile(
    r"\(\s*[hmfdx]\s*/\s*[hmfdx](?:\s*/\s*[hmfdx])?\s*\)"  # (h/m) (m/f/d) (h/m/x)
    r"|(?<![a-z0-9])[hmf]\s*/\s*[mfdx](?:\s*/\s*[dx])?(?![a-z0-9])"  # m/f/d suelto
    r"|\[\s*urgente\s*\]|\(\s*urgente\s*\)"
    r"|\(\s*(?:remote|remoto|hibrido|hybrid|presencial|on-?site)\s*\)"
)
# Sufijo " - Madrid", " – Remoto"... solo si es una ubicación/modalidad conocida:
# quitar cualquier sufijo fusionaría "Trainee - Java" con "Trainee - QA".
_SUFFIX_WORDS = (
    "remoto|remote|hibrido|hybrid|presencial|espana|spain|madrid|barcelona|granada|sevilla|"
    "valencia|malaga|bilbao|zaragoza|murcia|alicante|cordoba|cadiz|almeria|huelva|jaen|"
    "europe|europa|worldwide|anywhere"
)
_SUFFIX = re.compile(rf"\s[-–—]\s*(?:(?:{_SUFFIX_WORDS})(?:\s*[,/]\s*|\s+)?)+$")
_LEGAL = {
    "sl", "sa", "slu", "inc", "ltd", "gmbh", "spain", "espana", "iberia", "group", "grupo",
}


def fold(text: str) -> str:
    """Minúsculas, sin tildes y con espacios colapsados."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


def norm_title(title: str) -> str:
    """Título comparable: sin género, sufijos de ubicación/modalidad ni signos."""
    t = fold(title)
    t = _GENDER.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = _SUFFIX.sub("", t)
    t = re.sub(r"[^\w]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def norm_company(company: str | None) -> str:
    """Empresa comparable: sin formas jurídicas, país ni puntuación."""
    if not company:
        return ""
    c = fold(company).replace(".", "")
    c = re.sub(r"[^\w]+", " ", c)
    return " ".join(w for w in c.split() if w not in _LEGAL)


_FRACTION = re.compile(r"\.(\d+)")
_COMPACT_TZ = re.compile(r"([+-]\d{2})(\d{2})$")


def parse_iso(value) -> datetime | None:
    """Fecha ISO 8601 de una fuente externa → datetime con zona UTC, o None si no se entiende.

    Acepta lo que Python 3.10 no entiende por sí solo: sufijo "Z", " UTC", fracciones de segundo de
    cualquier longitud ("…00.0000000" de Jooble) y zonas sin dos puntos ("+0000")."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace(" UTC", "+00:00")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    text = _FRACTION.sub(lambda m: "." + (m.group(1) + "000000")[:6], text, count=1)
    text = _COMPACT_TZ.sub(lambda m: m.group(1) + ":" + m.group(2), text)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
