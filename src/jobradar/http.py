"""Cliente HTTP asíncrono con pausa por dominio, reintento en 5xx y aviso de bloqueo."""
from __future__ import annotations

import asyncio
import random
import time
from urllib.parse import urlsplit

import httpx

from .config import HttpSettings

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0.0.0 Safari/537.36")


class SourceBlocked(Exception):
    """La fuente nos bloquea (403/429): hay que parar, no insistir."""

    def __init__(self, domain: str, status: int):
        super().__init__(f"{domain} bloquea las peticiones (HTTP {status})")
        self.domain = domain
        self.status = status


class Http:
    def __init__(self, settings: HttpSettings | None = None, *,
                 transport: httpx.AsyncBaseTransport | None = None, backoff: float = 2.0):
        self.settings = settings or HttpSettings()
        self.backoff = backoff
        self._client = httpx.AsyncClient(
            headers={"User-Agent": _UA, "Accept-Language": "es-ES,es;q=0.9,en;q=0.7"},
            timeout=self.settings.timeout_seconds, follow_redirects=True, transport=transport)
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def __aenter__(self) -> "Http":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, **kw) -> httpx.Response:
        domain = urlsplit(url).hostname or ""
        lock = self._locks.setdefault(domain, asyncio.Lock())
        lo, hi = self.settings.delay_seconds
        async with lock:
            for attempt in (0, 1):
                wait = random.uniform(lo, hi) - (time.monotonic() - self._last.get(domain, -1e9))
                if wait > 0:
                    await asyncio.sleep(wait)
                resp = await self._client.request(method, url, **kw)
                self._last[domain] = time.monotonic()
                if resp.status_code in (403, 429):
                    raise SourceBlocked(domain, resp.status_code)
                if resp.status_code >= 500 and attempt == 0:
                    await asyncio.sleep(self.backoff)
                    continue
                resp.raise_for_status()
                return resp
        raise AssertionError("inalcanzable")

    async def get(self, url: str, **kw) -> httpx.Response:
        return await self._request("GET", url, **kw)

    async def post_json(self, url: str, json, **kw) -> httpx.Response:
        return await self._request("POST", url, json=json, **kw)
