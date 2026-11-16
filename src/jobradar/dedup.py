"""Claves y similitud para detectar la misma oferta en varias fuentes."""
from __future__ import annotations

from difflib import SequenceMatcher

from .normalize import norm_company, norm_title

SIMILARITY = 0.90


def job_key(title: str, company: str | None) -> str:
    return f"{norm_company(company)}|{norm_title(title)}"


def similar(a_title: str, b_title: str) -> float:
    """Ratio difflib sobre los tokens ordenados de los títulos normalizados."""
    a = " ".join(sorted(norm_title(a_title).split()))
    b = " ".join(sorted(norm_title(b_title).split()))
    return SequenceMatcher(None, a, b).ratio()
