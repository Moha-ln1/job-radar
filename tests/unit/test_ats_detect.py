import asyncio

import pytest

from jobradar.ats_detect import detect, detect_url


@pytest.mark.parametrize("url,ats,slug", [
    ("https://boards.greenhouse.io/gitlab", "greenhouse", "gitlab"),
    ("https://job-boards.greenhouse.io/acme/jobs/123", "greenhouse", "acme"),
    ("https://boards.greenhouse.io/embed/job_board?for=bigco", "greenhouse", "bigco"),
    ("https://jobs.lever.co/netflix/abc-123", "lever", "netflix"),
    ("https://jobs.ashbyhq.com/ramp", "ashby", "ramp"),
    ("https://jobs.smartrecruiters.com/BoschGroup/123-dev", "smartrecruiters", "BoschGroup"),
    ("https://careers.smartrecruiters.com/Visa", "smartrecruiters", "Visa"),
    ("https://accenture.wd103.myworkdayjobs.com/en-US/AccentureCareers", "workday", "accenture.wd103/AccentureCareers"),
    ("https://acme.wd5.myworkdayjobs.com/Jobs/job/x", "workday", "acme.wd5/Jobs"),
    ("https://foo.recruitee.com/o/dev", "recruitee", "foo"),
    ("https://foo-bar.jobs.personio.de/job/1", "personio", "foo-bar"),
    ("https://foo.jobs.personio.com", "personio", "foo"),
    ("https://foo.teamtailor.com/jobs", "teamtailor", "foo"),
])
def test_detect_by_url(url, ats, slug):
    r = detect(url)
    assert r and r["ats"] == ats and r["slug"] == slug and r["name"]


@pytest.mark.parametrize("html,ats,slug", [
    ('<a href="https://jobs.lever.co/acme">Empleo</a>', "lever", "acme"),
    ('<iframe src="https://boards.greenhouse.io/embed/job_board?for=acme&amp;b=x"></iframe>', "greenhouse", "acme"),
    ('<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme2"></script>', "greenhouse", "acme2"),
    ("<script>var u = 'https:\\/\\/jobs.ashbyhq.com\\/ramp';</script>", "ashby", "ramp"),
    ('<a href="//zeta.recruitee.com/">x</a>', "recruitee", "zeta"),
])
def test_detect_by_html(html, ats, slug):
    r = detect(html)
    assert r and r["ats"] == ats and r["slug"] == slug


@pytest.mark.parametrize("text", ["", "https://example.com/careers", "<a href='https://example.com'>x</a>",
                                  "https://www.recruitee.com/", "https://boards.greenhouse.io/embed/job_board/js"])
def test_detect_none(text):
    assert detect(text) is None


class FakeHttp:
    def __init__(self, html):
        self.html, self.calls = html, 0

    async def get(self, url):
        self.calls += 1
        return type("R", (), {"text": self.html})()


def test_detect_url_skips_download_when_url_reveals_ats():
    http = FakeHttp("")
    assert asyncio.run(detect_url(http, "https://jobs.lever.co/acme"))["slug"] == "acme"
    assert http.calls == 0


def test_detect_url_downloads_page():
    http = FakeHttp('<a href="https://jobs.lever.co/acme">x</a>')
    assert asyncio.run(detect_url(http, "https://acme.com/careers"))["ats"] == "lever"
    assert http.calls == 1
