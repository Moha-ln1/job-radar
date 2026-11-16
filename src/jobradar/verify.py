"""Contraste de lo extraído con la página de detalle (JSON-LD JobPosting)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from . import health
from .config import load_env
from .dedup import similar
from .http import Http, SourceBlocked
from .models import JobOffer
from .normalize import norm_company, norm_title
from .paths import Paths
from .sources import Fetcher, SourceContext
from .sources.official_apis import missing_keys


@dataclass
class VerifyRow:
    source: str
    count: int
    filled_pct: float
    checked: int
    ok: bool
    mismatches: list[str] = field(default_factory=list)


def _find_jobposting(data) -> dict | None:
    if isinstance(data, list):
        for item in data:
            if (found := _find_jobposting(item)):
                return found
    elif isinstance(data, dict):
        t = data.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
            return data
        return _find_jobposting(data.get("@graph"))
    return None


def _jsonld_job(soup: BeautifulSoup) -> dict | None:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            found = _find_jobposting(json.loads(tag.string or tag.get_text()))
        except ValueError:
            continue
        if found:
            return found
    return None


def _company_name(job: dict) -> str | None:
    org = job.get("hiringOrganization")
    if isinstance(org, dict):
        org = org.get("name")
    return org if isinstance(org, str) else None


_BLOCK_MARKERS = ("no podemos identificar tu navegador", "captcha", "just a moment",
                  "access denied", "verify you are human", "cf-chl")


def _titles_match(listed: str, detail: str, threshold: float) -> bool:
    """Coinciden si son parecidos o si el detalle contiene todas las palabras del listado
    (p. ej. '[Hiring] Puesto @Empresa' frente a 'Puesto')."""
    want = set(norm_title(listed).split())
    return similar(listed, detail) >= threshold or (
        len(want) >= 2 and want <= set(norm_title(detail).split()))


def _compare(offer: JobOffer, html: str) -> str | None:
    """None si coincide; si no, 'ESTADO: detalle'."""
    if any(m in html[:20000].lower() for m in _BLOCK_MARKERS) and "jobposting" not in html.lower():
        return "DETALLE_BLOQUEADO: la página de detalle muestra un muro anti-bot"
    soup = BeautifulSoup(html, "html.parser")
    job = _jsonld_job(soup)
    if job:
        title = job.get("title") or job.get("name")
        if isinstance(title, str) and not _titles_match(offer.title, title, 0.9):
            return f"DIFERENTE: título '{offer.title}' ≠ '{title}'"
        company, other = offer.company, _company_name(job)
        if company and other and norm_company(company) != norm_company(other) \
                and similar(company, other) < 0.9:
            return f"DIFERENTE: empresa '{company}' ≠ '{other}'"
        return None
    texts = [t.get_text(" ") for t in soup.find_all(["title", "h1"])]
    if not texts:
        return "SIN_DATOS: la página no tiene JSON-LD ni título"
    for t in texts:
        if _titles_match(offer.title, t, 0.8):
            return None
    return f"DIFERENTE: '{offer.title}' no aparece en el título de la página"


async def verify(paths: Paths, sample: int = 3, *, fetchers: dict[str, Fetcher] | None = None,
                 http: Http | None = None, only: list[str] | None = None) -> list[VerifyRow]:
    from .radar import (
        derive_combos,
        derive_locations,
        derive_terms,
        load_context,
        run_sources,
    )
    settings, searches, _excl, syn, catalog = load_context(paths)
    if fetchers is None:
        from .sources import all_fetchers
        fetchers = all_fetchers()
    own_http = http is None
    http = http or Http(settings.http)
    try:
        names = only or [n for n, o in settings.sources.items() if o.get("enabled", True)]
        ctx = SourceContext(http=http, settings=settings, terms=derive_terms(searches, syn, catalog),
                            locations=derive_locations(searches, catalog),
                            combos=derive_combos(searches, syn, catalog),
                            env=load_env(paths.env) if paths.env.exists() else {})
        results = await run_sources(ctx, names, fetchers)
        rows = []
        for name, res in results.items():
            if res.error:
                rows.append(VerifyRow(name, 0, 0.0, 0, False, [f"ERROR: {res.error}"]))
                continue
            if not res.offers and missing_keys(name, ctx.env):
                rows.append(VerifyRow(name, 0, 0.0, 0, True, ["SIN_CLAVE: opcional, ver docs/APIS.md"]))
                continue
            problems: list[str] = []
            bad = not res.offers
            if bad:
                problems.append("DIFERENTE: 0 ofertas")
            # Los enlaces vigilados no son ofertas: no tiene sentido contrastar su texto con el destino.
            picked = [] if name.startswith("watch") else res.offers[:sample]
            for offer in picked:
                try:
                    msg = _compare(offer, (await http.get(offer.url)).text)
                except SourceBlocked as exc:
                    msg = f"DETALLE_BLOQUEADO: {exc}"
                except Exception as exc:
                    msg = f"ERROR HTTP: {exc}"
                if msg:
                    problems.append(f"{msg} ({offer.url})")
                    bad = bad or not msg.startswith(("SIN_DATOS", "DETALLE_BLOQUEADO"))
            rows.append(VerifyRow(name, len(res.offers), health.filled_pct(res.offers),
                                  len(picked), not bad, problems))
        return rows
    finally:
        if own_http:
            await http.__aexit__()


def format_table(rows: list[VerifyRow]) -> str:
    lines = [f"{'Fuente':<18}{'Ofertas':>8}{'Rellenos':>10}{'Comprobadas':>13}  Estado"]
    for r in rows:
        lines.append(f"{r.source:<18}{r.count:>8}{r.filled_pct:>9.0f}%{r.checked:>13}  "
                     f"{'OK' if r.ok else 'FALLO'}")
        lines += [f"    - {m}" for m in r.mismatches]
    return "\n".join(lines)
