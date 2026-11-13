"""Product UI translation catalog: enum codes → labels per locale.

Business rows store language-neutral codes (decision=prioritize, format=video, …).
The frontend loads locale_labels for the user's language and maps codes to display text.
Keyword terms themselves are never translated.

Seeded into PostgreSQL table `locale_labels` on ensure_schema / daily persist.
"""
from __future__ import annotations

# (category, key, en, zh)
ENTRIES: list[tuple[str, str, str, str]] = [
    # decision
    ("decision", "prioritize", "Prioritize", "优先"),
    ("decision", "watch", "Watch", "观察"),
    ("decision", "skip", "Skip", "跳过"),
    # trend_status (usecases "now")
    ("trend_status", "rising", "Rising", "上涨中"),
    ("trend_status", "holding", "Holding", "维持"),
    ("trend_status", "fading", "Fading", "回落"),
    ("trend_status", "flat", "Flat", "未上涨"),
    # format (opportunity output type)
    ("format", "video", "Video", "视频"),
    ("format", "voice", "Voice", "语音"),
    ("format", "image", "Image", "图片"),
    ("format", "text", "Text", "文字"),
    # kind
    ("kind", "name", "Name", "专有名词"),
    ("kind", "generic", "Generic", "通用词"),
    # volume_band (free tier)
    ("volume_band", ">1k", ">1k searches/day", "日搜 >1k"),
    ("volume_band", "100-1k", "100–1k searches/day", "日搜 100–1k"),
    ("volume_band", "<100", "<100 searches/day", "日搜 <100"),
    ("volume_band", "unknown", "Unknown volume", "搜索量未知"),
    # action (yours / decision fallback)
    ("action", "new", "Write a new page", "新建页面"),
    ("action", "update", "Update your page", "更新已有页面"),
    ("action", "improve", "Improve ranking", "提升排名"),
    ("action", "prioritize", "Prioritize", "优先"),
    ("action", "watch", "Watch", "观察"),
    ("action", "skip", "Skip", "跳过"),
    # report run status
    ("report_status", "running", "Running", "运行中"),
    ("report_status", "success", "Success", "成功"),
    ("report_status", "partial", "Partial", "部分成功"),
    ("report_status", "failed", "Failed", "失败"),
    # common UI chrome (optional for frontend)
    ("ui", "discovered_leads", "Today's new names", "今日新词"),
    ("ui", "keyword_opportunities", "Keyword opportunities", "关键词机会"),
    ("ui", "daily_report", "Daily report", "日报"),
    ("ui", "free_tier", "Free", "免费"),
    ("ui", "paid_tier", "Pro", "会员"),
]


def rows_for_seed() -> list[tuple[str, str, str, str]]:
    """Flatten to (locale, category, key, label) for upsert."""
    out: list[tuple[str, str, str, str]] = []
    for category, key, en, zh in ENTRIES:
        out.append(("en", category, key, en))
        out.append(("zh", category, key, zh))
    return out


def as_dict(locale: str = "en") -> dict[str, dict[str, str]]:
    """{category: {key: label}} for one locale — handy in tests / offline UI."""
    loc = "zh" if str(locale).lower().startswith("zh") else "en"
    idx = 3 if loc == "zh" else 2
    out: dict[str, dict[str, str]] = {}
    for category, key, en, zh in ENTRIES:
        out.setdefault(category, {})[key] = zh if idx == 3 else en
    return out
