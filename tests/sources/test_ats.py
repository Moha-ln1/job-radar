"""Contrato de las fuentes ATS: fixtures reales recortados (capturados el 2026-11-16) y comprobación campo a campo."""
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from jobradar.config import HttpSettings, Settings
from jobradar.http import Http, SourceBlocked
from jobradar.sources import SourceContext, ats

FIX = Path(__file__).parent / "fixtures"
UTC = timezone.utc


def _json(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _by_url(offers, url):
    return next(o for o in offers if o.url == url)


def test_greenhouse():
    offers = ats._parse_greenhouse(_json("greenhouse_gitlab.json"), "GitLab", "gitlab")
    o = _by_url(offers, "https://job-boards.greenhouse.io/gitlab/jobs/8638232002")
    assert (o.title, o.company, o.source) == ("AI Transformation Owner, CRO", "GitLab", "greenhouse:gitlab")
    assert o.location == "Remote, United States"
    assert o.category == "Enablement"
    assert o.modality is None
    assert o.posted_at == datetime(2026, 7, 22, 17, 38, 40, tzinfo=UTC)
    assert len(offers) == 3


def test_lever():
    offers = ats._parse_lever(_json("lever_palantir.json"), "Palantir", "palantir")
    o = _by_url(offers, "https://jobs.lever.co/palantir/6ed76ce8-4156-4b60-b120-403538bd66cd")
    assert (o.title, o.company, o.source) == ("Administrative Business Partner", "Palantir", "lever:palantir")
    assert o.location == "Singapore, Singapore"
    assert o.modality == "hibrido"
    assert o.category == "Administrative"
    assert o.posted_at == datetime(2026, 8, 11, 17, 38, 11, 368000, tzinfo=UTC)
    assert _by_url(offers, "https://jobs.lever.co/palantir/ac978161-6f46-4f6b-ad9e-a258e642751c").modality == "presencial"
    assert _by_url(offers, "https://jobs.lever.co/palantir/0ccbe620-a3ef-41d1-a5c4-68e56b3c91d0").modality == "remoto"


def test_ashby():
    offers = ats._parse_ashby(_json("ashby_ramp.json"), "Ramp", "ramp")
    o = _by_url(offers, "https://jobs.ashbyhq.com/ramp/34413f8d-26bf-4bbc-8ade-eb309a0e2245")
    assert (o.title, o.company, o.source) == ("Software Engineer, Security, Cloud", "Ramp", "ashby:ramp")
    assert o.location == "New York, NY (HQ)"
    assert o.modality == "hibrido"  # workplaceType manda sobre isRemote
    assert o.category == "Engineering"
    assert o.posted_at == datetime(2026, 4, 7, 17, 12, 35, 753000, tzinfo=UTC)


def test_smartrecruiters():
    offers = ats._parse_smartrecruiters(_json("smartrecruiters_bosch.json"), "Bosch", "BoschGroup")
    o = _by_url(offers, "https://jobs.smartrecruiters.com/BoschGroup/744000160852229")
    assert o.title == "People & Talent Intern (International Recruitment) – May 2027"
    assert (o.company, o.source) == ("Bosch", "smartrecruiters:BoschGroup")
    assert o.location == "Barcelona, CT, Spain"
    assert o.modality == "hibrido"
    assert o.posted_at == datetime(2026, 11, 10, 11, 22, 21, 771000, tzinfo=UTC)


def test_workday():
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    offers = ats._parse_workday(_json("workday_accenture.json"), "Accenture",
                                "accenture.wd103.myworkdayjobs.com", "accenture", "AccentureCareers", now=now)
    o = _by_url(offers, "https://accenture.wd103.myworkdayjobs.com/AccentureCareers/job/Madrid/"
                        "MICROSOFT-365-Banking-Operations-New-Associate-ETT_14904269")
    assert o.title == "MICROSOFT 365-Banking Operations New Associate-ETT"
    assert (o.company, o.source) == ("Accenture", "workday:accenture")
    assert o.location == "Madrid"
    assert o.posted_at == datetime(2026, 11, 14, tzinfo=UTC)
    assert offers[2].posted_at is None  # "30+ Days Ago" no es una fecha


def test_workday_posted_on():
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    assert ats._workday_posted("Posted Today", now) == datetime(2026, 11, 16, tzinfo=UTC)
    assert ats._workday_posted("Posted Yesterday", now) == datetime(2026, 11, 15, tzinfo=UTC)
    assert ats._workday_posted("Posted 30+ Days Ago", now) is None
    assert ats._workday_posted("Publicado hace 13 días", now) == datetime(2026, 11, 3, tzinfo=UTC)
    assert ats._workday_posted("Publicado hace más de 30 días", now) is None
    assert ats._workday_posted(None, now) is None


def test_recruitee():
    offers = ats._parse_recruitee(_json("recruitee_bunq.json"), "bunq", "bunq")
    o = _by_url(offers, "https://careers.bunq.com/o/security-engineer-3")
    assert (o.title, o.company, o.source) == ("Security Engineer", "bunq", "recruitee:bunq")
    assert o.location == "Amsterdam, Noord-Holland, Netherlands"
    assert o.modality == "hibrido"
    assert o.category == "Technology"
    assert o.posted_at == datetime(2026, 11, 11, 13, 21, 40, tzinfo=UTC)
    assert _by_url(offers, "https://careers.bunq.com/o/reporting-agent-france-3").modality == "remoto"


def test_personio():
    offers = ats._parse_personio((FIX / "personio_personio.xml").read_bytes(), "Personio", "personio")
    o = _by_url(offers, "https://personio.jobs.personio.de/job/2885178")
    assert (o.title, o.company, o.source) == (
        "Business Development Representative (d/f/m)", "Personio", "personio:personio")
    assert o.location == "Berlin"
    assert o.category == "Go to Market"
    assert o.posted_at == datetime(2026, 11, 11, 17, 43, 42, tzinfo=UTC)


def test_teamtailor():
    offers = ats._parse_teamtailor((FIX / "teamtailor_career.rss").read_bytes(), "Teamtailor", "career")
    o = _by_url(offers, "https://career.teamtailor.com/jobs/8742767-customer-success-manager-french-speaking")
    assert (o.title, o.company, o.source) == (
        "Customer Success Manager - French Speaking", "Teamtailor", "teamtailor:career")
    assert o.location == "Stockholm, Sweden / Barcelona, Spain"
    assert o.modality == "hibrido"
    assert o.category == "Customer Success"
    assert o.posted_at == datetime(2026, 11, 13, 14, 0, 10, tzinfo=UTC)


# --- fetch_ats: despacho y aislamiento de errores -----------------------------------------------------------

def _ctx(handler, companies):
    http = Http(HttpSettings(delay_seconds=[0, 0]), transport=httpx.MockTransport(handler), backoff=0)
    return SourceContext(http=http, settings=Settings(companies=companies), terms=["intern"])


async def test_fetch_ats_continua_si_una_empresa_falla():
    def handler(req: httpx.Request) -> httpx.Response:
        if "boards-api.greenhouse.io" in req.url.host:
            return httpx.Response(404)
        return httpx.Response(200, json=_json("lever_palantir.json"))

    ctx = _ctx(handler, [
        {"name": "Rota", "ats": "greenhouse", "slug": "nope"},
        {"name": "Palantir", "ats": "lever", "slug": "palantir"},
        {"name": "Otra", "ats": "desconocido", "slug": "x"},
    ])
    async with ctx.http:
        offers = await ats.fetch_ats(ctx)
    assert len(offers) == 3 and {o.company for o in offers} == {"Palantir"}


async def test_fetch_ats_propaga_bloqueo():
    ctx = _ctx(lambda req: httpx.Response(429), [{"name": "X", "ats": "lever", "slug": "x"}])
    async with ctx.http:
        with pytest.raises(SourceBlocked):
            await ats.fetch_ats(ctx)


async def test_fetch_workday_post_y_dedup_por_url():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((str(req.url), json.loads(req.content)["searchText"]))
        return httpx.Response(200, json=_json("workday_accenture.json"))

    ctx = _ctx(handler, [{"name": "Accenture", "ats": "workday", "slug": "accenture.wd103/AccentureCareers"}])
    ctx.terms = ["intern", "junior"]
    async with ctx.http:
        offers = await ats.fetch_ats(ctx)
    url = "https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs"
    assert seen == [(url, "intern Spain"), (url, "junior Spain")]
    assert len(offers) == 3  # mismas URLs en ambos términos


async def test_fetch_smartrecruiters_pagina():
    pages = []

    def handler(req: httpx.Request) -> httpx.Response:
        pages.append(req.url.params["offset"])
        data = _json("smartrecruiters_bosch.json")
        data["totalFound"] = 150
        return httpx.Response(200, json=data)

    ctx = _ctx(handler, [{"name": "Bosch", "ats": "smartrecruiters", "slug": "BoschGroup"}])
    async with ctx.http:
        await ats.fetch_ats(ctx)
    assert pages == ["0", "100"]
