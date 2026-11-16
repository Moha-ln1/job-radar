"""Webs de empleo de empresas por API de ATS: Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Recruitee,
Personio (XML) y Teamtailor (RSS). Las empresas salen de ``companies:`` en config.yaml."""
from __future__ import annotations
from jobradar.normalize import parse_iso

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from jobradar.http import SourceBlocked
from jobradar.models import JobOffer, Modality, build_offer
from jobradar.sources import SourceContext

_log = logging.getLogger("jobradar.sources.ats")

_MODALITY: dict[str, Modality] = {
    "remote": "remoto", "hybrid": "hibrido", "onsite": "presencial", "on-site": "presencial",
    "on_site": "presencial",
}


def _modality(value) -> Modality | None:
    return _MODALITY.get(str(value).strip().lower()) if value else None


def _iso(value) -> datetime | None:
    return parse_iso(value)


def _epoch_ms(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _first(items, key: str) -> str | None:
    for it in items or []:
        if isinstance(it, dict) and it.get(key):
            return it[key]
    return None


def _keep(offers: list[JobOffer | None]) -> list[JobOffer]:
    return [o for o in offers if o is not None]


# --- Greenhouse -------------------------------------------------------------------------------------------

def _parse_greenhouse(data: dict, company: str, slug: str) -> list[JobOffer]:
    return _keep([build_offer(
        title=j.get("title"), url=j.get("absolute_url"), source=f"greenhouse:{slug}", company=company,
        location=(j.get("location") or {}).get("name"),
        posted_at=_iso(j.get("first_published")) or _iso(j.get("updated_at")),
        category=_first(j.get("departments"), "name"),
        # Sin comprobar dominio: la API devuelve la web de empleo de la empresa si la tiene
        # (p. ej. careers.datadoghq.com), y el enlace viene de la API oficial, no de leer HTML.
        expected_domains=None,
    ) for j in data.get("jobs", [])])


async def _fetch_greenhouse(ctx: SourceContext, company: str, slug: str) -> list[JobOffer]:
    resp = await ctx.http.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    return _parse_greenhouse(resp.json(), company, slug)


# --- Lever ------------------------------------------------------------------------------------------------

def _parse_lever(data: list, company: str, slug: str) -> list[JobOffer]:
    offers = []
    for j in data:
        cats = j.get("categories") or {}
        offers.append(build_offer(
            title=j.get("text"), url=j.get("hostedUrl"), source=f"lever:{slug}", company=company,
            location=cats.get("location"), modality=_modality(j.get("workplaceType")),
            posted_at=_epoch_ms(j.get("createdAt")), category=cats.get("team"),
            expected_domains={"lever.co"}))
    return _keep(offers)


async def _fetch_lever(ctx: SourceContext, company: str, slug: str) -> list[JobOffer]:
    # Lever devuelve todas las descripciones (cientos de KB): necesita más margen que el general
    resp = await ctx.http.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=60)
    return _parse_lever(resp.json(), company, slug)


# --- Ashby ------------------------------------------------------------------------------------------------

def _parse_ashby(data: dict, company: str, slug: str) -> list[JobOffer]:
    offers = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        modality = _modality(j.get("workplaceType")) or ("remoto" if j.get("isRemote") else None)
        offers.append(build_offer(
            title=j.get("title"), url=j.get("jobUrl"), source=f"ashby:{slug}", company=company,
            location=j.get("location"), modality=modality, posted_at=_iso(j.get("publishedAt")),
            category=j.get("department"), expected_domains={"ashbyhq.com"}))
    return _keep(offers)


async def _fetch_ashby(ctx: SourceContext, company: str, slug: str) -> list[JobOffer]:
    resp = await ctx.http.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    return _parse_ashby(resp.json(), company, slug)


# --- SmartRecruiters --------------------------------------------------------------------------------------

