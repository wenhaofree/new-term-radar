"""Mail a report (Markdown) through Resend, and/or alert via webhook (Feishu / DingTalk / Telegram).

Environment for mail: RESEND_API_KEY, EMAIL_FROM, RADAR_EMAIL_TO (comma-separated).
Without RADAR_EMAIL_TO mail is skipped: a missing recipient must not fail the run.

Environment for alerts: RADAR_WEBHOOK_URL, RADAR_WEBHOOK_TYPE=feishu|dingtalk|telegram|generic
(default feishu when URL looks like open.feishu.cn / flybook, else generic JSON {text}).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from . import UA

# Inline styles: Gmail drops a <style> block that sits outside <head>, which leaves
# tables unbordered with centred headers. Every tag carries its own.
FONT = "-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif"
INLINE = {
    "h2": "font-size:18px;margin:0 0 12px;color:#1f2328",
    "h3": "font-size:15px;margin:24px 0 8px;color:#1f2328",
    "p": "margin:8px 0",
    "table": "border-collapse:collapse;margin:8px 0;width:100%",
    "th": "border:1px solid #d0d7de;padding:6px 10px;font-size:13px;background:#f6f8fa;text-align:left;white-space:nowrap",
    "td": "border:1px solid #d0d7de;padding:6px 10px;font-size:13px;vertical-align:top",
    "ul": "padding-left:0;margin:8px 0;list-style:none",
    "li": "margin:0 0 10px;padding:8px 12px;border-left:3px solid #d0d7de;background:#f6f8fa;font-size:13px",
    "a": "color:#0969da",
}
TAG = re.compile(r"<(" + "|".join(INLINE) + r")(\s[^>]*)?>")
_ADDRESS = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[a-z]{2,}$", re.I)


def _inline(m: re.Match) -> str:
    attrs = m.group(2) or ""
    if m.group(1) == "td" and 'style="text-align' in attrs:   # markdown's own column alignment
        return f"<td{attrs}>"
    return f'<{m.group(1)} style="{INLINE[m.group(1)]}"{attrs}>'


def html(md_text: str) -> str:
    import markdown
    body = TAG.sub(_inline, markdown.markdown(md_text, extensions=["tables"]))
    return f'<div style="font:14px/1.6 {FONT};color:#1f2328;max-width:900px">{body}</div>'


def recipients(raw: str) -> list[str]:
    """RADAR_EMAIL_TO as people type it: commas (also full-width), semicolons or spaces
    between addresses; quotes and angle brackets around them are dropped."""
    parts = re.split(r"[,，;；\s]+", raw.strip().strip("\"'"))
    return [p.strip("\"'<>") for p in parts if p.strip("\"'<>")]


def send(subject: str, md_text: str) -> str:
    to = recipients(os.environ.get("RADAR_EMAIL_TO", ""))
    if not to:
        return "mail skipped: RADAR_EMAIL_TO not set"
    bad = [i + 1 for i, a in enumerate(to) if not _ADDRESS.match(a)]
    if bad:   # the address itself stays out of the log
        raise SystemExit(f"RADAR_EMAIL_TO: {len(to)} address(es), number {bad} is not an email address")
    body = json.dumps({"from": os.environ["EMAIL_FROM"], "to": to, "subject": subject, "html": html(md_text)}).encode()
    # Resend sits behind Cloudflare, which answers Python's default User-Agent with 403 "error code: 1010".
    req = urllib.request.Request("https://api.resend.com/emails", data=body, method="POST", headers={
        "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}", "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return f"mail sent ({res.status})"
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Resend {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc


def webhook_type(url: str = "") -> str:
    explicit = (os.environ.get("RADAR_WEBHOOK_TYPE") or "").strip().lower()
    if explicit in ("feishu", "dingtalk", "telegram", "generic"):
        return explicit
    u = (url or os.environ.get("RADAR_WEBHOOK_URL") or "").lower()
    if "feishu" in u or "larksuite" in u or "flybook" in u:
        return "feishu"
    if "dingtalk" in u or "oapi.dingtalk" in u:
        return "dingtalk"
    if "api.telegram.org" in u:
        return "telegram"
    return "generic"


def _payload(kind: str, title: str, text: str) -> dict:
    body = f"{title}\n{text}".strip()
    if kind == "feishu":
        return {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title[:80] or "radar",
                        "content": [[{"tag": "text", "text": text[:3500]}]],
                    }
                }
            },
        }
    if kind == "dingtalk":
        return {"msgtype": "text", "text": {"content": body[:3500]}}
    if kind == "telegram":
        return {"text": body[:3500]}
    return {"text": body, "title": title, "message": text}


def alert(title: str, text: str) -> str:
    """Post an alert to RADAR_WEBHOOK_URL. Skips quietly when unset."""
    url = (os.environ.get("RADAR_WEBHOOK_URL") or "").strip()
    if not url:
        return "alert skipped: RADAR_WEBHOOK_URL not set"
    kind = webhook_type(url)
    data = json.dumps(_payload(kind, title, text), ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return f"alert sent ({kind}, {res.status})"
    except urllib.error.HTTPError as exc:
        return f"alert failed HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"
    except (OSError, ValueError) as exc:
        return f"alert failed: {type(exc).__name__}: {exc}"
