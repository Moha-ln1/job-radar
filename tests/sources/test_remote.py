"""Contrato de las fuentes de empleo remoto: fixtures reales recortados (2026-11-16), campo a campo."""
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from jobradar.config import HttpSettings, Settings
from jobradar.http import Http
from jobradar.sources import SourceContext, remote

FIX = Path(__file__).parent / "fixtures"
UTC = timezone.utc


def _json(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _by_url(offers, url):
    return next(o for o in offers if o.url == url)


def test_remotive():
    offers = remote._parse_remotive(_json("remotive.json"))
    o = _by_url(offers, "https://remotive.com/remote-jobs/marketing/content-creator-youtube-2091173")
    assert (o.title, o.company, o.source) == ("Content Creator - YouTube", "Metics Media", "remotive")
    assert (o.modality, o.remote_region, o.location) == ("remoto", "USA, Canada", None)
    assert o.category == "Marketing"
    assert o.posted_at == datetime(2026, 11, 13, 17, 29, 57, tzinfo=UTC)


def test_remoteok_salta_el_aviso_legal():
    data = _json("remoteok.json")
    assert "legal" in data[0]
    offers = remote._parse_remoteok(data)
    assert len(offers) == len(data) - 1
    o = _by_url(offers, "https://remoteOK.com/remote-jobs/remote-global-partnerships-bd-lead-fuku-1137796")
    assert (o.title, o.company, o.source) == ("Global Partnerships BD Lead", "Fuku", "remoteok")
    assert (o.modality, o.remote_region) == ("remoto", "Paris")
    assert o.posted_at == datetime(2026, 11, 13, 8, 0, 21, tzinfo=UTC)


def test_weworkremotely_separa_empresa_y_puesto():
    offers = remote._parse_weworkremotely((FIX / "weworkremotely.rss").read_bytes())
    o = _by_url(offers, "https://weworkremotely.com/remote-jobs/felyri-consulting-limited-research-consultant")
    assert (o.title, o.company, o.source) == ("Research Consultant", "FELYRI CONSULTING LIMITED", "weworkremotely")
    assert (o.modality, o.remote_region) == ("remoto", "Anywhere in the World")
    assert o.category == "All Other Remote"
    assert o.posted_at == datetime(2026, 11, 16, 2, 47, 54, tzinfo=UTC)


def test_himalayas():
    offers = remote._parse_himalayas(_json("himalayas.json"))
    o = _by_url(offers, "https://himalayas.app/companies/trend-micro/jobs/senior-manager-of-compliance")
    assert (o.title, o.company, o.source) == ("Senior Manager of Compliance", "Trend Micro", "himalayas")
    assert (o.modality, o.remote_region, o.category) == ("remoto", "United States", "Legal")
    assert o.posted_at == datetime(2026, 11, 16, 1, 37, 8, tzinfo=UTC)


def test_arbeitnow():
    offers = remote._parse_arbeitnow(_json("arbeitnow.json"))
    o = _by_url(offers, "https://www.arbeitnow.com/jobs/companies/agilerobotsse/"
                        "senior-mechanical-engineer-robotic-systems-munich-bavaria-66135")
    assert (o.title, o.company, o.source) == (
        "Senior Mechanical Engineer - Robotic Systems", "Agilerobotsse", "arbeitnow")
    assert (o.location, o.modality, o.remote_region) == ("Munich, Bavaria", None, None)
    assert o.posted_at == datetime(2026, 11, 16, 0, 55, 24, tzinfo=UTC)
    rem = next(x for x in offers if x.modality == "remoto")
    assert (rem.location, rem.remote_region) == (None, "Remote")


async def test_remotive_dedup_por_url_y_max_3_terminos():
    queries = []

    def handler(req: httpx.Request) -> httpx.Response:
        queries.append(req.url.params["search"])
        return httpx.Response(200, json=_json("remotive.json"))

    http = Http(HttpSettings(delay_seconds=[0, 0]), transport=httpx.MockTransport(handler), backoff=0)
    ctx = SourceContext(http=http, settings=Settings(), terms=["a", "b", "c", "d"])
    async with http:
        offers = await remote.fetch_remotive(ctx)
    assert queries == ["a", "b", "c"]
    assert len(offers) == 3
