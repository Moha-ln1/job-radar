"""Detecta qué ATS usa una web de empleo (por URL o por el HTML) para añadirla a `companies:`."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlsplit

_RESERVED = {"www", "api", "boards", "jobs", "careers", "embed", "static", "cdn"}
_LANG = re.compile(r"[a-z]{2}([-_][A-Za-z]{2})?")


def _pretty(slug: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_.]+", slug) if w) or slug


def _found(ats: str, slug: str, name: str | None = None) -> dict:
    return {"name": name or _pretty(slug), "ats": ats, "slug": slug}


def _from_url(url: str) -> dict | None:
    url = unquote(url.strip().replace("\\/", "/"))
    if not re.match(r"^[a-z]+://", url, re.I):
        url = "https://" + url
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    segs = [s for s in parts.path.split("/") if s]
    query = parse_qs(parts.query)

    if host.endswith("greenhouse.io"):
        if query.get("for"):
            return _found("greenhouse", query["for"][0])
        if host.startswith(("boards.", "job-boards.", "boards.eu.", "job-boards.eu.")) \
                and segs and segs[0] not in ("embed", "v1"):
            return _found("greenhouse", segs[0])
        return None
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and segs:
        return _found("lever", segs[0])
    if host == "jobs.ashbyhq.com" and segs:
        return _found("ashby", segs[0])
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com") and segs:
        return _found("smartrecruiters", segs[0])
    if host.endswith(".myworkdayjobs.com"):
        labels = host.split(".")
        if len(labels) >= 4 and re.fullmatch(r"wd\d+", labels[1]):
            site = [s for s in segs if not _LANG.fullmatch(s)]
            if site:
                return _found("workday", f"{labels[0]}.{labels[1]}/{site[0]}", _pretty(labels[0]))
        return None
    for pattern, ats in ((r"([a-z0-9-]+)\.recruitee\.com", "recruitee"),
                         (r"([a-z0-9-]+)\.jobs\.personio\.(?:de|com)", "personio"),
                         (r"([a-z0-9-]+)\.teamtailor\.com", "teamtailor")):
        m = re.fullmatch(pattern, host)
        if m and m.group(1) not in _RESERVED:
            return _found(ats, m.group(1))
    return None


_CHARS = r"[A-Za-z0-9._~:/?#@$&*+,;=%\\-]"
_URL_IN_HTML = re.compile(
    r"(?:https?:)?//" + _CHARS + r"*?(?:greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|"
    r"myworkdayjobs\.com|recruitee\.com|personio\.(?:de|com)|teamtailor\.com)" + _CHARS + "*", re.I)


def detect(url_or_html: str) -> dict | None:
    """Devuelve {name, ats, slug} o None. Acepta una URL o un fragmento/página HTML."""
    text = (url_or_html or "").strip().replace("\\/", "/").replace("&amp;", "&")
    if not text:
        return None
    if "<" not in text and not re.search(r"\s", text):
        return _from_url(text)
    for m in _URL_IN_HTML.finditer(text):
        raw = m.group(0)
        found = _from_url("https:" + raw if raw.startswith("//") else raw)
        if found:
            return found
    return None


async def detect_url(http, url: str) -> dict | None:
    """Si la URL ya revela el ATS lo devuelve; si no, descarga la página y busca en su HTML."""
    found = _from_url(url)
    if found:
        return found
    resp = await http.get(url)
    return detect(resp.text)
