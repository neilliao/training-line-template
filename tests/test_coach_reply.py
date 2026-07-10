"""對話教練結構化回覆：coach_agent._normalize_reply / _fallback_reply +
coach_flex.build_reply()。取代舊版整段文字推播（原作者 反饋：不想讀大段文字）。"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coach_agent
import coach_flex

_HEX = re.compile(r"^#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")


def _walk_colors(obj, bad):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("color", "backgroundColor") and isinstance(v, str):
                if not _HEX.match(v):
                    bad.append(v)
            _walk_colors(v, bad)
    elif isinstance(obj, list):
        for v in obj:
            _walk_colors(v, bad)


def test_normalize_reply_keeps_valid_fields():
    data = {
        "headline": "今天可以練，天氣普通",
        "status": "good",
        "rows": [{"label": "課表", "value": "10k Z2"}, {"label": "天氣", "value": "28度 多雲"}],
        "tips": ["補水", "配速壓住"],
        "ask": "",
    }
    out = coach_agent._normalize_reply(data)
    assert out["headline"] == "今天可以練，天氣普通"
    assert out["status"] == "good"
    assert len(out["rows"]) == 2
    assert out["tips"] == ["補水", "配速壓住"]


def test_normalize_reply_caps_rows_and_tips():
    # rows 上限 7（週課表逐日建議一天一列，最多七天）、tips 上限 3
    data = {
        "headline": "測試",
        "status": "warn",
        "rows": [{"label": f"L{i}", "value": f"V{i}"} for i in range(10)],
        "tips": [f"tip{i}" for i in range(10)],
    }
    out = coach_agent._normalize_reply(data)
    assert len(out["rows"]) == 7
    assert len(out["tips"]) <= 3


def test_normalize_reply_invalid_status_falls_back_to_warn():
    out = coach_agent._normalize_reply({"headline": "x", "status": "nonsense", "rows": []})
    assert out["status"] == "warn"


def test_normalize_reply_drops_incomplete_rows():
    out = coach_agent._normalize_reply({
        "headline": "x", "status": "good",
        "rows": [{"label": "課表", "value": ""}, {"label": "", "value": "有值沒標籤"},
                 {"label": "天氣", "value": "晴天"}],
    })
    assert out["rows"] == [{"label": "天氣", "value": "晴天"}]


def test_fallback_reply_shape():
    out = coach_agent._fallback_reply("教練想太久了")
    assert out["headline"] == "教練想太久了"
    assert out["status"] == "warn"
    assert out["rows"] == []


def test_build_reply_all_colors_valid_hex():
    data = coach_agent._normalize_reply({
        "headline": "今天可以練，但天氣偏熱",
        "status": "warn",
        "rows": [{"label": "課表", "value": "10k Z2"}, {"label": "天氣", "value": "WBGT 29 高風險"}],
        "tips": ["降速壓心率", "多補水"],
        "ask": "要不要我幫你查傍晚時段？",
    })
    flex = coach_flex.build_reply(data)
    bad = []
    _walk_colors(flex, bad)
    assert bad == []
    assert flex["type"] == "flex"
    assert flex["altText"]


def test_build_reply_handles_empty_rows_and_tips():
    data = coach_agent._normalize_reply({"headline": "沒有資料", "status": "bad", "rows": []})
    flex = coach_flex.build_reply(data)
    bad = []
    _walk_colors(flex, bad)
    assert bad == []


def test_build_reply_bad_status_uses_red_deep_header():
    import flex_tokens as t
    data = coach_agent._normalize_reply({"headline": "不建議", "status": "bad", "rows": []})
    flex = coach_flex.build_reply(data)
    assert flex["contents"]["header"]["backgroundColor"] == t.RED_DEEP
