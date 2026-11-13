"""Unit tests for PostgreSQL row mapping and skip-when-unset persistence."""
from __future__ import annotations

from datetime import date

import pytest

from radar import notify, persist, pg, preflight


def test_volume_band():
    assert persist.volume_band(None) == "unknown"
    assert persist.volume_band(50) == "<100"
    assert persist.volume_band(100) == "100-1k"
    assert persist.volume_band(1000) == "100-1k"
    assert persist.volume_band(1001) == ">1k"
    assert persist.volume_band("bad") == "unknown"


def test_opportunity_row_maps_competition_and_markets():
    row = {
        "phrase": "ai headshot",
        "kind": "generic",
        "names": ["photocraft"],
        "per_day": 420,
        "now": "rising",
        "started": "2026-10-01",
        "momentum": 2.5,
        "decision": "prioritize",
        "brand": False,
        "source": "searched",
        "demoted": False,
        "competition": {
            "kd": 18,
            "weak": 4,
            "results": [
                {"domain": "a.com", "url": "https://a.com", "title": "A", "position": 1, "kind": "tool", "dr": 12},
                {"domain": "b.com", "url": "https://b.com", "title": "B", "position": 2, "kind": "tool", "dr": 55},
            ],
        },
        "markets": {"by": {"US": {"volume": 1000, "kd": 20}}, "best": "US", "top_region": "US"},
        "yours": {"action": "new"},
    }
    out = persist.opportunity_row(row, date(2026, 11, 13))
    assert out["keyword"] == "ai headshot"
    assert out["kind"] == "generic"
    assert out["behind_names"] == ["photocraft"]
    assert out["daily_volume"] == 420
    assert out["volume_band"] == "100-1k"
    assert out["trend_status"] == "rising"
    assert out["kd"] == 18
    assert out["weak_sites_count"] == 4
    assert out["weak_sites"][0]["domain"] == "a.com"
    assert out["best_market"] == "US"
    assert out["action"] == "new"
    assert out["decision"] == "prioritize"
    assert out["discovered_date"] == "2026-11-13"
    assert out["payload"]["phrase"] == "ai headshot"


def test_opportunities_from_usecases_skips_errors():
    assert persist.opportunities_from_usecases({"error": "boom"}) == []
    assert persist.opportunities_from_usecases({"skipped": True}) == []
    rows = persist.opportunities_from_usecases({
        "rows": [{"phrase": "strata", "kind": "name", "names": [], "per_day": 2000, "now": "holding", "decision": "watch"}],
    })
    assert len(rows) == 1 and rows[0]["volume_band"] == ">1k"


def test_lead_row_includes_format():
    lead = {
        "term": "seedance",
        "kinds": ["x"],
        "signals": ["X 2 accounts"],
        "examples": ["a video model demo"],
        "named": 0.9,
        "posts": [],
    }
    out = persist.lead_row(lead, date(2026, 11, 13))
    assert out["term"] == "seedance"
    assert out["format"] == "video"
    assert out["name_score"] == 0.9


def test_collect_errors_and_status():
    errors = persist.collect_errors(
        {"x": {"error": "HTTP 401"}},
        {"usecases": {"country_errors": ["a: 401"], "posts_error": "timeout"}},
        more=["postgres: down"],
    )
    assert any("x:" in e for e in errors)
    assert any("country_errors" in e for e in errors)
    assert any("postgres" in e for e in errors)
    assert persist.run_status([], [{"k": 1}], []) == "success"
    assert persist.run_status(errors, [{"k": 1}], []) == "partial"
    assert persist.run_status(errors, [], []) == "failed"


def test_pg_configured_false_without_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert pg.configured() is False
    assert pg.start_report() is None
    assert pg.save_daily_run(
        report_id=None, status="success", duration_seconds=1, cost_micros=0,
        signals_overview={}, report_md="", report_json={}, errors=[],
        opportunities=[], leads=[],
    ) is None


def test_preflight_skip_network_requires_aisa(monkeypatch):
    monkeypatch.setattr(preflight.aisa, "has_key", lambda: False)
    r = preflight.run(skip_network=True)
    assert r.ok is False and r.failures[0].name == "aisa"


def test_preflight_skip_network_ok(monkeypatch):
    monkeypatch.setattr(preflight.aisa, "has_key", lambda: True)
    monkeypatch.delenv("TRUSTMRR_API_KEY", raising=False)
    r = preflight.run(skip_network=True, need_revenue=False)
    assert r.ok is True


def test_notify_webhook_payload_feishu():
    body = notify._payload("feishu", "title", "hello")
    assert body["msg_type"] == "post"
    assert "hello" in str(body)


def test_notify_alert_skipped_without_url(monkeypatch):
    monkeypatch.delenv("RADAR_WEBHOOK_URL", raising=False)
    assert "skipped" in notify.alert("t", "m")
