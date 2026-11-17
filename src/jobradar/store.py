"""Persistencia SQLite: ofertas únicas (jobs), sus enlaces (postings) y estado de fuentes."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .dedup import SIMILARITY, job_key, similar
from .models import Decision, JobOffer
from .normalize import norm_company

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, title TEXT NOT NULL, company TEXT,
  company_norm TEXT NOT NULL DEFAULT '', location TEXT, modality TEXT, remote_region TEXT,
  category TEXT, first_seen TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  priority TEXT, reasons TEXT NOT NULL DEFAULT '[]', matched_searches TEXT NOT NULL DEFAULT '[]',
  notified_at TEXT, tg_message_id INTEGER, description TEXT
);
CREATE INDEX IF NOT EXISTS jobs_key ON jobs(key);
CREATE INDEX IF NOT EXISTS jobs_company ON jobs(company_norm);
CREATE TABLE IF NOT EXISTS postings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL REFERENCES jobs(id),
  source TEXT NOT NULL, url TEXT NOT NULL UNIQUE, posted_at TEXT, first_seen TEXT NOT NULL,
  raw_title TEXT, raw_company TEXT
);
CREATE INDEX IF NOT EXISTS postings_job ON postings(job_id);
CREATE TABLE IF NOT EXISTS seen_watch (
  url_or_hash TEXT NOT NULL, source TEXT NOT NULL, first_seen TEXT NOT NULL,
  PRIMARY KEY (source, url_or_hash)
);
CREATE TABLE IF NOT EXISTS source_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, ts TEXT NOT NULL, ok INTEGER NOT NULL,
  count INTEGER NOT NULL, filled_pct REAL, error TEXT
);
"""


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


@dataclass
class Posting:
    id: int
    job_id: int
    source: str
    url: str
    posted_at: datetime | None
    first_seen: datetime
    raw_title: str | None = None
    raw_company: str | None = None


@dataclass
class Job:
    id: int
    key: str
    title: str
    company: str | None
    company_norm: str
    location: str | None
    modality: str | None
    remote_region: str | None
    category: str | None
    first_seen: datetime
    status: str
    priority: str | None
    reasons: list[str] = field(default_factory=list)
    matched_searches: list[str] = field(default_factory=list)
    notified_at: datetime | None = None
    tg_message_id: int | None = None
    description: str | None = None
    # Primer enlace del job; lo usa offer_view().
    first_posting: Posting | None = field(default=None, repr=False, compare=False)

    def offer_view(self) -> JobOffer:
        """Oferta reconstruida (con su primer enlace) para re-evaluar los filtros."""
        p = self.first_posting
        return JobOffer.model_construct(
            title=self.title, url=p.url if p else "", source=p.source if p else "",
            company=self.company, location=self.location, modality=self.modality,
            remote_region=self.remote_region, posted_at=p.posted_at if p else None,
            category=self.category, description=self.description,
        )


@dataclass
class UpsertResult:
    new_jobs: list[Job] = field(default_factory=list)
    new_postings: list[tuple[Job, Posting]] = field(default_factory=list)


