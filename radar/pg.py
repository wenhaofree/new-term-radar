"""PostgreSQL product store: daily report batches and keyword opportunities for the frontend.

Operational state (snapshots, 14-day review leads) stays in local SQLite under state/.
This module writes only what a product dashboard needs. Needs DATABASE_URL and psycopg.

Environment: DATABASE_URL=postgresql://user:pass@host:5432/radar
Without it, configured() is False and callers skip persistence.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
  id                BIGSERIAL PRIMARY KEY,
  run_date          DATE NOT NULL,
  started_at        TIMESTAMPTZ NOT NULL,
  finished_at       TIMESTAMPTZ,
  duration_seconds  INTEGER,
  status            TEXT NOT NULL DEFAULT 'running',
  cost_micros       BIGINT NOT NULL DEFAULT 0,
  signals_overview  JSONB NOT NULL DEFAULT '{}',
  report_md         TEXT,
  report_json       JSONB,
  errors            JSONB NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS reports_run_date_idx ON reports (run_date DESC);

CREATE TABLE IF NOT EXISTS keyword_opportunities (
  id                BIGSERIAL PRIMARY KEY,
  report_id         BIGINT REFERENCES reports(id) ON DELETE SET NULL,
  discovered_date   DATE NOT NULL,
  keyword           TEXT NOT NULL,
  kind              TEXT NOT NULL DEFAULT 'name',
  behind_names      TEXT[] NOT NULL DEFAULT '{}',
  format            TEXT,
  daily_volume      INTEGER,
  volume_band       TEXT NOT NULL DEFAULT 'unknown',
  trend_status      TEXT,
  started_rising    TEXT,
  momentum          DOUBLE PRECISION,
  kd                DOUBLE PRECISION,
  weak_sites_count  INTEGER,
  weak_sites        JSONB,
  best_market       TEXT,
  markets           JSONB,
  decision          TEXT,
  action            TEXT,
  is_acted          BOOLEAN NOT NULL DEFAULT FALSE,
  demoted           BOOLEAN NOT NULL DEFAULT FALSE,
  brand             BOOLEAN NOT NULL DEFAULT FALSE,
  source            TEXT,
  serp              JSONB,
  year              JSONB,
  age               JSONB,
  dot_com           JSONB,
  payload           JSONB NOT NULL DEFAULT '{}',
  UNIQUE (discovered_date, keyword, kind)
);

CREATE INDEX IF NOT EXISTS keyword_opportunities_date_idx ON keyword_opportunities (discovered_date DESC);
CREATE INDEX IF NOT EXISTS keyword_opportunities_decision_idx ON keyword_opportunities (decision);

CREATE TABLE IF NOT EXISTS discovered_leads (
  id                BIGSERIAL PRIMARY KEY,
  report_id         BIGINT REFERENCES reports(id) ON DELETE SET NULL,
  discovered_date   DATE NOT NULL,
  term              TEXT NOT NULL,
  format            TEXT,
  signals           JSONB NOT NULL DEFAULT '[]',
  name_score        DOUBLE PRECISION,
  examples          JSONB NOT NULL DEFAULT '[]',
  kinds             JSONB NOT NULL DEFAULT '[]',
  UNIQUE (discovered_date, term)
);

CREATE INDEX IF NOT EXISTS discovered_leads_date_idx ON discovered_leads (discovered_date DESC);

-- Free tier: exact daily_volume, weak_sites, kd, markets detail stay on the base table.
CREATE OR REPLACE VIEW v_keyword_opportunities_free AS
SELECT
  id, report_id, discovered_date, keyword, kind, behind_names, format,
  volume_band, trend_status, decision, action, is_acted, demoted, brand, source
FROM keyword_opportunities;
"""

def database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def configured() -> bool:
    return bool(database_url())


def connect():
    """Open a connection; raises if DATABASE_URL is missing or psycopg is not installed."""
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError('PostgreSQL needs psycopg: pip install "new-term-radar[pg]" or uv sync --extra pg') from exc
    conn = psycopg.connect(url)
    return conn


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()


