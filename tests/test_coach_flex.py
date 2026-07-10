import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import coach_flex


def _iter_text(node):
    if isinstance(node, dict):
        if node.get("type") == "text":
            yield node
        for v in node.values():
            yield from _iter_text(v)
    elif isinstance(node, list):
        for it in node:
            yield from _iter_text(it)


def _empty_text_nodes(flex):
    bad = []
    for n in _iter_text(flex):
        t = n.get("text")
        if not isinstance(t, str) or t == "":
            bad.append(n)
    return bad


FULL = {
    "today": "2026-06-04",
    "today_workout": "10-12k P'530-540/km",
    "today_is_rest": False,
    "tomorrow_workout": "間歇 6x800m",
    "week_range": "2026 06/01-06/07",
    "week_goal": "強化有氧基礎，週中一次節奏跑",
    "advice": "今日狀態良好\n按課表跑 10-12k，配速 530-540，心率守在 Z2 上緣\n明日間歇，今晚早睡",
    "hrv": 52, "hrv_status": "良好", "hrv_color": "#16A34A",
    "sleepHrs": 7.5, "sleepScore": 82,
    "tsb": -8.0, "form_status": "疲勞累積", "form_color": "#EF4444",
}


def test_build_returns_flex_with_no_empty_text():
    flex = coach_flex.build(FULL)
    assert flex["type"] == "flex"
    assert flex["contents"]["type"] == "bubble"
    bad = _empty_text_nodes(flex)
    assert not bad, f"空 text node：{bad}"


def test_advice_three_lines_present():
    flex = coach_flex.build(FULL)
    texts = [n["text"] for n in _iter_text(flex)]
    joined = " ".join(texts)
    assert "今日狀態良好" in joined
    assert "按課表跑 10-12k" in joined
    assert "明日間歇，今晚早睡" in joined


def test_missing_fields_no_empty_text():
    sparse = {
        "today": None, "today_workout": "", "today_is_rest": True,
        "tomorrow_workout": "", "week_range": "", "week_goal": "",
        "advice": "", "hrv": None, "sleepHrs": None, "tsb": None,
        "form_status": None,
    }
    flex = coach_flex.build(sparse)
    bad = _empty_text_nodes(flex)
    assert not bad, f"缺欄位仍產生空 text：{bad}"


def test_empty_advice_uses_fallback_line():
    flex = coach_flex.build({"advice": "", "today_workout": "", "today_is_rest": True})
    texts = " ".join(n["text"] for n in _iter_text(flex))
    assert "今日暫無教練建議" in texts


def test_rest_day_workout_label():
    flex = coach_flex.build({"advice": "x", "today_workout": "", "today_is_rest": True})
    texts = [n["text"] for n in _iter_text(flex)]
    assert "休息" in texts


# ── LINE color 不變量：每個 color 都必須是合法 hex，否則 push 400 ──
import re as _re
_HEX = _re.compile(r"^#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")


def _all_color_values(node):
    if isinstance(node, dict):
        for key in ("color", "backgroundColor", "borderColor"):
            v = node.get(key)
            if isinstance(v, str):
                yield v
        for v in node.values():
            yield from _all_color_values(v)
    elif isinstance(node, list):
        for it in node:
            yield from _all_color_values(it)


def test_semantic_token_colors_become_valid_hex():
    # 真實 /api/coach 的 *_color 是語意 token（good/ok/warn/none），不是 hex
    data = dict(FULL)
    data.update(hrv_color="warn", form_color="ok")
    flex = coach_flex.build(data)
    bad = [c for c in _all_color_values(flex) if not _HEX.match(c)]
    assert not bad, f"非法 LINE color（push 會 400）：{bad}"


def test_none_and_unknown_color_tokens_safe():
    data = {"advice": "x", "hrv": 30, "hrv_color": "none",
            "tsb": -5, "form_color": "???", "form_status": "無資料"}
    flex = coach_flex.build(data)
    bad = [c for c in _all_color_values(flex) if not _HEX.match(c)]
    assert not bad, f"非法 LINE color：{bad}"


def test_all_colors_valid_hex_on_full_fixture():
    flex = coach_flex.build(FULL)
    bad = [c for c in _all_color_values(flex) if not _HEX.match(c)]
    assert not bad, f"非法 LINE color：{bad}"


# ── 合併：天氣區塊（weather 參數）──────────────────────────────
WEATHER = {
    "code": 80, "emoji": "🌦️", "desc": "陣雨",
    "t_max": 28, "t_min": 25, "at_max": 34,
    "humidity": 78, "rain_pct": 100, "precip": 20.1, "comfort": "悶熱",
}


def test_weather_block_renders_and_no_empty_text():
    flex = coach_flex.build(FULL, weather=WEATHER)
    bad = _empty_text_nodes(flex)
    assert not bad, f"天氣區塊產生空 text：{bad}"
    texts = " ".join(n["text"] for n in _iter_text(flex))
    assert "今日天氣" in texts
    assert "陣雨" in texts and "28°C" in texts and "100%" in texts
    assert "體感 34°C" in texts and "悶熱" in texts


def test_weather_block_colors_valid_hex():
    flex = coach_flex.build(FULL, weather=WEATHER)
    bad = [c for c in _all_color_values(flex) if not _HEX.match(c)]
    assert not bad, f"非法 LINE color：{bad}"


def test_weather_none_omits_block():
    flex = coach_flex.build(FULL, weather=None)
    texts = " ".join(n["text"] for n in _iter_text(flex))
    assert "今日天氣" not in texts


def test_weather_partial_fields_no_empty_text():
    sparse_wx = {"emoji": "🌡️", "desc": "", "t_max": None, "t_min": None,
                 "at_max": None, "humidity": None, "rain_pct": None, "comfort": ""}
    flex = coach_flex.build(FULL, weather=sparse_wx)
    bad = _empty_text_nodes(flex)
    assert not bad, f"缺欄位天氣仍產生空 text：{bad}"


def test_form_insights_section_rendered():
    coach = dict(FULL)
    coach["form_insights"] = [
        {"topic": "步頻", "level": "green", "msg": "步頻 172，在合理範圍"},
        {"topic": "溫度", "level": "yellow", "msg": "今天 30 度，配速慢 10-15 秒/km 屬正常"},
        {"topic": "強度", "level": "red", "msg": "恢復期，心率守 150 以下"},
    ]
    flex = coach_flex.build(coach)
    texts = [n.get("text") for n in _iter_text(flex)]
    assert "跑前重點" in texts
    assert any("步頻 172" in t for t in texts)
    assert not _empty_text_nodes(flex)


def test_form_insights_absent_no_section():
    flex = coach_flex.build(FULL)
    texts = [n.get("text") for n in _iter_text(flex)]
    assert "跑前重點" not in texts


def test_form_insights_bad_items_skipped():
    coach = dict(FULL)
    coach["form_insights"] = [{"topic": "步頻"}, None, {"msg": ""}]
    flex = coach_flex.build(coach)
    texts = [n.get("text") for n in _iter_text(flex)]
    assert "跑前重點" not in texts
    assert not _empty_text_nodes(flex)


def test_custom_title():
    flex = coach_flex.build(FULL, title="跑前評估")
    texts = [n.get("text") for n in _iter_text(flex)]
    assert "跑前評估" in texts
    assert "今日教練" not in texts
