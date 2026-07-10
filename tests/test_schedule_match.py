"""三態勾稽測試。核心：原作者 2026-06-05 指出的兩個假 ✅。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import schedule_match as sm


# ── 原作者 實際案例（舊版誤判成 ✅）──────────────────────────────
def test_real_case1_time_workout_overrun_is_partial():
    """20-30min FR' 卻跑 39:47 → 應 partial 超量，非 matched。"""
    status, detail = sm.evaluate_match("20-30min FR'", dist_km=6.14, time_sec=39 * 60 + 47)
    assert status == "partial", f"應 partial，實得 {status}"
    assert "超量" in detail and "20" in detail


def test_real_case2_interval_wrong_count_is_partial():
    """課表 1200*3+400*6（9組）卻做 11 組短間歇 → partial，標 11/9。"""
    w = "1200*3 + 400*6 P'114-116 r2'45 P'106-110 r100s"
    status, detail = sm.evaluate_match(w, dist_km=5.2, time_sec=23 * 60 + 17, interval_count=11)
    assert status == "partial", f"應 partial，實得 {status}"
    assert "11" in detail and "9" in detail


# ── 間歇 ──────────────────────────────────────────────────────
def test_interval_exact_count_matched():
    w = "1200*3 + 400*6"
    status, _ = sm.evaluate_match(w, interval_count=9, time_sec=1400)
    assert status == "matched"


def test_interval_too_few_unmatched():
    status, _ = sm.evaluate_match("1200*3 + 400*6", interval_count=2, time_sec=600)
    assert status == "unmatched"


def test_parse_interval_reps():
    assert sm.parse_interval_reps("1200*3 + 400*6") == 9
    assert sm.parse_interval_reps("3x1200") == 3
    assert sm.parse_interval_reps("800x10") == 10


# ── 距離 ──────────────────────────────────────────────────────
def test_distance_in_range_matched():
    status, _ = sm.evaluate_match("10-12k", dist_km=11.0)
    assert status == "matched"


def test_distance_over_is_partial():
    status, detail = sm.evaluate_match("10-12k", dist_km=18.0)
    assert status == "partial" and "超量" in detail


def test_distance_slightly_under_is_partial():
    status, detail = sm.evaluate_match("10-12k", dist_km=9.0)  # ≥ 85% of 10
    assert status == "partial" and "略少" in detail


def test_distance_far_under_unmatched():
    status, _ = sm.evaluate_match("10-12k", dist_km=6.0)  # < 8.5
    assert status == "unmatched"


# ── 時間 ──────────────────────────────────────────────────────
def test_time_in_range_matched():
    status, _ = sm.evaluate_match("20-30min FR'", dist_km=5.0, time_sec=25 * 60)
    assert status == "matched"


# ── 無法解析：有跑就算 ─────────────────────────────────────────
def test_unparseable_but_ran_matched():
    status, _ = sm.evaluate_match("FR' 輕鬆跑", dist_km=5.0, time_sec=1800)
    assert status == "matched"


def test_nothing_ran_unmatched():
    status, _ = sm.evaluate_match("FR'", dist_km=0, time_sec=0)
    assert status == "unmatched"


# ── 配速達標判讀 evaluate_pace ────────────────────────────────────
# 核心：原作者 2026-06-25 指出 AI 把 4'36"（偏慢）誤判成「偏快」。
# 配速數字越大越慢，方向判斷不可外包給小模型，用純函式算好。
def test_pace_real_case_slower():
    """課表 425-435/km、實跑 4'36" → 比慢端 4'35" 還慢 1 秒 = 偏慢未達。"""
    r = sm.evaluate_pace("4'36\"", "800*5-6 P'106-110 (425-435/km) r2' +肌力訓練")
    assert r is not None
    assert r.verdict == "slower"
    assert r.delta_sec == 1


def test_pace_on_target_mid():
    r = sm.evaluate_pace("4'30\"", "800*5-6 (425-435/km)")
    assert r.verdict == "on_target"
    assert r.delta_sec == 0


def test_pace_on_target_slow_boundary():
    """4'35" 剛好等於慢端 → 仍算達標。"""
    r = sm.evaluate_pace("4'35\"", "(425-435/km)")
    assert r.verdict == "on_target"


def test_pace_faster():
    """4'20"=260s < 快端 4'25"=265s → 偏快 5 秒。"""
    r = sm.evaluate_pace("4'20\"", "10-12k P'425-435/km")
    assert r.verdict == "faster"
    assert r.delta_sec == 5


def test_pace_another_range():
    r = sm.evaluate_pace("5'35\"", "10-12k P'530-540/km")
    assert r.verdict == "on_target"


def test_pace_single_target():
    """單一目標 P'430/km：4'36"=276 > 4'30"=270 → 偏慢 6 秒。"""
    r = sm.evaluate_pace("4'36\"", "10k P'430/km")
    assert r is not None
    assert r.verdict == "slower"
    assert r.delta_sec == 6


def test_pace_interval_text_has_recovery_caveat():
    """間歇課表的判讀文字須提醒：全程均速含恢復、工作段通常更快。"""
    r = sm.evaluate_pace("4'36\"", "800*5-6 (425-435/km)")
    assert "恢復" in r.text or "工作段" in r.text


def test_pace_no_target_freerun():
    assert sm.evaluate_pace("5'00\"", "小明 10-12k FR'") is None


def test_pace_no_target_hrzone():
    assert sm.evaluate_pace("6'00\"", "@AII 10k Z2") is None


def test_pace_no_target_distance_only():
    """只有距離 10-12k、無配速 → None（不可把距離數字誤當配速）。"""
    assert sm.evaluate_pace("5'30\"", "10-12k") is None


def test_pace_actual_unparseable():
    assert sm.evaluate_pace("N/A", "(425-435/km)") is None
    assert sm.evaluate_pace(None, "(425-435/km)") is None
