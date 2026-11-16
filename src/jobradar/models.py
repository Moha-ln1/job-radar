"""Modelos de datos: oferta validada, búsqueda, exclusiones y decisión."""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, field_validator, model_validator

from .normalize import fold

Modality = Literal["presencial", "hibrido", "remoto"]

_TAGS = re.compile(r"<[^>]*>")
_TRACKING = {
    "trk", "trackingid", "refid", "ref", "src", "position", "pagenum", "gclid", "fbclid",
}
_log = logging.getLogger("jobradar.extract")


def _clean_text(v: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(v)).strip()


class JobOffer(BaseModel):
    title: str
    url: str
    source: str
    company: str | None = None
    location: str | None = None
    modality: Modality | None = None
    remote_region: str | None = None
    posted_at: datetime | None = None
    category: str | None = None
    description: str | None = None  # NUNCA se usa para filtrar

    @field_validator(
        "title", "url", "source", "company", "location", "remote_region", "category",
        mode="before",
    )
    @classmethod
    def _clean(cls, v):
        if not isinstance(v, str):
            return v
        v = _clean_text(v)
        if _TAGS.search(v):
            raise ValueError("contiene restos de HTML")
        return v or None

    @field_validator("description", mode="before")
    @classmethod
    def _clean_description(cls, v):
        # La descripción suele venir con HTML: solo se decodifica y se recorta.
        return html.unescape(v).strip() or None if isinstance(v, str) else v

    @field_validator("title")
    @classmethod
    def _title_len(cls, v: str) -> str:
        if not 3 <= len(v) <= 200:
            raise ValueError("el título debe tener entre 3 y 200 caracteres")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        parts = urlsplit(v)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("la URL debe ser absoluta (http/https)")
        query = [
            (k, val) for k, val in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in _TRACKING
        ]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    @field_validator("posted_at")
    @classmethod
    def _posted(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        v = v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        if v > now + timedelta(days=1) or v < now - timedelta(days=365):
            return None  # fecha dudosa: no se rechaza la oferta
        return v

    @model_validator(mode="after")
    def _title_not_company(self):
        if self.company and fold(self.title) == fold(self.company):
            raise ValueError("el título es igual que la empresa")
        return self


def build_offer(*, expected_domains: set[str] | None = None, **fields) -> JobOffer | None:
    """Construye una oferta; si no es válida la registra en el log y devuelve None."""
    try:
        offer = JobOffer(**fields)
    except Exception as exc:  # ValidationError u otros
        _log.warning("oferta rechazada (%s): %s", fields.get("url"), str(exc).replace("\n", " "))
        return None
    if expected_domains:
        host = (urlsplit(offer.url).hostname or "").lower()
        if not any(host == d or host.endswith("." + d) for d in expected_domains):
            _log.warning("oferta rechazada: dominio %s no esperado (%s)", host, sorted(expected_domains))
            return None
    return offer


class Search(BaseModel):
    id: str
    name: str
    tipos: list[str] = []
    areas: list[str] = []
    modalidades: list[Modality] = []
    ubicaciones: list[str] = []
    prioridad: Literal["alta", "normal"] = "alta"
    paused: bool = False


class Exclusions(BaseModel):
    words: list[str] = []
    companies: list[str] = []


class Decision(BaseModel):
    matched: list[str]
    priority: Literal["alta", "normal"] | None = None
    reasons: list[str]

    @property
    def ok(self) -> bool:
        return bool(self.matched)
