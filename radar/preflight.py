"""Cheap API key checks before a paid daily run.

Fails fast on a missing or invalid AIsa key. Optional GoAnyAPI / TrustMRR keys are
checked only when present (or when revenue is forced on). Callers alert and abort on failure.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import UA, aisa, goanyapi, revenue


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Result:
    ok: bool
    checks: list[Check] = field(default_factory=list)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def summary(self) -> str:
        if self.ok:
            return "preflight ok: " + ", ".join(f"{c.name}={c.detail or 'ok'}" for c in self.checks)
        return "preflight failed: " + "; ".join(f"{c.name}: {c.detail}" for c in self.failures)


def _aisa() -> Check:
    if not aisa.has_key():
        return Check("aisa", False, "no AISA_API_KEY (and no ~/.aisa login)")
    try:
        aisa._post(aisa.CHAT, {
            "model": "gpt-4.1-nano",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }, timeout=30)
        return Check("aisa", True, "chat ok")
    except aisa.AisaError as exc:
        msg = str(exc)
        if "401" in msg or "invalid_api_key" in msg.lower():
            return Check("aisa", False, f"invalid or unpaid key ({msg[:120]})")
        return Check("aisa", False, msg[:160])


def _goany() -> Check | None:
    if not goanyapi.key():
        return None
    try:
        req = urllib.request.Request(
            goanyapi.BASE.rstrip("/") + "/",
            headers={"authorization": f"Bearer {goanyapi.key()}", "accept": "application/json", "user-agent": UA},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                res.read(200)
            return Check("goanyapi", True, "reachable")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:120]
            if exc.code in (401, 403):
                return Check("goanyapi", False, f"HTTP {exc.code}: {body}")
            if exc.code in (404, 405):
                return Check("goanyapi", True, f"HTTP {exc.code} (key accepted)")
            return Check("goanyapi", False, f"HTTP {exc.code}: {body}")
    except (OSError, ValueError) as exc:
        return Check("goanyapi", False, f"{type(exc).__name__}: {exc}")


def _trustmrr(required: bool) -> Check | None:
    if not revenue.key():
        if required:
            return Check("trustmrr", False, "TRUSTMRR_API_KEY required for --revenue / Monday revenue")
        return None
    try:
        req = urllib.request.Request(
            f"{revenue.API}?limit=1&page=1&sort=listed-desc",
            headers={"Authorization": f"Bearer {revenue.key()}", "User-Agent": UA, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as res:
            json.load(res)
        return Check("trustmrr", True, "ok")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:120]
        return Check("trustmrr", False, f"HTTP {exc.code}: {body}")
    except (OSError, ValueError) as exc:
        return Check("trustmrr", False, f"{type(exc).__name__}: {exc}")


def run(*, need_revenue: bool = False, skip_network: bool = False) -> Result:
    """Check required keys. skip_network only verifies presence (for unit tests)."""
    checks: list[Check] = []
    if skip_network:
        checks.append(Check("aisa", aisa.has_key(), "present" if aisa.has_key() else "missing"))
        if goanyapi.key():
            checks.append(Check("goanyapi", True, "present"))
        if need_revenue and not revenue.key():
            checks.append(Check("trustmrr", False, "TRUSTMRR_API_KEY required"))
        elif revenue.key():
            checks.append(Check("trustmrr", True, "present"))
        if os.environ.get("DATABASE_URL", "").strip():
            checks.append(Check("database_url", True, "set"))
        return Result(ok=all(c.ok for c in checks), checks=checks)

    checks.append(_aisa())
    g = _goany()
    if g:
        checks.append(g)
    t = _trustmrr(need_revenue)
    if t:
        checks.append(t)
    if os.environ.get("DATABASE_URL", "").strip():
        checks.append(Check("database_url", True, "set"))
    else:
        checks.append(Check("database_url", True, "unset (file/SQLite only)"))
    # database_url is informational; never fail the run for being unset
    hard = [c for c in checks if c.name != "database_url"]
    return Result(ok=all(c.ok for c in hard), checks=checks)
