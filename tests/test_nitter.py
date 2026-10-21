from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from radar import aisa, nitter, sources


def test_parse_date_valid():
    dt = nitter.parse_date("Oct 20, 2026 · 8:57 PM UTC")
    assert dt == datetime(2026, 10, 20, 20, 57, tzinfo=timezone.utc)

    dt2 = nitter.parse_date("Dec 3, 2025 · 6:28 PM UTC")
    assert dt2 == datetime(2025, 12, 3, 18, 28, tzinfo=timezone.utc)

    dt3 = nitter.parse_date("3 Dec 2025 · 6:28 PM UTC")
    assert dt3 == datetime(2025, 12, 3, 18, 28, tzinfo=timezone.utc)


def test_parse_date_invalid():
    assert nitter.parse_date("") is None
    assert nitter.parse_date("not a date") is None


def test_parse_timeline_html():
    sample_html = """
    <div class="timeline">
      <div class="timeline-item " data-username="dotey">
        <a class="tweet-link" href="/dotey/status/2112649429371040028#m"></a>
        <div class="tweet-body">
          <div class="tweet-header">
            <span class="tweet-date"><a href="/dotey/status/2112649429371040028#m" title="Oct 20, 2026 · 8:57 PM UTC">6h</a></span>
          </div>
          <div class="tweet-content media-body" dir="auto">Introducing Qwen3.8 &amp; HyperFrames on Claude Code</div>
          <div class="tweet-stats">
            <span class="tweet-stat"><div class="icon-container"><span class="icon-heart" title=""></span> 1,491</div></span>
          </div>
        </div>
      </div>
      <div class="timeline-item " data-username="dotey">
        <a class="tweet-link" href="/dotey/status/2112646324860465280#m"></a>
        <div class="tweet-body">
          <div class="retweet-header"><span>Retweeted</span></div>
          <div class="tweet-header">
            <span class="tweet-date"><a href="/dotey/status/2112646324860465280#m" title="Oct 20, 2026 · 8:45 PM UTC">6h</a></span>
          </div>
          <div class="tweet-content media-body" dir="auto">Some shared wisdom</div>
          <div class="tweet-stats">
            <span class="tweet-stat"><div class="icon-container"><span class="icon-heart" title=""></span></div></span>
          </div>
        </div>
      </div>
    </div>
    """
    posts = nitter.parse_timeline(sample_html, "dotey")
    assert len(posts) == 2

    # First post
    p1 = posts[0]
    assert p1["account"] == "dotey"
    assert p1["url"] == "https://x.com/dotey/status/2112649429371040028"
    assert p1["likes"] == 1491
    assert p1["created"] == datetime(2026, 10, 20, 20, 57, tzinfo=timezone.utc)
    assert p1["text"] == "Introducing Qwen3.8 & HyperFrames on Claude Code"

    # Second post (Retweet & 0 likes)
    p2 = posts[1]
    assert p2["account"] == "dotey"
    assert p2["url"] == "https://x.com/dotey/status/2112646324860465280"
    assert p2["likes"] == 0
    assert p2["created"] == datetime(2026, 10, 20, 20, 45, tzinfo=timezone.utc)
    assert p2["text"].startswith("RT @")


def test_nitter_fetch_posts_rate_limiting():
    cfg = {"nitter": {"base_url": "https://nitter.wenhaofree.com", "pause": 0.01, "timeout": 5}}
    mock_post = {"account": "dotey", "text": "hello", "likes": 10, "url": "https://x.com/1", "created": None}

    with patch("radar.nitter.fetch_account_posts", return_value=[mock_post]) as mock_fetch:
        posts, answered = nitter.fetch_posts(["user1", "user2"], cfg)
        assert mock_fetch.call_count == 2
        assert answered == 2
        assert len(posts) == 2


def test_x_new_falls_back_to_nitter_when_no_aisa_key(tmp_path):
    cfg = {
        "x_accounts": {"labs": ["dotey"], "bloggers": []},
        "nitter": {"base_url": "https://nitter.wenhaofree.com", "pause": 0},
    }
    mock_posts = [{
        "account": "dotey",
        "text": "Introducing NovelFramework 2.0 with groundbreaking speed",
        "likes": 500,
        "url": "https://x.com/dotey/status/123",
        "created": datetime.now(timezone.utc),
    }]

    with patch.object(aisa, "has_key", return_value=False), \
         patch("radar.nitter.fetch_posts", return_value=(mock_posts, 1)) as mock_nitter:
        result = sources.x_new(cfg, tmp_path)
        assert mock_nitter.called
        assert result["answered"] == 1
        assert result["posts"] == 1
        assert result["cost_micros"] == 0


def test_x_new_falls_back_to_nitter_when_aisa_fails(tmp_path):
    cfg = {
        "x_accounts": {"labs": ["dotey"], "bloggers": []},
        "nitter": {"base_url": "https://nitter.wenhaofree.com", "pause": 0},
    }
    mock_posts = [{
        "account": "dotey",
        "text": "Check out SuperModel 3.5",
        "likes": 300,
        "url": "https://x.com/dotey/status/456",
        "created": datetime.now(timezone.utc),
    }]

    with patch.object(aisa, "has_key", return_value=True), \
         patch.object(aisa, "call_all", side_effect=RuntimeError("AIsa service down")), \
         patch("radar.nitter.fetch_posts", return_value=(mock_posts, 1)) as mock_nitter:
        result = sources.x_new(cfg, tmp_path)
        assert mock_nitter.called
        assert result["answered"] == 1
        assert result["posts"] == 1
        assert result["cost_micros"] == 0