def start_report(run_date: date | None = None, started_at: datetime | None = None) -> int | None:
    """Insert a running report row. Returns id, or None when Postgres is not configured."""
    if not configured():
        print("pg: DATABASE_URL not set; skipping product DB write", file=sys.stderr)
        return None
    day = run_date or date.today()
    started = started_at or datetime.now(timezone.utc)
    with connect() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reports (run_date, started_at, status) VALUES (%s, %s, 'running') RETURNING id",
                (day, started),
            )
            report_id = cur.fetchone()[0]
        conn.commit()
    return int(report_id)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def finish_report(
    report_id: int,
    *,
    status: str,
    duration_seconds: int,
    cost_micros: int,
    signals_overview: dict,
    report_md: str,
    report_json: dict,
    errors: list,
    opportunities: list[dict],
    leads: list[dict],
    finished_at: datetime | None = None,
) -> None:
    """Update the report row and upsert keyword opportunities + discovered leads."""
    finished = finished_at or datetime.now(timezone.utc)
    with connect() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE reports SET finished_at = %s, duration_seconds = %s, status = %s,
                   cost_micros = %s, signals_overview = %s::jsonb, report_md = %s,
                   report_json = %s::jsonb, errors = %s::jsonb WHERE id = %s""",
                (finished, duration_seconds, status, cost_micros, _json(signals_overview),
                 report_md, _json(report_json), _json(errors), report_id),
            )
            for row in opportunities:
                cur.execute(
                    """INSERT INTO keyword_opportunities (
                         report_id, discovered_date, keyword, kind, behind_names, format,
                         daily_volume, volume_band, trend_status, started_rising, momentum,
                         kd, weak_sites_count, weak_sites, best_market, markets,
                         decision, action, is_acted, demoted, brand, source,
                         serp, year, age, dot_com, payload
                       ) VALUES (
                         %(report_id)s, %(discovered_date)s, %(keyword)s, %(kind)s, %(behind_names)s, %(format)s,
                         %(daily_volume)s, %(volume_band)s, %(trend_status)s, %(started_rising)s, %(momentum)s,
                         %(kd)s, %(weak_sites_count)s, %(weak_sites)s::jsonb, %(best_market)s, %(markets)s::jsonb,
                         %(decision)s, %(action)s, %(is_acted)s, %(demoted)s, %(brand)s, %(source)s,
                         %(serp)s::jsonb, %(year)s::jsonb, %(age)s::jsonb, %(dot_com)s::jsonb, %(payload)s::jsonb
                       )
                       ON CONFLICT (discovered_date, keyword, kind) DO UPDATE SET
                         report_id = EXCLUDED.report_id,
                         behind_names = EXCLUDED.behind_names,
                         format = EXCLUDED.format,
                         daily_volume = EXCLUDED.daily_volume,
                         volume_band = EXCLUDED.volume_band,
                         trend_status = EXCLUDED.trend_status,
                         started_rising = EXCLUDED.started_rising,
                         momentum = EXCLUDED.momentum,
                         kd = EXCLUDED.kd,
                         weak_sites_count = EXCLUDED.weak_sites_count,
                         weak_sites = EXCLUDED.weak_sites,
                         best_market = EXCLUDED.best_market,
                         markets = EXCLUDED.markets,
                         decision = EXCLUDED.decision,
                         action = EXCLUDED.action,
                         demoted = EXCLUDED.demoted,
                         brand = EXCLUDED.brand,
                         source = EXCLUDED.source,
                         serp = EXCLUDED.serp,
                         year = EXCLUDED.year,
                         age = EXCLUDED.age,
                         dot_com = EXCLUDED.dot_com,
                         payload = EXCLUDED.payload""",
                    {**row, "report_id": report_id,
                     "weak_sites": _json(row.get("weak_sites")),
                     "markets": _json(row.get("markets")),
                     "serp": _json(row.get("serp")),
                     "year": _json(row.get("year")),
                     "age": _json(row.get("age")),
                     "dot_com": _json(row.get("dot_com")),
                     "payload": _json(row.get("payload") or {})},
                )
            for row in leads:
                cur.execute(
                    """INSERT INTO discovered_leads (
                         report_id, discovered_date, term, format, signals, name_score, examples, kinds
                       ) VALUES (
                         %(report_id)s, %(discovered_date)s, %(term)s, %(format)s,
                         %(signals)s::jsonb, %(name_score)s, %(examples)s::jsonb, %(kinds)s::jsonb
                       )
                       ON CONFLICT (discovered_date, term) DO UPDATE SET
                         report_id = EXCLUDED.report_id,
                         format = EXCLUDED.format,
                         signals = EXCLUDED.signals,
                         name_score = EXCLUDED.name_score,
                         examples = EXCLUDED.examples,
                         kinds = EXCLUDED.kinds""",
                    {**row, "report_id": report_id,
                     "signals": _json(row.get("signals") or []),
                     "examples": _json(row.get("examples") or []),
                     "kinds": _json(row.get("kinds") or [])},
                )
        conn.commit()


def save_daily_run(
    *,
    report_id: int | None,
    status: str,
    duration_seconds: int,
    cost_micros: int,
    signals_overview: dict,
    report_md: str,
    report_json: dict,
    errors: list,
    opportunities: list[dict],
    leads: list[dict],
    run_date: date | None = None,
) -> int | None:
    """Persist a finished daily run. Creates a report row when report_id is None and DB is configured."""
    if not configured():
        print("pg: DATABASE_URL not set; skipping product DB write", file=sys.stderr)
        return None
    rid = report_id
    if rid is None:
        rid = start_report(run_date=run_date)
    if rid is None:
        return None
    finish_report(
        rid,
        status=status,
        duration_seconds=duration_seconds,
        cost_micros=cost_micros,
        signals_overview=signals_overview,
        report_md=report_md,
        report_json=report_json,
        errors=errors,
        opportunities=opportunities,
        leads=leads,
    )
    return rid