def _parse_smartrecruiters(data: dict, company: str, slug: str) -> list[JobOffer]:
    offers = []
    for j in data.get("content", []):
        loc = j.get("location") or {}
        modality = "remoto" if loc.get("remote") else "hibrido" if loc.get("hybrid") else None
        offers.append(build_offer(
            title=j.get("name"), url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
            source=f"smartrecruiters:{slug}", company=company,
            location=loc.get("fullLocation") or loc.get("city"), modality=modality,
            posted_at=_iso(j.get("releasedDate")), category=(j.get("department") or {}).get("label"),
            expected_domains={"smartrecruiters.com"}))
    return _keep(offers)


async def _fetch_smartrecruiters(ctx: SourceContext, company: str, slug: str) -> list[JobOffer]:
    offers: list[JobOffer] = []
    offset = 0
    for _ in range(3):
        resp = await ctx.http.get(
            f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?country=es&limit=100&offset={offset}")
        data = resp.json()
        offers += _parse_smartrecruiters(data, company, slug)
        offset += 100
        if offset >= int(data.get("totalFound") or 0):
            break
    return offers


# --- Workday ----------------------------------------------------------------------------------------------

def _workday_posted(text: str | None, now: datetime) -> datetime | None:
    """'Posted 3 Days Ago' (o 'Publicado hace 3 días') -> fecha aproximada (00:00 UTC). '30+' no es fecha: None."""
    if not text:
        return None
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    low = text.lower()
    if "más de" in low or "more than" in low:
        return None
    if "today" in low or "hoy" in low:
        return day
    if "yesterday" in low or "ayer" in low:
        return day - timedelta(days=1)
    m = re.search(r"(\d+)(\+?)\s+(?:days?\s+ago|d[ií]as?)", low)
    if m and not m.group(2):
        return day - timedelta(days=int(m.group(1)))
    return None


def _parse_workday(data: dict, company: str, host: str, tenant: str, site: str,
                   now: datetime | None = None) -> list[JobOffer]:
    now = now or datetime.now(timezone.utc)
    offers = []
    for j in data.get("jobPostings", []):
        if not j.get("externalPath"):
            continue
        location = j.get("locationsText") or ", ".join((j.get("bulletFields") or [])[1:]) or None
        offers.append(build_offer(
            title=j.get("title"), url=f"https://{host}/{site}{j.get('externalPath')}",
            source=f"workday:{tenant}", company=company, location=location,
            posted_at=_workday_posted(j.get("postedOn"), now), expected_domains={"myworkdayjobs.com"}))
    return _keep(offers)


async def _fetch_workday(ctx: SourceContext, company: str, slug: str) -> list[JobOffer]:
    try:
        tenant_wd, site = slug.split("/", 1)
        tenant, wd = tenant_wd.split(".", 1)
    except ValueError:
        raise ValueError(f"slug de Workday inválido '{slug}' (formato esperado: tenant.wdN/sitio)") from None
    host = f"{tenant}.{wd}.myworkdayjobs.com"
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    offers: dict[str, JobOffer] = {}
    for term in ctx.terms[:4] or [""]:
        body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": f"{term} Spain".strip()}
        resp = await ctx.http.post_json(url, body, headers={"Accept-Language": "en-US,en;q=0.9"})
        for offer in _parse_workday(resp.json(), company, host, tenant, site):
            offers.setdefault(offer.url, offer)
    return list(offers.values())


# --- Recruitee --------------------------------------------------------------------------------------------

def _parse_recruitee(data: dict, company: str, slug: str) -> list[JobOffer]:
    offers = []
    for j in data.get("offers", []):
        url = j.get("careers_url") or f"https://{slug}.recruitee.com/o/{j.get('slug')}"
        modality = "remoto" if j.get("remote") else "hibrido" if j.get("hybrid") else \
            "presencial" if j.get("on_site") else None
        # Muchas empresas publican en su propio dominio (careers.bunq.com): se acepta el del enlace oficial.
        domains = {"recruitee.com", (urlsplit(url).hostname or "").lower()}
        offers.append(build_offer(
            title=j.get("title"), url=url, source=f"recruitee:{slug}", company=company,
            location=j.get("location") or j.get("city"), modality=modality,
            posted_at=_iso(j.get("published_at")), category=j.get("department"), expected_domains=domains))
    return _keep(offers)


async def _fetch_recruitee(ctx: SourceContext, company: str, slug: str) -> list[JobOffer]:
    resp = await ctx.http.get(f"https://{slug}.recruitee.com/api/offers/")
    return _parse_recruitee(resp.json(), company, slug)


# --- Personio (XML) ---------------------------------------------------------------------------------------

def _parse_personio(xml: bytes | str, company: str, slug: str) -> list[JobOffer]:
    root = ET.fromstring(xml)
    offers = []
    for pos in root.iter("position"):
        def text(tag: str) -> str | None:
            el = pos.find(tag)
            return el.text.strip() if el is not None and el.text else None
        offers.append(build_offer(
            title=text("name"), url=f"https://{slug}.jobs.personio.de/job/{text('id')}",
            source=f"personio:{slug}", company=company, location=text("office"),
            posted_at=_iso(text("createdAt")), category=text("department"),
            expected_domains={"personio.de", "personio.com"}))
    return _keep(offers)


async def _fetch_personio(ctx: SourceContext, company: str, slug: str) -> list[JobOffer]:
    resp = await ctx.http.get(f"https://{slug}.jobs.personio.de/xml")
    return _parse_personio(resp.content, company, slug)


# --- Teamtailor (RSS) -------------------------------------------------------------------------------------

_TT = "{https://teamtailor.com/locations}"


def _parse_teamtailor(xml: bytes | str, company: str, slug: str) -> list[JobOffer]:
    root = ET.fromstring(xml)
    offers = []
    for item in root.iter("item"):
        def text(tag: str) -> str | None:
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else None
        places = []
        for loc in item.iter(_TT + "location"):
            city = (loc.findtext(_TT + "city") or loc.findtext(_TT + "name") or "").strip()
            country = (loc.findtext(_TT + "country") or "").strip()
            places.append(", ".join(p for p in (city, country) if p))
        pub = text("pubDate")
        try:
            posted = parsedate_to_datetime(pub) if pub else None
        except (TypeError, ValueError):
            posted = None
        offers.append(build_offer(
            title=text("title"), url=text("link"), source=f"teamtailor:{slug}", company=company,
            location=" / ".join(p for p in places if p) or None, modality=_modality(text("remoteStatus")),
            posted_at=posted, category=text(_TT + "department"), expected_domains={"teamtailor.com"}))
    return _keep(offers)


async def _fetch_teamtailor(ctx: SourceContext, company: str, slug: str) -> list[JobOffer]:
    resp = await ctx.http.get(f"https://{slug}.teamtailor.com/jobs.rss")
    return _parse_teamtailor(resp.content, company, slug)


# --- Despacho ---------------------------------------------------------------------------------------------

_BY_ATS = {
    "greenhouse": _fetch_greenhouse, "lever": _fetch_lever, "ashby": _fetch_ashby,
    "smartrecruiters": _fetch_smartrecruiters, "workday": _fetch_workday,
    "recruitee": _fetch_recruitee, "personio": _fetch_personio, "teamtailor": _fetch_teamtailor,
}


async def fetch_ats(ctx: SourceContext) -> list[JobOffer]:
    offers: list[JobOffer] = []
    for entry in ctx.settings.companies:
        name, ats, slug = entry.get("name"), str(entry.get("ats", "")).lower(), entry.get("slug")
        fetch = _BY_ATS.get(ats)
        if fetch is None or not name or not slug:
            _log.warning("empresa ignorada (ATS desconocido o datos incompletos): %s", entry)
            continue
        try:
            found = await fetch(ctx, name, str(slug))
        except SourceBlocked:
            raise
        except Exception as exc:  # una empresa rota no debe tumbar a las demás
            # str() de un timeout de httpx está vacío: el tipo de error dice lo que ha pasado
            _log.warning("fallo al leer %s (%s:%s): %s", name, ats, slug, str(exc) or type(exc).__name__)
            continue
        offers += found
    return offers


FETCHERS = {"ats": fetch_ats}
