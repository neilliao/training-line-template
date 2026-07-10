"""深度分析 Flex bubble 結構測試（flex_builder.build_deep_analysis_bubble）。
比照 test_coach_flex.py 的不變量：無空 text node、所有顏色是合法 hex。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flex_builder as fb


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
    return [n for n in _iter_text(flex) if not isinstance(n.get("text"), str) or n.get("text") == ""]


_HEX = re.compile(r"^#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")


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


FULL_LOG = {
    "date": "2026-07-01", "distance_km": 10.5, "id": "12345",
    "deep_analysis": {
        "today_performance": "今天配速穩定，心率控制得宜。",
        "history_comparison": "比近 3 次同類課表平均快 15 秒。",
        "training_phase": "目前處於賽後恢復週，質量課降級為選擇性訓練。",
        "body_signals": "心率漂移 +3 bpm，有氧穩定；ACWR 1.1，訓練量安全。",
        "advice": "維持目前節奏，下次質量課可以稍微加量。",
        "generated_at": "2026-07-01T20:00:00",
    },
}


def test_build_returns_valid_flex_bubble():
    flex = fb.build_deep_analysis_bubble(FULL_LOG)
    assert flex["type"] == "flex"
    assert flex["contents"]["type"] == "bubble"
    assert flex["altText"]


def test_no_empty_text_nodes_on_full_fixture():
    flex = fb.build_deep_analysis_bubble(FULL_LOG)
    bad = _empty_text_nodes(flex)
    assert not bad, f"空 text node：{bad}"


def test_all_five_sections_present_in_order():
    flex = fb.build_deep_analysis_bubble(FULL_LOG)
    texts = [n["text"] for n in _iter_text(flex)]
    joined = " ".join(texts)
    for expected in ("今日表現", "跟歷史同類課表比較", "目前所處訓練階段", "身體訊號", "建議"):
        assert expected in joined
    for expected in (
        "今天配速穩定，心率控制得宜。",
        "比近 3 次同類課表平均快 15 秒。",
        "目前處於賽後恢復週，質量課降級為選擇性訓練。",
        "心率漂移 +3 bpm，有氧穩定；ACWR 1.1，訓練量安全。",
        "維持目前節奏，下次質量課可以稍微加量。",
    ):
        assert expected in joined


def test_all_colors_valid_hex():
    flex = fb.build_deep_analysis_bubble(FULL_LOG)
    bad = [c for c in _all_color_values(flex) if not _HEX.match(c)]
    assert not bad, f"非法 LINE color（push 會 400）：{bad}"


def test_missing_deep_analysis_shows_placeholder_not_crash():
    flex = fb.build_deep_analysis_bubble({"date": "2026-07-01", "distance_km": 10, "id": "1"})
    texts = " ".join(n["text"] for n in _iter_text(flex))
    assert "尚未生成完成" in texts


def test_partial_sections_only_render_available_ones():
    log = {
        "date": "2026-07-01", "distance_km": 10, "id": "1",
        "deep_analysis": {"today_performance": "還不錯", "advice": "多喝水"},
    }
    flex = fb.build_deep_analysis_bubble(log)
    texts = " ".join(n["text"] for n in _iter_text(flex))
    assert "還不錯" in texts and "多喝水" in texts
    assert "跟歷史同類課表比較" not in texts  # 沒資料的段落乾脆不畫，而不是畫空卡


def test_run_bubble_footer_has_deep_analysis_button_for_main_role():
    summary = {"id": "1", "date": "2026-07-01", "distance_km": 10, "avg_pace": "5'30\"",
               "moving_time": "1:00:00", "role": "main"}
    flex = fb.build_run_bubble(summary)
    footer_texts = [
        c["action"]["data"] for c in flex["contents"]["footer"]["contents"] if c.get("type") == "button"
    ]
    assert "deep:1" in footer_texts
    assert "detail:1" in footer_texts


def test_run_bubble_footer_omits_deep_analysis_button_for_warmup():
    summary = {"id": "1", "date": "2026-07-01", "distance_km": 3, "avg_pace": "6'30\"",
               "moving_time": "0:20:00", "role": "warmup"}
    flex = fb.build_run_bubble(summary)
    footer_texts = [
        c["action"]["data"] for c in flex["contents"]["footer"]["contents"] if c.get("type") == "button"
    ]
    assert "deep:1" not in footer_texts
    assert "detail:1" in footer_texts
