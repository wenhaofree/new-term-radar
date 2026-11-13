"""Map in-memory daily results to PostgreSQL row dicts (no DB I/O)."""
from __future__ import annotations

from datetime import date
from typing import Any

from . import opportunity


def volume_band(per_day: int | float | None) -> str:
    """Free-tier volume bucket. Exact daily_volume stays on the paid columns."""
    if per_day is None:
        return "unknown"
    try:
        n = float(per_day)
    except (TypeError, ValueError):
        return "unknown"
    if n > 1000:
        return ">1k"
    if n >= 100:
        return "100-1k"
    return "<100"


def _weak_sites(comp: dict | None) -> tuple[int | None, list | None]:
    if not comp:
        return None, None
    count = comp.get("weak")
    results = comp.get("results") or []
    weak_dr = 30
    sites = [
        {k: x.get(k) for k in ("domain", "url", "title", "position", "kind", "dr")}
        for x in results
        if x.get("dr") is not None and x["dr"] < weak_dr
    ]
    return (int(count) if count is not None else (len(sites) if sites else None)), (sites or None)


def _action(row: dict) -> str | None:
    yours = row.get("yours") or {}
    if yours.get("action"):
        return yours["action"]
    return row.get("decision")


def opportunity_row(row: dict, discovered: date | None = None) -> dict:
    """One usecases table row -> keyword_opportunities insert dict."""
    day = discovered or date.today()
    comp = row.get("competition") if isinstance(row.get("competition"), dict) else None
    markets = row.get("markets") if isinstance(row.get("markets"), dict) else None
    weak_count, weak_sites = _weak_sites(comp)
    per_day = row.get("per_day")
    payload = {k: v for k, v in row.items() if not k.startswith("_")}
    return {
        "discovered_date": day.isoformat() if isinstance(day, date) else day,
        "keyword": row.get("phrase") or row.get("term") or "",
        "kind": row.get("kind") or "name",
        "behind_names": list(row.get("names") or []),
        "format": opportunity.fmt({"term": row.get("phrase") or "", "examples": [], "posts": [], "about": ""}),
        "daily_volume": int(per_day) if per_day is not None else None,
        "volume_band": volume_band(per_day),
        "trend_status": None if row.get("no_data") else row.get("now"),
        "started_rising": row.get("started"),
        "momentum": row.get("momentum"),
        "kd": (comp or {}).get("kd"),
        "weak_sites_count": weak_count,
        "weak_sites": weak_sites,
        "best_market": (markets or {}).get("best"),
        "markets": markets,
        "decision": row.get("decision"),
        "action": _action(row),
        "is_acted": False,
        "demoted": bool(row.get("demoted")),
        "brand": bool(row.get("brand")),
        "source": row.get("source"),
        "serp": row.get("serp"),
        "year": row.get("year"),
        "age": row.get("age"),
        "dot_com": row.get("dot_com"),
        "payload": payload,
    }


def opportunities_from_usecases(uc: dict, discovered: date | None = None) -> list[dict]:
    if not uc or uc.get("skipped") or uc.get("error"):
        return []
    return [opportunity_row(r, discovered) for r in uc.get("rows") or [] if r.get("phrase") or r.get("term")]


def lead_row(lead: dict, discovered: date | None = None) -> dict:
    """One report lead -> discovered_leads insert dict."""
    day = discovered or date.today()
    tagged = opportunity.tag(dict(lead))
    examples = list(lead.get("examples") or [])[:5]
    return {
        "discovered_date": day.isoformat() if isinstance(day, date) else day,
        "term": lead.get("term") or "",
        "format": tagged.get("format") or "text",
        "signals": list(lead.get("signals") or []),
        "name_score": lead.get("named"),
        "examples": examples,
        "kinds": list(lead.get("kinds") or []),
    }


def leads_from_report(leads: list[dict], discovered: date | None = None) -> list[dict]:
    return [lead_row(r, discovered) for r in leads if r.get("term")]


def signals_overview(blocks: dict, extra: dict | None = None) -> dict:
    """Compact per-signal summary for reports.signals_overview."""
    out: dict[str, Any] = {}
    for name, block in (blocks or {}).items():
        if not isinstance(block, dict):
            continue
        summary: dict[str, Any] = {}
        for key in ("error", "skipped", "seconds", "posts", "answered", "accounts", "models", "spaces",
                    "searched", "read", "asks", "links", "new", "old", "cost_micros", "first_run"):
            if key in block:
                summary[key] = block[key]
        if "sites" in block and isinstance(block["sites"], dict):
            summary["sites"] = {
                s: {"urls": v.get("urls"), "new": v.get("new"), "error": v.get("error")}
                for s, v in block["sites"].items() if isinstance(v, dict)
            }
        if "terms" in block:
            summary["terms"] = len(block["terms"] or [])
        if "repos" in block:
            summary["repos"] = len(block["repos"] or [])
        if "products" in block:
            summary["products"] = len(block["products"] or [])
        out[name] = summary
    for name in ("judge", "usecases", "sidelights"):
        block = (extra or {}).get(name)
        if isinstance(block, dict):
            out[name] = {k: block[k] for k in ("error", "skipped", "seconds", "judged", "names", "kept", "cost_micros")
                         if k in block}
    return out


def collect_errors(blocks: dict, extra: dict | None = None, more: list | None = None) -> list[str]:
    """Flatten error strings from signal blocks and extra steps."""
    errors: list[str] = []
    for name, block in list((blocks or {}).items()) + list((extra or {}).items()):
        if not isinstance(block, dict):
            continue
        if block.get("error"):
            errors.append(f"{name}: {block['error']}")
        for key in ("errors", "competition_errors", "country_errors", "related_errors"):
            for item in block.get(key) or []:
                errors.append(f"{name}.{key}: {item}")
        if block.get("posts_error"):
            errors.append(f"{name}.posts_error: {block['posts_error']}")
    for item in more or []:
        if item:
            errors.append(str(item))
    return errors


def total_cost_micros(blocks: dict, extra: dict | None = None) -> int:
    total = 0
    for block in list((blocks or {}).values()) + list((extra or {}).values()):
        if isinstance(block, dict) and block.get("cost_micros"):
            try:
                total += int(block["cost_micros"])
            except (TypeError, ValueError):
                pass
    return total


def run_status(errors: list[str], opportunities: list, leads: list) -> str:
    """success when no errors; partial when some data with errors; failed when nothing useful."""
    if not errors:
        return "success"
    if opportunities or leads:
        return "partial"
    return "failed"
