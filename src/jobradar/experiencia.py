"""Años de experiencia que pide una oferta, leídos de su descripción ("+2 años de experiencia",
"at least 3 years of experience", "Experiencia mínima: Al menos 3 años")."""
from __future__ import annotations

import re

from .normalize import fold

_WORDS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_NUM = r"(?<![\w.,])(?P<num>\d{1,2}|" + "|".join(_WORDS) + r")\b"
_MORE = r"(?P<more>mas de|more than|over|superior a|superior de)\s+"
_PRE = (rf"(?:{_MORE}|(?:al menos|minimo de|minimo|un minimo de|at least|minimum of|minimum|entre|between)\s+"
        r"|\+\s*)?")
# Rango "2-4", "2 a 4", "2 y 4", "2 to 4", "2 and 4": cuenta el mínimo
_RANGE = r"(?:\s*(?:-|–|a|to|o|y|and)\s*\d{1,2})?"
_PLUS = r"(?:\s*\+|\s+o mas|\s+or more)?"
_YEARS_ES = r"\s*anos?"
_YEARS_EN = r"\s*(?:years?|yrs?)['’]?"

# (patrón, exige que la línea hable de experiencia)
_PATTERNS = [
    # "3 años de experiencia", "más de 2 años de experiencia demostrable", "2-4 años de experiencia"
    (re.compile(rf"{_PRE}{_NUM}{_RANGE}{_PLUS}{_YEARS_ES}\s+(?:de\s+|con\s+)?(?:\w+\s+){{0,2}}?experiencia"), False),
    # "experiencia mínima de 3 años", "experiencia: al menos 2 años", "experiencia de más de 2 años"
    (re.compile(rf"experiencia(?:\s+(?:minima|previa|demostrable|laboral|profesional|requerida))?"
                rf"\s*(?::|de|minima de)?\s*{_PRE}{_NUM}{_RANGE}{_PLUS}{_YEARS_ES}"), False),
    # "3+ years of experience", "at least 2 years of professional experience", "2 years' experience"
    (re.compile(rf"{_PRE}{_NUM}{_RANGE}{_PLUS}{_YEARS_EN}\s+(?:of\s+)?(?:[\w-]+\s+){{0,3}}?experience"), False),
    # "experience: 3+ years", "experience of at least 2 years"
    (re.compile(rf"experience\s*(?::|of)?\s*{_PRE}{_NUM}{_RANGE}{_PLUS}{_YEARS_EN}"), False),
    # "5+ years in the same process family", "3+ años en desarrollo": con el "+" es casi siempre un requisito
    (re.compile(r"(?<![\w.,])(?P<num>\d{1,2})\s*\+\s*(?:years?|yrs?|anos?)\b"), False),
    # "Experiencia en Python (mínimo 2 años)", "Python experience (at least 3 years)"
    (re.compile(rf"(?:minimo|al menos|at least|minimum)\s+(?:de\s+)?{_NUM}{_RANGE}{_PLUS}"
                rf"(?:{_YEARS_ES}|{_YEARS_EN})\b"), True),
]

# Antes del número: la experiencia es de la empresa, o solo se valora
_NOT_CANDIDATE = re.compile(
    r"\b(empresa|compania|company|firm|consultora|grupo|contamos|llevamos|tenemos|cuenta con|"
    r"we have|with over|valorable|se valora|deseable|nice to have|a plus|preferred|preferiblemente|"
    r"idealmente|ideally|bonus|plus si)\b[^.;:\n]{0,25}$")
# Justo después del número: "(valorable)", "es un plus"
_NOT_CANDIDATE_AFTER = re.compile(r"^[^.;\n]{0,20}\b(valorable|deseable|is a plus|a plus|"
                                  r"nice to have|preferred|preferible)\b")
_MAX_CANDIDATE = 15  # "más de 25 años de experiencia" es la empresa, no el puesto


def _value(token: str) -> int:
    return int(token) if token.isdigit() else _WORDS[token]


def required_years(description: str | None) -> int | None:
    """Años mínimos que exige la oferta (el menor de los que pide), o None si no dice nada claro.

    "Más de 2 años" cuenta como 3. Ante la duda se devuelve None: lo que se valora o la experiencia
    de la empresa no cuenta, y con varios requisitos se toma el más bajo. Cada línea (viñeta) se
    lee por separado: "(valorable)" de una no anula el requisito de la anterior."""
    if not description:
        return None
    found: list[int] = []
    for raw_line in description.split("\n"):
        line = fold(raw_line)
        for pattern, needs_experience in _PATTERNS:
            if needs_experience and "experienc" not in line:
                continue
            for m in pattern.finditer(line):
                before = line[max(0, m.start() - 60):m.start()]
                if _NOT_CANDIDATE.search(before) or _NOT_CANDIDATE_AFTER.search(line[m.end():]):
                    continue
                more = m.groupdict().get("more")
                years = _value(m.group("num")) + (1 if more else 0)
                if 0 < years <= _MAX_CANDIDATE:
                    found.append(years)
    return min(found) if found else None
