import httpx
import pytest

from jobradar.config import HttpSettings
from jobradar.http import Http, SourceBlocked

FAST = HttpSettings(delay_seconds=[0, 0], timeout_seconds=5)


async def test_403_lanza_source_blocked():
    t = httpx.MockTransport(lambda r: httpx.Response(403))
    async with Http(FAST, transport=t) as http:
        with pytest.raises(SourceBlocked) as e:
            await http.get("https://example.com/x")
    assert e.value.domain == "example.com" and e.value.status == 403


async def test_5xx_reintenta_una_vez():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503 if len(calls) == 1 else 200, json={"ok": True})

    async with Http(FAST, transport=httpx.MockTransport(handler), backoff=0) as http:
        r = await http.post_json("https://example.com/api", {"a": 1})
    assert r.json() == {"ok": True} and len(calls) == 2


async def test_5xx_persistente_falla_tras_un_reintento():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500)

    async with Http(FAST, transport=httpx.MockTransport(handler), backoff=0) as http:
        with pytest.raises(httpx.HTTPStatusError):
            await http.get("https://example.com/x")
    assert len(calls) == 2


async def test_cabeceras_navegador():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(200)

    async with Http(FAST, transport=httpx.MockTransport(handler)) as http:
        await http.get("https://example.com/")
    assert "Mozilla" in seen["user-agent"] and seen["accept-language"].startswith("es-ES")
