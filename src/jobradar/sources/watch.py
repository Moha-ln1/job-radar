"""Vigilancia de páginas de programas sin listado de ofertas: cada enlace del contenido principal es una "oferta".

No guarda estado: lo nuevo lo detecta el almacén por URL.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urldefrag, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from jobradar.models import JobOffer, build_offer
from jobradar.sources import SourceContext

_log = logging.getLogger("jobradar.sources.watch")

_SOCIAL = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com", "youtube.com", "youtu.be",
    "tiktok.com", "t.me", "wa.me", "whatsapp.com", "pinterest.com", "flickr.com", "threads.net", "discord.gg",
}
_FORMS = {"typeform.com", "forms.gle", "docs.google.com", "eventbrite.es", "eventbrite.com", "hubspot.com", "hsforms.com"}
_STATIC = re.compile(
    r"\.(?:pdf|zip|rar|docx?|xlsx?|pptx?|png|jpe?g|gif|svg|webp|ico|css|js|mp[34]|xml|json)$", re.I)
# Páginas institucionales que cambian a menudo pero nunca son una convocatoria (noticias, prensa,
# contacto, legal...). Se descartan salvo que el texto del enlace hable de inscribirse o de un programa.
_INSTITUTIONAL = re.compile(
    r"/(?:news|newsroom|noticias?|press|prensa|blog|author|autor|tag|category|categoria|contact[oa]?|"
    r"transparencia|licitaci[oó]n[^/]*|empleadores|empresas|financiadores|partners|alianzas[^/]*|"
    r"colaborador[^/]*|faqs?|preguntas-frecuentes|privac[^/]*|cookies?|aviso-legal|legal|"
    r"terminos[^/]*|politica[^/]*|about|sobre-nosotros|quienes-somos|equipo|team|donar|donate|"
    r"voluntari[^/]*|login|wp-login\.php)(?:/|$)", re.IGNORECASE)
_CALL_TEXT = re.compile(
    r"(?<![a-záéíóúñ])(?:inscri|plaza|plazo|convocatoria|candidatur|ap[uú]ntate|matr[ií]cula|beca|"
    r"pr[aá]cticas|nueva edici[oó]n|programa\b.*\btalent|sign[ _-]?up)", re.IGNORECASE)
_NOISE = ("nav", "header", "footer", "aside", "script", "style", "noscript", "svg")
_NOISE_ROLES = ("navigation", "banner", "contentinfo")


# Textos de enlace que no dicen nada por sí solos: se completan con el destino del enlace.
_GENERIC = re.compile(
    r"^[¡ ]*(?:(?:haz clic |pulsa |clic |click )?aqu[ií]|click here|here|descubre m[aá]s|ver m[aá]s.*|"
    r"leer m[aá]s|saber m[aá]s|m[aá]s informaci[oó]n|inf[oó]rmate|learn more|read more|more|"
    r"reserva tu plaza|inscr[ií]bete|ap[uú]ntate( ahora)?|[uú]nete)[.!¡ ]*$", re.IGNORECASE)


def _slug(path: str, host: str, own_host: str) -> str:
    """Última parte legible de la ruta ("/animate-y-prueba/" -> "animate y prueba")."""
    seg = next((s for s in reversed(path.split("/")) if s), "")
    if not seg and host != own_host:
        seg = host.split(".")[0]  # p. ej. "pdpython-diciembre-42malaga.eventbrite.es"
    return re.sub(r"[-_+]+", " ", seg).strip() or host


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def _in_domains(host: str, domains: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _parse_watch(html: str, base_url: str, name: str) -> list[JobOffer]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(_NOISE):
        tag.decompose()
    for tag in soup.find_all(attrs={"role": _NOISE_ROLES}):
        tag.decompose()
    root = soup.find("main") or soup.body or soup
    own_host = _host(base_url)
    offers: dict[str, JobOffer] = {}
    for a in root.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:", "sms:")):
            continue
        url = urldefrag(urljoin(base_url, href)).url
        parts = urlsplit(url)
        host = _host(url)
        if parts.scheme not in ("http", "https") or _STATIC.search(parts.path):
            continue
        if _in_domains(host, _SOCIAL):
            continue
        if not _in_domains(host, {own_host} | _FORMS):
            continue
        title = " ".join((a.get_text(" ", strip=True) or a.get("title") or a.get("aria-label") or "").split())
        if len(title) < 3:
            continue
        if _INSTITUTIONAL.search(parts.path) and not _CALL_TEXT.search(title):
            continue
        if _GENERIC.match(title):
            title = f"{title} ({_slug(parts.path, host, own_host)})"
        if len(title) > 200:  # tarjetas enteras como enlace (UGR): se recorta en vez de perder la convocatoria
            title = title[:199].rstrip() + "…"
        offer = build_offer(title=title, company=None, url=url, source=f"watch:{name}", category="vigilancia")
        if offer is not None:
            offers.setdefault(offer.url, offer)
    return list(offers.values())


async def fetch_watch(ctx: SourceContext) -> list[JobOffer]:
    offers: list[JobOffer] = []
    for entry in ctx.settings.watch:
        try:
            resp = await ctx.http.get(entry["url"])
        except httpx.HTTPError as exc:  # SourceBlocked no es HTTPError: se propaga
            _log.warning("no se pudo vigilar %s (%s): %s", entry.get("name"), entry["url"], exc)
            continue
        offers.extend(_parse_watch(resp.text, str(resp.url), entry["name"]))
    return offers


FETCHERS = {"watch": fetch_watch}
