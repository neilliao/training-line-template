"""深度分析組裝邏輯測試（純函式部分 + analyze_deep 的 fallback 骨架）。
不打真實 Anthropic / Firestore / wellness-dashboard，全部用 monkeypatch 隔離，
只驗證「資料來源 A 不足時，只有 A 那段顯示資料不足，其他段不受影響」這個核心誠實鐵則。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai_analyzer as ai
import schedule_history as sh


# ── build_training_desc（今日表現底稿，純函式）───────────────────
def test_build_training_desc_includes_core_fields():
    summary = {
        "date": "2026-07-01", "distance_km": 10.5, "moving_time": "1:00:00",
        "avg_pace": "5'43\"", "avg_hr": 148, "max_hr": 165,
    }
    desc = ai.build_training_desc(summary)
    assert "10.5 km" in desc
    assert "5'43\"" in desc
    assert "148 bpm" in desc


def test_build_training_desc_includes_exec_score_when_present():
    summary = {"date": "2026-07-01", "distance_km": 11, "moving_time": "1:00:00",
               "avg_pace": "5'30\"", "exec_score": 92, "exec_label": "接近完成"}
    desc = ai.build_training_desc(summary)
    assert "92 分" in desc
    assert "接近完成" in desc


def test_build_training_desc_omits_exec_score_when_absent():
    summary = {"date": "2026-07-01", "distance_km": 11, "moving_time": "1:00:00", "avg_pace": "5'30\""}
    desc = ai.build_training_desc(summary)
    assert "達成度" not in desc


# ── _format_history_facts ───────────────────────────────────────
def test_format_history_facts_none_when_no_comparison():
    assert ai._format_history_facts(None) is None


def test_format_history_facts_includes_sample_dates():
    cmp = sh.HistoryComparison(
        matched_count=2, pace_delta_sec=-20, hr_delta_bpm=-5,
        pace_text="這次均配速比近 2 次同類課表平均快 20 秒",
        hr_text="心率比近 2 次同類課表平均低 5 bpm",
        sample_dates=["2026-06-01", "2026-05-25"],
    )
    text = ai._format_history_facts(cmp)
    assert "快 20 秒" in text
    assert "2026-06-01" in text and "2026-05-25" in text


# ── _format_phase_facts ─────────────────────────────────────────
def test_format_phase_facts_none_when_missing():
    assert ai._format_phase_facts(None) is None
    assert ai._format_phase_facts({"based_on_latest_week": "2026-06-29"}) is None  # 無 logic_summary


def test_format_phase_facts_includes_summary_and_based_on():
    coach_logic = {"logic_summary": ["分層同構：質量課結構固定", "賽後恢復約 3-4 週"],
                    "based_on_latest_week": "2026-06-29"}
    text = ai._format_phase_facts(coach_logic)
    assert "分層同構" in text
    assert "2026-06-29" in text


# ── _format_body_facts ──────────────────────────────────────────
def test_format_body_facts_none_when_both_missing():
    assert ai._format_body_facts(None, None) is None


def test_format_body_facts_drift_only():
    text = ai._format_body_facts(3, None)
    assert "+3 bpm" in text
    assert "有氧穩定" in text


def test_format_body_facts_wellness_signals():
    wellness = {"signals": [
        {"key": "load_spike", "value": 1.4, "msg": "訓練量加得有點快"},
        {"key": "tsb", "value": -10.0, "msg": "疲勞累積中"},
        {"key": "recovery", "msg": "恢復指標穩定"},
    ]}
    text = ai._format_body_facts(None, wellness)
    assert "1.4" in text and "訓練量加得有點快" in text
    assert "-10.0" in text and "疲勞累積中" in text
    assert "恢復指標穩定" in text


# ── _resolve_section：誠實鐵則 ────────────────────────────────────
def test_resolve_section_insufficient_when_no_facts():
    assert ai._resolve_section("模型講的話", None, "這部分資料不足") == "這部分資料不足"


def test_resolve_section_uses_llm_text_when_available():
    assert ai._resolve_section("模型講的話", "有底稿", "資料不足") == "模型講的話"


def test_resolve_section_falls_back_to_facts_when_llm_empty():
    assert ai._resolve_section("", "有底稿事實文字", "資料不足") == "有底稿事實文字"
    assert ai._resolve_section(None, "有底稿事實文字", "資料不足") == "有底稿事實文字"


# ── _parse_deep_json ─────────────────────────────────────────────
def test_parse_deep_json_valid():
    text = '{"today_performance": "還不錯", "advice": "多喝水"}'
    data = ai._parse_deep_json(text)
    assert data["today_performance"] == "還不錯"


def test_parse_deep_json_strips_code_fence():
    text = '```json\n{"advice": "多喝水"}\n```'
    assert ai._parse_deep_json(text)["advice"] == "多喝水"


def test_parse_deep_json_invalid_returns_empty():
    assert ai._parse_deep_json("不是 JSON") == {}
    assert ai._parse_deep_json("") == {}
    assert ai._parse_deep_json("[1, 2, 3]") == {}


# ── analyze_deep：無 LLM client 時，逐段誠實 fallback（不打網路）───
def test_analyze_deep_without_client_falls_back_per_section(monkeypatch):
    monkeypatch.setattr(ai, "_get_client", lambda: None)
    monkeypatch.setattr(ai, "_fetch_history_comparison", lambda *a, **k: None)
    monkeypatch.setattr(ai, "_fetch_coach_logic", lambda: None)
    monkeypatch.setattr(ai, "_fetch_wellness_signals", lambda: None)

    summary = {"sport": "Run", "date": "2026-07-01", "distance_km": 10,
               "moving_time": "0:55:00", "avg_pace": "5'30\"", "avg_hr": 150}
    result = ai.analyze_deep(summary, schedule_workout="10-12k P'530-540/km")

    assert set(result.keys()) == {
        "today_performance", "history_comparison", "training_phase",
        "body_signals", "advice", "generated_at",
    }
    # 有底稿（今日表現一定算得出來）→ 不該顯示資料不足
    assert "資料不足" not in result["today_performance"]
    # 沒有歷史比較/教練邏輯/身體訊號來源 → 三段都誠實顯示資料不足
    assert "資料不足" in result["history_comparison"]
    assert "資料不足" in result["training_phase"]
    assert "資料不足" in result["body_signals"]
    assert "資料不足" in result["advice"]


def test_analyze_deep_uses_available_history_facts_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(ai, "_get_client", lambda: None)
    cmp = sh.HistoryComparison(
        matched_count=1, pace_delta_sec=-10, hr_delta_bpm=None,
        pace_text="這次均配速比近 1 次同類課表平均快 10 秒",
        hr_text="心率資料不足，無法比較", sample_dates=["2026-06-20"],
    )
    monkeypatch.setattr(ai, "_fetch_history_comparison", lambda *a, **k: cmp)
    monkeypatch.setattr(ai, "_fetch_coach_logic", lambda: None)
    monkeypatch.setattr(ai, "_fetch_wellness_signals", lambda: None)

    summary = {"sport": "Run", "date": "2026-07-01", "distance_km": 10,
               "moving_time": "0:55:00", "avg_pace": "5'20\"", "avg_hr": 150}
    result = ai.analyze_deep(summary, schedule_workout="10-12k P'530-540/km")

    assert "快 10 秒" in result["history_comparison"]
    # 這裡「心率資料不足」是比較結果裡合理的子細節，不是整段開天窗；
    # 用整段的固定 fallback 訊息當反例才是正確的誠實鐵則驗證
    assert "找不到同類型的歷史課表可比較" not in result["history_comparison"]


def test_analyze_deep_section_failure_is_isolated(monkeypatch):
    """歷史比較查詢炸掉，其他段不受影響（各段獨立 try/except 的核心保證）。"""
    def _boom(*a, **k):
        raise RuntimeError("Firestore 掛了")

    monkeypatch.setattr(ai, "_get_client", lambda: None)
    monkeypatch.setattr(ai, "_fetch_history_comparison", _boom)
    monkeypatch.setattr(ai, "_fetch_coach_logic",
                         lambda: {"logic_summary": ["賽後恢復約 3-4 週"], "based_on_latest_week": "2026-06-29"})
    monkeypatch.setattr(ai, "_fetch_wellness_signals", lambda: None)

    summary = {"sport": "Run", "date": "2026-07-01", "distance_km": 10,
               "moving_time": "0:55:00", "avg_pace": "5'20\"", "avg_hr": 150,
               "cardiac_drift": 3}
    result = ai.analyze_deep(summary, schedule_workout="10-12k P'530-540/km")

    assert "資料不足" in result["history_comparison"]        # 炸掉的那段
    assert "賽後恢復約 3-4 週" in result["training_phase"]     # 沒炸掉的段落正常
    assert "有氧穩定" in result["body_signals"]                # 心率漂移仍算得出來
