"""Fallback Twitter post collector using a Nitter instance (https://nitter.wenhaofree.com).

Used when AISA_API_KEY is not configured or unavailable.
Extracts recent posts for target accounts with rate-limiting to prevent anti-bot blocking.
"""
from __future__ import annotations

import html as html_lib
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_BASE_URL = "https://nitter.wenhaofree.com"
DEFAULT_PAUSE = 1.5
DEFAULT_TIMEOUT = 45
DEFAULT_RETRIES = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}


def parse_date(date_str: str) -> datetime | None:
    """Parse date strings found in Nitter date titles into UTC datetimes."""
    if not date_str:
        return None
    cleaned = re.sub(r"[\s·]+", " ", date_str.strip())
    formats = [
        "%b %d, %Y %I:%M %p UTC",
        "%b %d, %Y %I:%M %p",
        "%d %b %Y %I:%M %p UTC",
        "%d %b %Y %I:%M %p",
        "%b %d, %Y %H:%M UTC",
        "%d %b %Y %H:%M UTC",
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def parse_timeline(html_content: str, handle: str) -> list[dict]:
    """Parse timeline HTML from Nitter into a list of post dictionaries:
    {'account': str, 'text': str, 'likes': int, 'url': str, 'created': datetime | None}."""
    parts = re.split(r'<div class="timeline-item[ \"]', html_content)
    posts: list[dict] = []

    for part in parts[1:]:
        link_m = re.search(r'<a class="tweet-link" href="([^"]+)"', part)
        if not link_m:
            continue
        raw_path = link_m.group(1).split("#")[0]
        url = f"https://x.com{raw_path}"

        date_m = re.search(r'<span class="tweet-date"><a [^>]*title="([^"]+)"', part)
        created = parse_date(date_m.group(1)) if date_m else None

        content_m = re.search(r'<div class="tweet-content media-body"[^>]*>(.*?)</div>', part, re.DOTALL)
        text = ""
        if content_m:
            raw_text = content_m.group(1)
            raw_text = re.sub(r'<br\s*/?>', "\n", raw_text)
            raw_text = re.sub(r'<[^>]+>', " ", raw_text)
            text = html_lib.unescape(raw_text).strip()

        is_retweet = "retweet-header" in part or "Retweeted" in part
        if is_retweet and not text.startswith("RT @"):
            text = f"RT @unknown: {text}"

        likes_m = re.search(r'<span class="icon-heart"[^>]*></span>\s*([0-9,]+)', part)
        likes = int(likes_m.group(1).replace(",", "")) if likes_m else 0

        posts.append({
            "account": handle,
            "text": text,
            "likes": likes,
            "url": url,
            "created": created,
        })

    return posts


def fetch_account_posts(
    handle: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> list[dict]:
    """Fetch and parse tweets for a single Twitter account from Nitter with automatic retries on timeout or rate limit."""
    url = f"{base_url.rstrip('/')}/{handle}"
    req = urllib.request.Request(url, headers=HEADERS)

    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                content = res.read().decode("utf-8", errors="replace")
            return parse_timeline(content, handle)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                if attempt < retries:
                    backoff = 6.0 * attempt
                    sys.stderr.write(f"nitter: 429 rate limit on @{handle}, backing off {backoff:.1f}s (attempt {attempt}/{retries})...\n")
                    time.sleep(backoff)
                    continue
                sys.stderr.write(f"nitter: 429 rate limit on @{handle} after {retries} attempts, skipping\n")
                return []
            if exc.code == 404:
                sys.stderr.write(f"nitter: account @{handle} not found (404), skipping\n")
                return []
            if exc.code in (500, 502, 503, 504):
                if attempt < retries:
                    sys.stderr.write(f"nitter: HTTP {exc.code} on @{handle}, retrying ({attempt}/{retries})...\n")
                    time.sleep(3.0 * attempt)
                    continue
            sys.stderr.write(f"nitter: HTTP error {exc.code} for @{handle}, skipping\n")
            return []
        except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as exc:
            err_msg = str(exc)
            is_timeout = isinstance(exc, TimeoutError) or "timed out" in err_msg.lower() or "handshake" in err_msg.lower()
            if is_timeout:
                if attempt < retries:
                    backoff = 3.0 * attempt
                    sys.stderr.write(f"nitter: @{handle} read timed out ({timeout}s), retrying in {backoff:.1f}s ({attempt}/{retries})...\n")
                    time.sleep(backoff)
                    continue
                sys.stderr.write(f"nitter: @{handle} timed out after {retries} attempts ({timeout}s each), skipping\n")
                return []
            if attempt < retries:
                sys.stderr.write(f"nitter: network error on @{handle}: {exc}, retrying ({attempt}/{retries})...\n")
                time.sleep(2.0 * attempt)
                continue
            sys.stderr.write(f"nitter: error fetching @{handle}: {exc}, skipping\n")
            return []
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"nitter: unexpected error for @{handle}: {exc}, skipping\n")
            return []

    return []


def fetch_posts(handles: list[str], cfg: dict) -> tuple[list[dict], int]:
    """Fetch tweets for all given handles with interval throttling to prevent rate limiting.
    Returns (posts, answered_account_count)."""
    nitter_cfg = cfg.get("nitter", {}) if isinstance(cfg, dict) else {}
    base_url = nitter_cfg.get("base_url") or os.environ.get("NITTER_BASE_URL") or DEFAULT_BASE_URL
    pause = float(os.environ.get("NITTER_PAUSE") or nitter_cfg.get("pause", DEFAULT_PAUSE))
    timeout = int(os.environ.get("NITTER_TIMEOUT") or nitter_cfg.get("timeout", DEFAULT_TIMEOUT))
    retries = int(os.environ.get("NITTER_RETRIES") or nitter_cfg.get("retries", DEFAULT_RETRIES))

    posts: list[dict] = []
    answered = 0

    for i, handle in enumerate(handles):
        account_posts = fetch_account_posts(handle, base_url=base_url, timeout=timeout, retries=retries)
        if account_posts:
            posts.extend(account_posts)
            answered += 1

        # Sleep between requests to avoid trigger anti-bot / rate limit
        if i < len(handles) - 1 and pause > 0:
            time.sleep(pause)

    return posts, answered
