"""Descripción de una oferta, leída de su ficha, para las fuentes que en el listado solo dan el título.

Se pide solo para ofertas que ya encajan por el título (y solo si hay algo que comprobar en la descripción),
con un tope por escaneo. Si una web nos bloquea, se deja de pedir a ese dominio."""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlsplit

from ..http import Http

_log = logging.getLogger("jobradar.detalle")

# Fichas que se piden por escaneo, por dominio (LinkedIn bloquea con facilidad: muy pocas)
LIMITS = {"www.linkedin.com": 5}
DEFAULT_LIMIT = 25
_LD_JSON = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)


def supports(source: str) -> bool:
    return source.startswith(("workday:", "smartrecruiters:")) or source in _PORTALS


_PORTALS = {"tecnoempleo", "infoempleo", "primerempleo", "linkedin"}


def limit_for(url: str) -> int:
    return LIMITS.get(urlsplit(url).hostname or "", DEFAULT_LIMIT)


def _job_postings(html: str) -> list[dict]:
    out: list[dict] = []
    for raw in _LD_JSON.findall(html):
        try:
            data = json.loads(raw, strict=False)  # algunas webs dejan saltos de línea sin escapar
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph") or [data]
        out += [i for i in items if isinstance(i, dict) and i.get("@type") == "JobPosting"]
    return out


def description_from_html(html: str) -> str | None:
    """Texto de la oferta en el JSON-LD `JobPosting` de la página, con la experiencia y los requisitos."""
    for posting in _job_postings(html):
        parts = [str(posting.get("description") or "")]
        for key in ("qualifications", "skills", "responsibilities"):
            if posting.get(key):
                parts.append(str(posting[key]))
        exp = posting.get("experienceRequirements")
        if isinstance(exp, dict) and exp.get("monthsOfExperience"):
            parts.append(f"{int(float(exp['monthsOfExperience']) // 12)} years of experience")
        elif exp:
            parts.append(f"experiencia: {exp}")
        text = "\n".join(p for p in parts if p.strip())
        if text.strip():
            return text
    return None


def _workday_api(url: str) -> str:
    parts = urlsplit(url)
    site, _, rest = parts.path.lstrip("/").partition("/")
    tenant = (parts.hostname or "").split(".")[0]
    return f"https://{parts.hostname}/wday/cxs/{tenant}/{site}/{rest}"


async def fetch_description(http: Http, source: str, url: str) -> str | None:
    """Descripción de la ficha de una oferta, o None si no se encuentra. Los errores de red se propagan."""
    if source.startswith("workday:"):
        data = (await http.get(_workday_api(url))).json()
        return (data.get("jobPostingInfo") or {}).get("jobDescription")
    if source.startswith("smartrecruiters:"):
        slug, _, ad = urlsplit(url).path.strip("/").partition("/")
        data = (await http.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{ad}")).json()
        sections = (data.get("jobAd") or {}).get("sections") or {}
        # Sin "companyDescription": habla de la empresa ("más de 100 años de experiencia"), no del puesto
        return "\n".join((sections.get(k) or {}).get("text") or ""
                         for k in ("jobDescription", "qualifications", "additionalInformation")) or None
    if source in _PORTALS:
        return description_from_html((await http.get(url)).text)
    return None
