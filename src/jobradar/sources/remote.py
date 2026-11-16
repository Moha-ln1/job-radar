"""Fuentes de empleo remoto con API/RSS sin clave: Remotive, RemoteOK, We Work Remotely, Himalayas, Arbeitnow."""
from __future__ import annotations
from jobradar.normalize import parse_iso

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from jobradar.models import JobOffer, build_offer
from jobradar.sources import SourceContext


def _iso(value) -> datetime | None:
    return parse_iso(value)


def _epoch(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _keep(offers: list[JobOffer | None]) -> list[JobOffer]:
    return [o for o in offers if o is not None]


# --- Remotive ---------------------------------------------------------------------------------------------

def _parse_remotive(data: dict) -> list[JobOffer]:
    return _keep([build_offer(
        title=j.get("title"), url=j.get("url"), source="remotive", company=j.get("company_name"),
        modality="remoto", remote_region=j.get("candidate_required_location"),
        posted_at=_iso(j.get("publication_date")), category=j.get("category"),
        expected_domains={"remotive.com"}) for j in data.get("jobs", [])])


async def fetch_remotive(ctx: SourceContext) -> list[JobOffer]:
    offers: dict[str, JobOffer] = {}
    for term in ctx.terms[:3] or [""]:
        resp = await ctx.http.get(f"https://remotive.com/api/remote-jobs?search={quote(term)}")
        for offer in _parse_remotive(resp.json()):
            offers.setdefault(offer.url, offer)
    return list(offers.values())


# --- RemoteOK ---------------------------------------------------------------------------------------------

def _parse_remoteok(data: list) -> list[JobOffer]:
    # El primer elemento es el aviso legal (sin "position").
    return _keep([build_offer(
        title=j.get("position"), url=j.get("url"), source="remoteok", company=j.get("company"),
        modality="remoto", remote_region=j.get("location"),
        posted_at=_iso(j.get("date")) or _epoch(j.get("epoch")),
        expected_domains={"remoteok.com"}) for j in data if isinstance(j, dict) and j.get("position")])


async def fetch_remoteok(ctx: SourceContext) -> list[JobOffer]:
    return _parse_remoteok((await ctx.http.get("https://remoteok.com/api")).json())


# --- We Work Remotely (RSS) -------------------------------------------------------------------------------

def _parse_weworkremotely(xml: bytes | str) -> list[JobOffer]:
    offers = []
    for item in ET.fromstring(xml).iter("item"):
        def text(tag: str) -> str | None:
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else None
        company, sep, title = (text("title") or "").partition(": ")
        if not sep:  # sin "Empresa: Puesto" no se puede separar con seguridad
            company, title = None, company
        pub = text("pubDate")
        try:
            posted = parsedate_to_datetime(pub) if pub else None
        except (TypeError, ValueError):
            posted = None
        offers.append(build_offer(
            title=title, url=text("link"), source="weworkremotely", company=company, modality="remoto",
            remote_region=text("region"), posted_at=posted, category=text("category"),
            expected_domains={"weworkremotely.com"}))
    return _keep(offers)


async def fetch_weworkremotely(ctx: SourceContext) -> list[JobOffer]:
    return _parse_weworkremotely((await ctx.http.get("https://weworkremotely.com/remote-jobs.rss")).content)


# --- Himalayas --------------------------------------------------------------------------------------------

def _parse_himalayas(data: dict) -> list[JobOffer]:
    offers = []
    for j in data.get("jobs", []):
        region = ", ".join(j.get("locationRestrictions") or []) or None
        parents = j.get("parentCategories") or []
        offers.append(build_offer(
            title=j.get("title"), url=j.get("applicationLink") or j.get("guid"), source="himalayas",
            company=j.get("companyName"), modality="remoto", remote_region=region,
            posted_at=_epoch(j.get("pubDate")), category=parents[0] if parents else None,
            expected_domains={"himalayas.app"}))
    return _keep(offers)


async def fetch_himalayas(ctx: SourceContext) -> list[JobOffer]:
    return _parse_himalayas((await ctx.http.get("https://himalayas.app/jobs/api?limit=100")).json())


# --- Arbeitnow --------------------------------------------------------------------------------------------

# El feed mezcla enlaces de sus dominios por país.
_ARBEITNOW_DOMAINS = {"arbeitnow." + tld for tld in (
    "com", "nl", "ch", "co.uk", "fr", "de", "at", "es", "it", "be", "pl", "ie", "se", "dk")}


def _parse_arbeitnow(data: dict) -> list[JobOffer]:
    offers = []
    for j in data.get("data", []):
        remote = bool(j.get("remote"))
        offers.append(build_offer(
            title=j.get("title"), url=j.get("url"), source="arbeitnow", company=j.get("company_name"),
            location=None if remote else j.get("location"), modality="remoto" if remote else None,
            remote_region=j.get("location") if remote else None, posted_at=_epoch(j.get("created_at")),
            expected_domains=_ARBEITNOW_DOMAINS))
    return _keep(offers)


async def fetch_arbeitnow(ctx: SourceContext) -> list[JobOffer]:
    return _parse_arbeitnow((await ctx.http.get("https://www.arbeitnow.com/api/job-board-api")).json())


FETCHERS = {
    "remotive": fetch_remotive, "remoteok": fetch_remoteok, "weworkremotely": fetch_weworkremotely,
    "himalayas": fetch_himalayas, "arbeitnow": fetch_arbeitnow,
}
