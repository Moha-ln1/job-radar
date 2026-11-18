"""Portales de empleo que solo ofrecen HTML: LinkedIn (invitado), InfoJobs, Tecnoempleo, Infoempleo y Primerempleo.

Cada portal tiene una función pura ``_parse_<portal>(html)`` (testeable con fixtures) y su ``fetch``.
Vía 1: JSON embebido o JSON-LD si el portal lo trae (InfoJobs). Vía 2: enlaces de oferta y su contenedor.
"""
from __future__ import annotations
from jobradar.normalize import parse_iso

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from jobradar.http import SourceBlocked
from jobradar.models import JobOffer, build_offer
from jobradar.normalize import fold
from jobradar.sources import SourceContext


_log = logging.getLogger("jobradar.sources")
_UNITS = (  # (prefijo plegado, segundos)
    ("min", 60), ("h", 3600), ("d", 86400), ("sem", 7 * 86400), ("w", 7 * 86400), ("mes", 30 * 86400),
)
_RELATIVE = re.compile(r"hace\s+(\d+)\s*([a-z]+)")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _text(el: Tag | None) -> str | None:
    return " ".join(el.get_text(" ", strip=True).split()) or None if el else None


def _relative_date(text: str | None, now: datetime | None = None) -> datetime | None:
    """'Hace 5 días', 'Hace 3 horas', 'Hace 5d', 'hace 27 horas' -> fecha aproximada UTC."""
    m = _RELATIVE.search(fold(text or ""))
    if not m:
        return None
    n, word = int(m.group(1)), m.group(2)
    secs = next((s for prefix, s in _UNITS if word.startswith(prefix)), None)
    if secs is None:
        return None
    return (now or datetime.now(timezone.utc)) - timedelta(seconds=n * secs)


def _iso_date(value: str | None) -> datetime | None:
    return parse_iso(value)


def _dedup(offers: list[JobOffer | None]) -> list[JobOffer]:
    seen: dict[str, JobOffer] = {}
    for o in offers:
        if o is not None:
            seen.setdefault(o.url, o)
    return list(seen.values())


def _partial(exc: SourceBlocked, offers: list[JobOffer | None]) -> SourceBlocked:
    """Adjunta al bloqueo lo ya descargado: un 429 en la búsqueda 12 no debe tirar las 11 anteriores."""
    exc.partial = _dedup(offers)
    return exc


