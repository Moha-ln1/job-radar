"""Normalización de textos para comparar y deduplicar ofertas."""
from __future__ import annotations

import re
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
