"""Salud de las fuentes: alertas cuando una fuente se rompe o devuelve mucho menos de lo normal."""
from __future__ import annotations

import json
from datetime import datetime
from statistics import median

from .models import JobOffer
from .paths import Paths
from .store import Store

DROP_POINTS = 30


def filled_pct(offers: list[JobOffer]) -> float:
    """% medio de campos company/location/posted_at rellenos."""
    if not offers:
        return 0.0
    total = sum((bool(o.company) + bool(o.location) + (o.posted_at is not None)) for o in offers)
    return 100.0 * total / (3 * len(offers))


def _load_state(paths: Paths) -> dict:
    try:
        return json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _alert_allowed(paths: Paths, name: str, now: datetime) -> bool:
    """Máx. 1 alerta por día y fuente; registra la fecha si se permite."""
    state = _load_state(paths)
    alerts = state.setdefault("health_alerts", {})
    today = now.date().isoformat()
    if alerts.get(name) == today:
        return False
    alerts[name] = today
    paths.state.parent.mkdir(parents=True, exist_ok=True)
    paths.state.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def check(store: Store, name: str, result, now: datetime, paths: Paths | None = None) -> str | None:
    """Alerta en español si la fuente falla o empeora; None si todo va bien o ya se avisó hoy.

    Debe llamarse ANTES de store.record_run de esta ejecución (la mediana usa las anteriores)."""
    paths = paths or Paths.default()
    message = None
    if result.error:
        message = f"La fuente {name} ha fallado: {result.error}"
    else:
        previous = [r for r in store.last_runs(name, 20) if r["ok"]][:5]
        if previous:
            med_count = median(r["count"] for r in previous)
            if not result.offers and med_count > 0:
                message = (f"La fuente {name} no ha devuelto ninguna oferta "
                           f"(lo normal son unas {med_count:g}); puede haber cambiado la web")
            else:
                fills = [r["filled_pct"] for r in previous if r["filled_pct"] is not None]
                if fills and result.offers:
                    now_pct, med_pct = filled_pct(result.offers), median(fills)
                    if med_pct - now_pct > DROP_POINTS:
                        message = (f"La fuente {name} rellena menos campos: {now_pct:.0f}% frente "
                                   f"al {med_pct:.0f}% habitual; puede haber cambiado la web")
    if message and _alert_allowed(paths, name, now):
        return message
    return None
