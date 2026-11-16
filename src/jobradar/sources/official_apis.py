"""Fuentes con API oficial y clave gratuita: Adzuna y Jooble. Sin clave en .env se desactivan en silencio."""
from __future__ import annotations
from jobradar.normalize import parse_iso

import html
import logging
import re
from datetime import datetime

from jobradar.models import JobOffer, build_offer
from jobradar.sources import SourceContext

_log = logging.getLogger("jobradar.sources")
_TAGS = re.compile(r"<[^>]*>")
_MAX_TERMS, _MAX_LOCATIONS = 4, 2


def _clean(text: str | None) -> str | None:
    if not isinstance(text, str):
        return None
    return " ".join(_TAGS.sub("", html.unescape(text)).split()) or None


def _date(value: str | None) -> datetime | None:
    return parse_iso(value)


def _queries(ctx: SourceContext) -> list[tuple[str, str]]:
    terms = ctx.terms[:_MAX_TERMS] or ["prácticas"]
    places = ctx.locations[:_MAX_LOCATIONS] or ["España"]
    return [(t, p) for t in terms for p in places]


def _dedup(offers: list[JobOffer | None]) -> list[JobOffer]:
    seen: dict[str, JobOffer] = {}
    for o in offers:
        if o is not None:
            seen.setdefault(o.url, o)
    return list(seen.values())


# ------------------------------------------------------------------------------------------ Adzuna
def _parse_adzuna(data: dict) -> list[JobOffer]:
    offers = []
    for o in data.get("results") or []:
        loc = o.get("location") or {}
        area = loc.get("area") or []
        offers.append(build_offer(
            title=_clean(o.get("title")) or "",
            company=_clean((o.get("company") or {}).get("display_name")),
            location=_clean(loc.get("display_name") or (area[-1] if area else None)),
            url=o.get("redirect_url") or "",
            source="adzuna",
            posted_at=_date(o.get("created")),
            category=_clean((o.get("category") or {}).get("label")),
            description=_clean(o.get("description")),
        ))
    return _dedup(offers)


async def fetch_adzuna(ctx: SourceContext) -> list[JobOffer]:
    app_id, app_key = ctx.env.get("ADZUNA_APP_ID"), ctx.env.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        _log.info("adzuna: sin clave: fuente desactivada")
        return []
    offers: list[JobOffer] = []
    for term, place in _queries(ctx):
        resp = await ctx.http.get(
            "https://api.adzuna.com/v1/api/jobs/es/search/1",
            params={"app_id": app_id, "app_key": app_key, "what": term, "where": place,
                    "results_per_page": 50, "max_days_old": 14})
        offers.extend(_parse_adzuna(resp.json()))
    return _dedup(offers)


# ------------------------------------------------------------------------------------------ Jooble
def _parse_jooble(data: dict) -> list[JobOffer]:
    return _dedup([build_offer(
        title=_clean(o.get("title")) or "",
        company=_clean(o.get("company")),
        location=_clean(o.get("location")),
        url=o.get("link") or "",
        source="jooble",
        posted_at=_date(o.get("updated")),
        description=_clean(o.get("snippet")),
    ) for o in data.get("jobs") or []])


async def fetch_jooble(ctx: SourceContext) -> list[JobOffer]:
    key = ctx.env.get("JOOBLE_API_KEY")
    if not key:
        _log.info("jooble: sin clave: fuente desactivada")
        return []
    offers: list[JobOffer] = []
    for term, place in _queries(ctx):
        resp = await ctx.http.post_json(
            f"https://es.jooble.org/api/{key}", {"keywords": term, "location": place, "page": 1})
        offers.extend(_parse_jooble(resp.json()))
    return _dedup(offers)


FETCHERS = {"adzuna": fetch_adzuna, "jooble": fetch_jooble}
