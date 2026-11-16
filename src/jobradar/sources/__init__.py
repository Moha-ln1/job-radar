"""Fuentes de ofertas.

Contrato: cada módulo de este paquete expone ``FETCHERS: dict[str, Fetcher]``, donde la clave es el nombre de la
fuente en ``config.yaml`` (``sources:``) y el valor es ``async def fetch(ctx: SourceContext) -> list[JobOffer]``.

- Usa siempre ``ctx.http`` (ritmo por dominio y SourceBlocked ya incluidos) y ``build_offer(expected_domains=...)``.
- No filtres por tipo/área en la fuente: eso lo hace ``filters.evaluate``. Sí puedes usar ``ctx.terms`` y
  ``ctx.locations`` como parámetros de búsqueda del portal para traer menos.
- Deja que ``SourceBlocked`` y los errores de red se propaguen: ``radar`` los aísla por fuente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from jobradar.config import Settings
from jobradar.http import Http
from jobradar.models import JobOffer


@dataclass
class SourceContext:
    http: Http
    settings: Settings
    terms: list[str] = field(default_factory=list)       # p. ej. ["prácticas", "internship", "trainee"]
    locations: list[str] = field(default_factory=list)   # p. ej. ["Granada", "España"]
    env: dict[str, str] = field(default_factory=dict)    # claves opcionales de .env
    # Tipo + área de tus búsquedas, p. ej. ["prácticas programador", "junior programador"]: para portales
    # generalistas, donde "prácticas" a secas trae ofertas de cualquier sector.
    combos: list[str] = field(default_factory=list)

    def options(self, name: str) -> dict:
        """Opciones de la fuente en config.yaml (``sources.<name>``)."""
        return self.settings.sources.get(name, {})


Fetcher = Callable[[SourceContext], Awaitable[list[JobOffer]]]


def all_fetchers() -> dict[str, Fetcher]:
    """Registro de todas las fuentes disponibles."""
    from jobradar.sources import ats, html_portals, official_apis, remote, watch

    registry: dict[str, Fetcher] = {}
    for module in (ats, remote, html_portals, official_apis, watch):
        registry.update(module.FETCHERS)
    return registry