class Store:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        if "description" not in {r["name"] for r in self.db.execute("PRAGMA table_info(jobs)")}:
            self.db.execute("ALTER TABLE jobs ADD COLUMN description TEXT")  # bases de datos antiguas

    def close(self) -> None:
        self.db.close()

    # --- conversión de filas ---
    def _job(self, row: sqlite3.Row) -> Job:
        job = Job(
            id=row["id"], key=row["key"], title=row["title"], company=row["company"],
            company_norm=row["company_norm"], location=row["location"], modality=row["modality"],
            remote_region=row["remote_region"], category=row["category"],
            first_seen=_parse(row["first_seen"]), status=row["status"], priority=row["priority"],
            reasons=json.loads(row["reasons"]), matched_searches=json.loads(row["matched_searches"]),
            notified_at=_parse(row["notified_at"]), tg_message_id=row["tg_message_id"],
            description=row["description"],
        )
        job.first_posting = (self.postings(job.id) or [None])[0]
        return job

    @staticmethod
    def _posting(row: sqlite3.Row) -> Posting:
        return Posting(row["id"], row["job_id"], row["source"], row["url"], _parse(row["posted_at"]),
                       _parse(row["first_seen"]), row["raw_title"], row["raw_company"])

    # --- escritura ---
    def _find_job(self, offer: JobOffer, key: str, cnorm: str, now: datetime) -> int | None:
        if not cnorm:
            return None  # sin empresa nunca se fusiona
        row = self.db.execute("SELECT id FROM jobs WHERE key=? ORDER BY id LIMIT 1", (key,)).fetchone()
        if row:
            return row["id"]
        since = _iso(now - timedelta(days=30))
        best, best_id = 0.0, None
        for r in self.db.execute(
                "SELECT id, title FROM jobs WHERE company_norm=? AND first_seen>=?", (cnorm, since)):
            ratio = similar(offer.title, r["title"])
            if ratio >= SIMILARITY and ratio > best:
                best, best_id = ratio, r["id"]
        return best_id

    def upsert(self, offers: list[JobOffer], now: datetime) -> UpsertResult:
        res = UpsertResult()
        created: set[int] = set()
        with self.db:
            for o in offers:
                if self.db.execute("SELECT 1 FROM postings WHERE url=?", (o.url,)).fetchone():
                    continue
                cnorm = norm_company(o.company)
                key = job_key(o.title, o.company)
                job_id = self._find_job(o, key, cnorm, now)
                is_new = job_id is None
                if is_new:
                    cur = self.db.execute(
                        "INSERT INTO jobs (key,title,company,company_norm,location,modality,"
                        "remote_region,category,first_seen,description) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (key, o.title, o.company, cnorm, o.location, o.modality, o.remote_region,
                         o.category, _iso(now), o.description))
                    job_id = cur.lastrowid
                    created.add(job_id)
                cur = self.db.execute(
                    "INSERT INTO postings (job_id,source,url,posted_at,first_seen,raw_title,raw_company)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (job_id, o.source, o.url, _iso(o.posted_at), _iso(now), o.title, o.company))
                job = self.get_job(job_id)
                if is_new:
                    res.new_jobs.append(job)
                elif job_id not in created:
                    posting = self._posting(self.db.execute(
                        "SELECT * FROM postings WHERE id=?", (cur.lastrowid,)).fetchone())
                    res.new_postings.append((job, posting))
        return res

    def set_decision(self, job_id: int, decision: Decision) -> None:
        with self.db:
            self.db.execute(
                "UPDATE jobs SET status=?, priority=?, reasons=?, matched_searches=? WHERE id=?",
                ("avisada" if decision.ok else "descartada", decision.priority,
                 json.dumps(decision.reasons, ensure_ascii=False),
                 json.dumps(decision.matched, ensure_ascii=False), job_id))

    def set_description(self, job_id: int, description: str | None) -> None:
        with self.db:
            self.db.execute("UPDATE jobs SET description=? WHERE id=?", (description, job_id))

    def mark_notified(self, job_id: int, tg_message_id: int | None, now: datetime) -> None:
        with self.db:
            self.db.execute("UPDATE jobs SET notified_at=?, tg_message_id=? WHERE id=?",
                            (_iso(now), tg_message_id, job_id))

    def record_run(self, source: str, now: datetime, ok: bool, count: int,
                   filled_pct: float | None = None, error: str | None = None) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO source_runs (source,ts,ok,count,filled_pct,error) VALUES (?,?,?,?,?,?)",
                (source, _iso(now), int(ok), count, filled_pct, error))

    def watch_is_new(self, source: str, key: str, now: datetime) -> bool:
        with self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO seen_watch (url_or_hash,source,first_seen) VALUES (?,?,?)",
                (key, source, _iso(now)))
        return cur.rowcount == 1

    # --- lectura ---
    def get_job(self, job_id: int) -> Job | None:
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def postings(self, job_id: int) -> list[Posting]:
        return [self._posting(r) for r in self.db.execute(
            "SELECT * FROM postings WHERE job_id=? ORDER BY id", (job_id,))]

    def _jobs_since(self, since: datetime, status: str | None) -> list[Job]:
        sql, args = "SELECT * FROM jobs WHERE first_seen>=?", [_iso(since)]
        if status:
            sql, args = sql + " AND status=?", args + [status]
        return [self._job(r) for r in self.db.execute(sql + " ORDER BY first_seen DESC, id DESC", args)]

    def recent(self, days: int, now: datetime, status: str | None = None) -> list[Job]:
        return self._jobs_since(now - timedelta(days=days), status)

    def discarded(self, hours: int, now: datetime) -> list[Job]:
        return self._jobs_since(now - timedelta(hours=hours), "descartada")

    def jobs_since(self, days: int, now: datetime) -> list[Job]:
        return self._jobs_since(now - timedelta(days=days), None)

    def last_runs(self, source: str, n: int = 5) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM source_runs WHERE source=? ORDER BY id DESC LIMIT ?", (source, n))
        return [dict(r) | {"ok": bool(r["ok"])} for r in rows]

    def pending_digest(self) -> list[Job]:
        """Ofertas que encajan y aún no se han avisado (para el resumen diario)."""
        rows = self.db.execute(
            "SELECT * FROM jobs WHERE status='avisada' AND notified_at IS NULL ORDER BY first_seen, id")
        return [self._job(r) for r in rows]
