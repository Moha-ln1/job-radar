import json

import httpx

from jobradar.config import HttpSettings, save_searches
from jobradar.http import Http
from jobradar.models import Exclusions, JobOffer
from jobradar.paths import Paths
from jobradar.verify import format_table, verify


def ld(title, company="Acme", wrap=True):
    post = {"@type": "JobPosting", "title": title, "hiringOrganization": {"name": company}}
    data = {"@graph": [{"@type": "WebPage"}, post]} if wrap else [post]
    return f'<html><script type="application/ld+json">{json.dumps(data)}</script></html>'


def offers(*titles):
    return [JobOffer(title=t, url=f"https://a.com/{i}", source="s", company="Acme")
            for i, t in enumerate(titles)]


async def run(tmp_path, pages, fetched):
    (tmp_path / "config.yaml").write_text("sources:\n  s: {enabled: true}\n", encoding="utf-8")
    save_searches(tmp_path / "busquedas.yaml", [], Exclusions())

    async def fetch(ctx):
        return fetched

    def handler(req):
        page = pages.get(req.url.path)
        return httpx.Response(200, text=page) if page is not None else httpx.Response(404)

    http = Http(HttpSettings(delay_seconds=[0, 0]), transport=httpx.MockTransport(handler))
    async with http:
        return await verify(Paths(tmp_path), 3, fetchers={"s": fetch}, http=http)


async def test_titulo_igual_ok_y_diferente_falla(tmp_path):
    rows = await run(tmp_path, {"/0": ld("Becario Data"), "/1": ld("Director Financiero", wrap=False)},
                     offers("Becario Data", "Becario Python"))
    row = rows[0]
    assert row.count == 2 and row.checked == 2 and not row.ok
    assert len(row.mismatches) == 1 and "DIFERENTE" in row.mismatches[0]
    assert "FALLO" in format_table(rows)


async def test_sin_jsonld_y_error_http(tmp_path):
    pages = {"/0": "<html><title>Becario Data - Acme</title></html>", "/1": "<html><p>nada</p></html>"}
    rows = await run(tmp_path, pages, offers("Becario Data", "Becario Python", "Otro"))
    row = rows[0]
    assert any("SIN_DATOS" in m for m in row.mismatches)
    assert any("ERROR HTTP" in m for m in row.mismatches)
    assert not row.ok


async def test_todo_ok(tmp_path):
    rows = await run(tmp_path, {"/0": ld("Becario Data")}, offers("Becario Data"))
    assert rows[0].ok and rows[0].mismatches == [] and "OK" in format_table(rows)


async def test_api_sin_clave_no_es_fallo(tmp_path):
    (tmp_path / "config.yaml").write_text("sources:\n  jooble: {enabled: true}\n", encoding="utf-8")
    save_searches(tmp_path / "busquedas.yaml", [], Exclusions())

    async def fetch(ctx):
        return []
    http = Http(HttpSettings(delay_seconds=[0, 0]), transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    async with http:
        rows = await verify(Paths(tmp_path), 3, fetchers={"jooble": fetch}, http=http)
    assert rows[0].ok and "SIN_CLAVE" in rows[0].mismatches[0]


def test_detalle_con_prefijos_hiring_coincide():
    from jobradar.verify import _titles_match
    assert _titles_match("Content Creator - YouTube", "[Hiring] Content Creator - YouTube @Metics Media", 0.9)
    assert not _titles_match("Content Creator", "Senior Backend Engineer", 0.9)


def test_muro_antibot_no_cuenta_como_diferente():
    from jobradar.models import build_offer
    from jobradar.verify import _compare
    offer = build_offer(title="Prácticas Finanzas", url="https://www.infojobs.net/x/of-i1", source="infojobs")
    msg = _compare(offer, "<html><title>InfoJobs</title><body>No podemos identificar tu navegador</body></html>")
    assert msg.startswith("DETALLE_BLOQUEADO")
