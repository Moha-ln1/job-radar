"""Modalidad (remoto / híbrido / presencial) leída de la descripción cuando la fuente no la da.

Solo frases claras: "teletrabajo" o "remote" sueltos aparecen en cualquier descripción ("posibilidad de
teletrabajo ocasional", "remote teams") y darían falsos remotos."""
from __future__ import annotations

import re

from .normalize import fold

_PATTERNS = [
    ("hibrido", re.compile(r"\b(?:hibrid[oa]s?|hybrid|semi-?presencial|modelo mixto|"
                           r"\d dias? (?:a la semana |por semana )?(?:de )?(?:presencial\w*|en (?:la )?oficina))")),
    ("remoto", re.compile(r"\b(?:100 ?% ?(?:remot\w*|teletrabaj\w*|a distancia)|(?:totalmente|fully|full)[ -]remot\w*|"
                          r"remote[- ]first|trabajo (?:totalmente )?remoto|(?:remote|remoto) (?:position|role|job|puesto))\b")),
    ("presencial", re.compile(r"\b(?:100 ?% ?presencial|(?:puesto|trabajo|modalidad|jornada) presencial|"
                              r"presencial en|on-?site|in[- ]office|en nuestras oficinas de)\b")),
]
_NEGATION = re.compile(r"\b(?:no|sin|not|non)\W+(?:\w+\W+){0,3}$")


def modality_from_text(text: str | None) -> str | None:
    """'remoto', 'hibrido' o 'presencial' si la descripción lo dice claramente; si no, None."""
    if not text:
        return None
    t = fold(text)
    for key, pattern in _PATTERNS:
        for m in pattern.finditer(t):
            if not _NEGATION.search(t[max(0, m.start() - 24):m.start()]):
                return key
    return None