def _strip_query(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _search_terms(ctx: SourceContext, limit: int = 3) -> list[str]:
    return ctx.terms[:limit] or ["prácticas"]


def _modality(text: str | None) -> str | None:
    t = fold(text or "")
    if "hibrid" in t:
        return "hibrido"
    if "remot" in t or "teletrabajo" in t:
        return "remoto"
    if "presencial" in t:
        return "presencial"
    return None


# --------------------------------------------------------------------------------------- LinkedIn
_LI_DOMAINS = {"linkedin.com"}


def _parse_linkedin(html: str) -> list[JobOffer]:
    offers = []
    for card in _soup(html).select("div.base-card"):
        link = card.select_one("a.base-card__full-link")
        if link is None or not link.get("href"):
            continue
        time_el = card.select_one("time[datetime]")
        offers.append(build_offer(
            expected_domains=_LI_DOMAINS,
            title=_text(card.select_one(".base-search-card__title")) or "",
            company=_text(card.select_one(".base-search-card__subtitle")),
            location=_text(card.select_one(".job-search-card__location")),
            url=_strip_query(link["href"]),
            source="linkedin",
            posted_at=_iso_date(time_el["datetime"]) if time_el else None,
        ))
    return _dedup(offers)


_li_places: dict[str, str] | None = None


def linkedin_location(label: str) -> str:
    """Nombre de ubicación que LinkedIn entiende. Sin ", Spain" geolocaliza mal: "España" da ofertas
    de EE. UU., "Sevilla" de Colombia y "Córdoba" de México (comprobado 16/11/2026)."""
    global _li_places
    if _li_places is None:
        from pathlib import Path

        from jobradar.filters import Catalog
        cat = Catalog.from_file(Path(__file__).resolve().parents[1] / "data" / "catalogo.yaml")
        _li_places = {}
        for key, entry in cat.ubicaciones.items():
            if entry.get("linkedin"):
                _li_places[fold(key)] = _li_places[fold(entry.get("label", key))] = entry["linkedin"]
    return _li_places.get(fold(label), label)


async def fetch_linkedin(ctx: SourceContext) -> list[JobOffer]:
    opts = ctx.options("linkedin")
    max_pages = int(opts.get("max_pages", 3))
    max_locations = int(opts.get("max_locations", 3))
    # Se para antes del límite de la fuente para devolver lo encontrado en vez de perderlo todo
    deadline = time.monotonic() + 0.85 * float(opts.get("timeout_seconds", 90))
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    offers: list[JobOffer] = []
    try:
        # Primero lo que LinkedIn marca como remoto (f_WT=2): el listado no trae la modalidad y, como
        # _dedup se queda con la primera, estas ofertas conservan su etiqueta "remoto".
        remote_terms = (ctx.combos or ctx.terms)[:int(opts.get("remote_terms", 3))]
        for term in remote_terms if opts.get("remote_pass", True) else []:
            for page in range(int(opts.get("remote_pages", 2))):
                if time.monotonic() > deadline:
                    break
                url = (f"{base}?keywords={quote_plus(term)}&location={quote_plus(linkedin_location('españa'))}"
                       f"&start={page * 10}&f_TPR=r604800&f_WT=2&sortBy=DD")
                cards = _parse_linkedin((await ctx.http.get(url)).text)
                offers.extend(o.model_copy(update={"modality": "remoto"}) for o in cards)
                if len(cards) < 10:
                    break
        # tipo + área ("prácticas python"): un tipo a secas trae ofertas de cualquier sector
        for term in (ctx.combos or ctx.terms)[:int(opts.get("max_terms", 5))] or ["prácticas"]:
            # 3 ubicaciones: p. ej. Granada y Málaga (presencial) + España (remoto/híbrido)
            for location in [linkedin_location(loc) for loc in ctx.locations[:max_locations]] or [""]:
                for page in range(max_pages):
                    if time.monotonic() > deadline:
                        _log.warning("LinkedIn: tiempo casi agotado, se devuelven %d ofertas", len(offers))
                        return _dedup(offers)
                    # sortBy=DD: primero las más recientes, que son las que interesan en cada escaneo
                    url = (f"{base}?keywords={quote_plus(term)}&location={quote_plus(location)}"
                           f"&start={page * 10}&f_TPR=r604800&sortBy=DD")
                    resp = await ctx.http.get(url)
                    cards = _parse_linkedin(resp.text)
                    offers.extend(cards)
                    if len(cards) < 10:
                        break
    except SourceBlocked as exc:
        raise _partial(exc, offers) from None
    return _dedup(offers)


# --------------------------------------------------------------------------------------- InfoJobs
_IJ_DOMAINS = {"infojobs.net"}
_IJ_PROPS = re.compile(r"window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\((\".*?\")\)\s*;?\s*</script>", re.S)
_IJ_OFFER_LINK = re.compile(r"/of-i[0-9a-f]+")


def _ij_url(link: str) -> str:
    return _strip_query(urljoin("https://www.infojobs.net/", link))


def _parse_infojobs(html: str) -> list[JobOffer]:
    m = _IJ_PROPS.search(html)
    if m:
        try:
            raw = json.loads(json.loads(m.group(1))).get("offers") or []
        except (ValueError, AttributeError):
            raw = []
        offers = [build_offer(
            expected_domains=_IJ_DOMAINS,
            title=o.get("title") or "",
            company=o.get("companyName"),
            location=o.get("city"),
            modality=_modality(o.get("teleworking")),
            url=_ij_url(o["link"]),
            source="infojobs",
            posted_at=_iso_date(o.get("publishedAt")),
        ) for o in raw if o.get("link")]
        if offers:
            return _dedup(offers)
    return _parse_infojobs_cards(html)


def _parse_infojobs_cards(html: str) -> list[JobOffer]:
    """Vía 2: enlaces ``/of-i<hex>`` y su ``<li>`` contenedor (sin depender de clases)."""
    offers = []
    for link in _soup(html).find_all("a", href=_IJ_OFFER_LINK):
        card = link.find_parent("li")
        title = link.get("aria-label") or _text(link)
        company_el = card.find("h3") if card else None
        facts = [_text(li) for li in card.find_all("li")] if card else []
        since = next((f for f in facts if f and _relative_date(f)), None)
        place = next((f for f in facts if f and f is not since and not _modality(f)), None)
        offers.append(build_offer(
            expected_domains=_IJ_DOMAINS, title=title or "", company=_text(company_el), location=place,
            modality=next((_modality(f) for f in facts if _modality(f)), None),
            url=_ij_url(link["href"]), source="infojobs", posted_at=_relative_date(since),
        ))
    return _dedup(offers)


def _parse_infojobs_api(data: dict) -> list[JobOffer]:
    """Respuesta de la API oficial ``GET /api/9/offer`` (doc pública de InfoJobs)."""
    offers = []
    for o in data.get("offers") or []:
        exp = (o.get("experienceMin") or {}).get("value")
        offers.append(build_offer(
            expected_domains=_IJ_DOMAINS,
            title=o.get("title") or "",
            company=(o.get("author") or {}).get("name"),
            location=o.get("city") or (o.get("province") or {}).get("value"),
            modality=_modality((o.get("teleworking") or {}).get("value")),
            url=_ij_url(o.get("link") or ""),
            source="infojobs",
            posted_at=_iso_date(o.get("published") or o.get("updated")),
            category=(o.get("category") or {}).get("value"),
            description=f"Experiencia mínima: {exp}" if exp else None,
        ))
    return _dedup(offers)


def _infojobs_terms(ctx: SourceContext) -> list[str]:
    """InfoJobs bloquea a partir de unas 3 peticiones seguidas y "prácticas" a secas trae 20 ofertas de
    cualquier sector: pocas búsquedas combinadas de tipo y área (sacadas de tus búsquedas). `keywords` en
    config.yaml las sustituye si quieres fijarlas a mano."""
    custom = ctx.options("infojobs").get("keywords")
    return list(custom)[:3] if custom else (ctx.combos[:3] or _search_terms(ctx))


async def _infojobs_html(ctx: SourceContext) -> list[JobOffer]:
    offers: list[JobOffer] = []
    try:
        for term in _infojobs_terms(ctx):
            resp = await ctx.http.get(
                f"https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword={quote_plus(term)}")
            offers.extend(_parse_infojobs(resp.text))
    except SourceBlocked as exc:
        raise _partial(exc, offers) from None
    return _dedup(offers)


async def fetch_infojobs(ctx: SourceContext) -> list[JobOffer]:
    cid, secret = ctx.env.get("INFOJOBS_CLIENT_ID"), ctx.env.get("INFOJOBS_CLIENT_SECRET")
    if not (cid and secret):
        return await _infojobs_html(ctx)
    offers: list[JobOffer] = []
    for term in _infojobs_terms(ctx):
        try:
            resp = await ctx.http.get(
                "https://api.infojobs.net/api/9/offer",
                params={"q": term, "maxResults": 50, "order": "updated-desc", "sinceDate": "_7_DAYS"},
                auth=(cid, secret))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                _log.warning("clave de InfoJobs no válida: se usa el HTML público")
                return await _infojobs_html(ctx)
            raise
        offers.extend(_parse_infojobs_api(resp.json()))
    return _dedup(offers)


# ------------------------------------------------------------------------------------ Tecnoempleo
_TE_DOMAINS = {"tecnoempleo.com"}
_TE_META = re.compile(r"^(?P<place>.*?)\s+-\s+(?P<date>\d{2}/\d{2}/\d{4})")


def _parse_tecnoempleo(html: str) -> list[JobOffer]:
    offers = []
    for card in _soup(html).select('div[onclick*="/rf-"]'):
        link = card.find("a", href=re.compile(r"/rf-[0-9a-f]+$"))
        if link is None:
            continue
        company = next((a for a in card.find_all("a", href=True) if a is not link and "/rf-" not in a["href"]), None)
        meta = _TE_META.match(_text(card.select_one("span.d-lg-none")) or "")
        place, posted, modality = None, None, None
        if meta:
            day, month, year = meta["date"].split("/")
            posted = datetime(int(year), int(month), int(day), tzinfo=timezone.utc)
            modality = _modality(meta["place"])
            place = None if "remoto" in fold(meta["place"]) else re.sub(r"\s*\([^)]*\)", "", meta["place"]).strip() or None
        offers.append(build_offer(
            expected_domains=_TE_DOMAINS, title=link.get("title") or _text(link) or "", company=_text(company),
            location=place, modality=modality, url=link["href"], source="tecnoempleo", posted_at=posted))
    return _dedup(offers)


async def fetch_tecnoempleo(ctx: SourceContext) -> list[JobOffer]:
    offers: list[JobOffer] = []
    try:
        for term in _search_terms(ctx):
            resp = await ctx.http.get(f"https://www.tecnoempleo.com/ofertas-trabajo/?te={quote_plus(term)}")
            offers.extend(_parse_tecnoempleo(resp.text))
    except SourceBlocked as exc:
        raise _partial(exc, offers) from None
    return _dedup(offers)


# ------------------------------------------------------------------------------------- Infoempleo
_IE_DOMAINS = {"infoempleo.com"}
_IE_LINK = re.compile(r"^/ofertasdetrabajo/.+/\d+/?$")


def _parse_infoempleo(html: str) -> list[JobOffer]:
    offers = []
    for card in _soup(html).select("li.offerblock"):
        link = card.find("a", href=_IE_LINK)
        if link is None:
            continue
        place = card.select_one(".offer-location-desktop") or card.select_one(".offer-location span")
        offers.append(build_offer(
            expected_domains=_IE_DOMAINS, title=_text(link) or "", company=_text(card.select_one(".company-name")),
            location=_text(place), url=urljoin("https://www.infoempleo.com/", link["href"]),
            source="infoempleo", posted_at=_relative_date(_text(card.select_one(".offer-date")))))
    return _dedup(offers)


async def fetch_infoempleo(ctx: SourceContext) -> list[JobOffer]:
    offers: list[JobOffer] = []
    try:
        for term in ctx.combos[:3] or _search_terms(ctx):  # portal generalista: tipo + área
            resp = await ctx.http.get(f"https://www.infoempleo.com/trabajo/?q={quote_plus(term)}")
            offers.extend(_parse_infoempleo(resp.text))
    except SourceBlocked as exc:
        raise _partial(exc, offers) from None
    return _dedup(offers)


# ------------------------------------------------------------------------------------ Primerempleo
_PE_DOMAINS = {"primerempleo.com"}
_PE_LINK = re.compile(r"^/[^/]+/[^/]+/[^/]+/\d+$")  # /primer-empleo/<lugar>/<slug>/<id>


def _parse_primerempleo(html: str) -> list[JobOffer]:
    offers = []
    for card in _soup(html).select("div.well-box"):
        link = card.find("a", href=_PE_LINK, target="_blank")
        if link is None:
            continue
        marker = card.select_one(".fa-map-marker")
        offers.append(build_offer(
            expected_domains=_PE_DOMAINS, title=_text(link) or "", company=_text(card.select_one("a.author-name")),
            location=_text(marker.parent) if marker else None,
            url=urljoin("https://www.primerempleo.com/", link["href"]), source="primerempleo"))
    return _dedup(offers)


async def fetch_primerempleo(ctx: SourceContext) -> list[JobOffer]:
    """El portal solo busca por etiquetas (``/?q=madrid``); sin etiqueta devuelve las últimas ofertas."""
    queries = [""] + [fold(t) for t in _search_terms(ctx)] + [fold(loc) for loc in ctx.locations if fold(loc) != "espana"]
    offers: list[JobOffer] = []
    try:
        for q in dict.fromkeys(queries):
            resp = await ctx.http.get("https://www.primerempleo.com/" + (f"?q={quote_plus(q)}" if q else ""))
            offers.extend(_parse_primerempleo(resp.text))
    except SourceBlocked as exc:
        raise _partial(exc, offers) from None
    return _dedup(offers)


FETCHERS = {
    "linkedin": fetch_linkedin,
    "infojobs": fetch_infojobs,
    "tecnoempleo": fetch_tecnoempleo,
    "infoempleo": fetch_infoempleo,
    "primerempleo": fetch_primerempleo,
}
