"""UI translation catalog for multi-language product display."""
from __future__ import annotations

from radar import locale_labels


def test_catalog_has_en_and_zh_for_core_enums():
    d_en = locale_labels.as_dict("en")
    d_zh = locale_labels.as_dict("zh")
    assert d_en["decision"]["prioritize"] == "Prioritize"
    assert d_zh["decision"]["prioritize"] == "优先"
    assert d_en["format"]["video"] == "Video"
    assert d_zh["format"]["video"] == "视频"
    assert d_zh["volume_band"][">1k"].startswith("日搜")
    assert d_en["trend_status"]["rising"] == "Rising"


def test_seed_rows_cover_both_locales_without_dup_keys():
    rows = locale_labels.rows_for_seed()
    assert len(rows) == len(locale_labels.ENTRIES) * 2
    keys = {(loc, cat, key) for loc, cat, key, _ in rows}
    assert len(keys) == len(rows)
    assert {loc for loc, *_ in rows} == {"en", "zh"}
