"""Escaneo: orquesta fuentes, almacenamiento, filtros y salud."""
from __future__ import annotations

import asyncio
import re
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import health
from .config import Settings, load_env, load_searches, load_settings
from .filters import Catalog, Synonyms, evaluate
from .http import Http
from .models import Decision, JobOffer, Search
from .normalize import fold
from .paths import Paths
from .sources import Fetcher, SourceContext
from .store import Job, Posting, Store

_log = logging.getLogger("jobradar.radar")
_DATA = Path(__file__).parent / "data"
MAX_TERMS = 8
_ES_END = ("dor", "dora", "ario", "aria", "cion", "as", "os", "ista", "dad", "ica", "ico")


@dataclass
class SourceResult:
    name: str
    offers: list[JobOffer] = field(default_factory=list)
    error: str | None = None
    ms: int = 0


@dataclass
class ScanReport:
    new_matched: list[Job] = field(default_factory=list)
    new_discarded: int = 0
    new_postings_for_notified: list[tuple[Job, Posting]] = field(default_factory=list)
    source_status: dict[str, SourceResult] = field(default_factory=dict)
    health_alerts: list[str] = field(default_factory=list)
    new_jobs: list[Job] = field(default_factory=list)  # todos los nuevos (para el arranque inicial)


def _looks_spanish(term: str) -> bool:
    return term.endswith(_ES_END) or " de " in term


def derive_terms(searches: list[Search], syn: Synonyms, catalog: Catalog) -> list[str]:
    """Término principal en español e inglés de cada tipo/área de las búsquedas activas."""
    out: list[str] = []
    for s in searches:
        if s.paused:
            continue
        for key in [*s.tipos, *s.areas]:
            if fold(key) == "cualquiera":
                continue
            members = syn.expand(key)
            es = next((m for m in members if _looks_spanish(m)), members[0])
            en = next((m for m in members if m != es and not _looks_spanish(m)), None)
            if en is None and len(members) > 1:
                en = members[1] if members[0] == es else members[0]
            label = catalog.tipos.get(fold(key)) or catalog.areas.get(fold(key))
            # "Datos / IA" no sirve como término para un portal: solo etiquetas de una pieza
            if label and "/" not in label and es == members[0]:
                es = label.lower()
            for t in (es, en):
                if t and t not in out:
                    out.append(t)
    return out[:MAX_TERMS]


def derive_locations(searches: list[Search], catalog: Catalog) -> list[str]:
    out: list[str] = []
    for s in searches:
        if s.paused:
            continue
        for u in s.ubicaciones:
            label = (catalog.ubicaciones.get(fold(u)) or {}).get("label", u)
            if label not in out:
                out.append(label)
    return out or ["España"]


BLOCK_COOLDOWN_MIN_HOURS = 6
BLOCK_COOLDOWN_MAX_HOURS = 48


def _ts(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def cooldown_until(settings: Settings, store: Store, name: str) -> datetime | None:
    """Si la fuente nos ha bloqueado en sus últimas ejecuciones, hasta cuándo se deja descansar.

    Cada bloqueo seguido duplica la pausa (6 h, 12 h, 24 h... hasta 48 h) para no insistir
    contra una web que ya nos ha cortado. Una ejecución correcta pone el contador a cero."""
    blocked, last = 0, None
    for run in store.last_runs(name, 6):
        if run["ok"] or "bloquea" not in (run.get("error") or ""):
            break
        blocked += 1
        last = last or _ts(run["ts"])
    if not blocked:
        return None
    opts = settings.sources.get(name, {})
    base = max(BLOCK_COOLDOWN_MIN_HOURS, opts.get("min_interval_hours", settings.scan.every_hours))
    return last + timedelta(hours=min(base * 2 ** (blocked - 1), BLOCK_COOLDOWN_MAX_HOURS))


# Enlaces de páginas vigiladas que suelen indicar una convocatoria abierta → aviso al momento.
# El resto de enlaces nuevos (noticias, contacto...) va al resumen diario para no meter ruido.
_CALL_WORDS = re.compile(
    r"inscri|apunt|plaza|convocatoria|candidatur|admisi|matr[ií]cula|solicit|sign[_ -]?up|apply|"
    r"registr|piscina|piscine|proceso de selecci|nueva edici|abiert|open call|eventbrite|typeform|forms",
    re.IGNORECASE)


def watch_decision(offer) -> Decision:
    """Decisión para un enlace nuevo de una página vigilada (no pasa por los filtros de ofertas)."""
    urgent = bool(_CALL_WORDS.search(f"{offer.title} {offer.url}"))
    return Decision(matched=["watch"], priority="alta" if urgent else "normal",
                    reasons=["página vigilada: enlace nuevo" + (" (parece una convocatoria)" if urgent else "")])


def due_sources(settings: Settings, store: Store, now: datetime) -> list[str]:
    due = []
    for name, opts in settings.sources.items():
        if not opts.get("enabled", True):
            continue
        pause = cooldown_until(settings, store, name)
        if pause and now < pause:
            continue
        hours = opts.get("min_interval_hours", settings.scan.every_hours)
        runs = store.last_runs(name, 1)
        if runs and now - _ts(runs[0]["ts"]) < timedelta(hours=hours):
            continue
        due.append(name)
    return due


async def run_sources(ctx: SourceContext, names: list[str], fetchers: dict[str, Fetcher],
                      timeout: float = 90) -> dict[str, SourceResult]:
    async def one(name: str) -> SourceResult:
        t0 = time.monotonic()
        limit = timeout
        fetcher = fetchers.get(name)
        if fetcher is None:
            return SourceResult(name, error="fuente desconocida (sin implementación)")
        try:
            limit = ctx.options(name).get("timeout_seconds", timeout)
            offers = await asyncio.wait_for(fetcher(ctx), limit)
            return SourceResult(name, offers=list(offers), ms=int((time.monotonic() - t0) * 1000))
        except asyncio.TimeoutError:
            err = f"tiempo de espera agotado ({limit:g} s)"
        except Exception as exc:  # una fuente nunca debe afectar a las demás
            _log.warning("fuente %s falló: %r", name, exc)
            err = str(exc) or type(exc).__name__
        return SourceResult(name, error=err, ms=int((time.monotonic() - t0) * 1000))

    results = await asyncio.gather(*(one(n) for n in names), return_exceptions=True)
    out: dict[str, SourceResult] = {}
    for name, r in zip(names, results):
        out[name] = r if isinstance(r, SourceResult) else SourceResult(name, error=str(r))
    return out


def load_context(paths: Paths):
    """(settings, búsquedas, exclusiones, sinónimos, catálogo) desde los archivos de trabajo."""
    settings = load_settings(paths.config) if paths.config.exists() else Settings()
    searches, excl = load_searches(paths.searches)
    user = paths.user_synonyms if paths.user_synonyms.exists() else None
    syn = Synonyms.from_files(_DATA / "sinonimos.yaml", user)
    catalog = Catalog.from_file(_DATA / "catalogo.yaml")
    return settings, searches, excl, syn, catalog


async def scan(paths: Paths, now: datetime | None = None, *, only: list[str] | None = None,
               dry_run: bool = False, fetchers: dict[str, Fetcher] | None = None,
               http: Http | None = None) -> ScanReport:
    now = now or datetime.now(timezone.utc)
    settings, searches, excl, syn, catalog = load_context(paths)
    if fetchers is None:
        from .sources import all_fetchers
        fetchers = all_fetchers()
    store = Store(":memory:" if dry_run else paths.db)
    own_http = http is None
    http = http or Http(settings.http)
    report = ScanReport()
    try:
        names = only if only is not None else due_sources(settings, store, now)
        ctx = SourceContext(http=http, settings=settings,
                            terms=derive_terms(searches, syn, catalog),
                            locations=derive_locations(searches, catalog),
                            env=load_env(paths.env) if paths.env.exists() else {})
        results = await run_sources(ctx, names, fetchers)
        for name, res in results.items():
            report.source_status[name] = res
            if not dry_run:
                alert = health.check(store, name, res, now, paths)
                if alert:
                    report.health_alerts.append(alert)
            store.record_run(name, now, res.error is None, len(res.offers),
                             health.filled_pct(res.offers) if res.error is None else None, res.error)
            if res.error:
                continue
            up = store.upsert(res.offers, now)
            # Páginas vigiladas con `filtrar: true` (p. ej. un portal de prácticas con ofertas de todo
            # tipo): sus enlaces pasan por las búsquedas como cualquier oferta.
            filtered = {f"watch:{w.get('name')}" for w in settings.watch if w.get("filtrar")}
            for job in up.new_jobs:
                src = job.first_posting.source if job.first_posting else ""
                if src.startswith("watch:") and src not in filtered:
                    store.set_decision(job.id, watch_decision(job.offer_view()))
                else:
                    store.set_decision(job.id, evaluate(job.offer_view(), searches, excl, syn, catalog,
                                                        now, settings.scan.max_age_days))
                job = store.get_job(job.id)
                report.new_jobs.append(job)
                if job.status == "avisada":
                    report.new_matched.append(job)
                else:
                    report.new_discarded += 1
            report.new_postings_for_notified += [(j, p) for j, p in up.new_postings
                                                 if j.notified_at is not None]
    finally:
        store.close()
        if own_http:
            await http.__aexit__()
    return report


async def init_baseline(paths: Paths, now: datetime | None = None, **kw) -> ScanReport:
    """Primera ejecución: todo lo encontrado queda como notificado, sin avisar."""
    now = now or datetime.now(timezone.utc)
    report = await scan(paths, now, **kw)
    store = Store(paths.db)
    try:
        for job in report.new_jobs:
            store.mark_notified(job.id, None, now)
    finally:
        store.close()
    report.new_matched = []
    return report


def reevaluate(paths: Paths, search_ids: list[str], days: int = 14,
               now: datetime | None = None) -> list[Job]:
    """Aplica búsquedas nuevas o editadas a lo descartado de los últimos días."""
    now = now or datetime.now(timezone.utc)
    settings, searches, excl, syn, catalog = load_context(paths)
    chosen = [s for s in searches if s.id in search_ids]
    store = Store(paths.db)
    try:
        found = []
        for job in store.recent(days, now, "descartada"):
            d = evaluate(job.offer_view(), chosen, excl, syn, catalog, now, settings.scan.max_age_days)
            if d.ok:
                store.set_decision(job.id, d)
                found.append(store.get_job(job.id))
        return found
    finally:
        store.close()


def probe(paths: Paths, text: str, now: datetime | None = None) -> Decision | None:
    """Evalúa un texto como si fuera el título de una oferta; None si no es un título válido."""
    from .models import build_offer
    offer = build_offer(title=text, url="https://ejemplo.invalid/prueba", source="probar")
    if offer is None:
        return None
    settings, searches, excl, syn, catalog = load_context(paths)
    return evaluate(offer, searches, excl, syn, catalog, now or datetime.now(timezone.utc),
                    settings.scan.max_age_days)
