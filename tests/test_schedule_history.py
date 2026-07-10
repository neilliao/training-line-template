"""歷史同類課表比較測試（純函式，schedule_history.py）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import schedule_history as sh


# ── workout_signature ──────────────────────────────────────────
def test_signature_interval_extracts_distance_set():
    assert sh.workout_signature("1200*3 + 400*6 P'114-116 r2'45") == "interval:400,1200"


def test_signature_interval_ignores_pace_numbers_order():
    # 同樣是 1200/400 間歇，配速級距不同，signature 仍應相同（同類判斷不比配速）
    a = sh.workout_signature("1200*3 + 400*6 P'114-116")
    b = sh.workout_signature("400*6 + 1200*3 P'100-102")
    assert a == b == "interval:400,1200"


def test_signature_distance_bucket():
    assert sh.workout_signature("10-12k P'530-540/km") == "distance:10-12"
    assert sh.workout_signature("11k") == "distance:10-12"


def test_signature_none_for_freeform_text():
    assert sh.workout_signature("FR' Z2 輕鬆跑") is None
    assert sh.workout_signature("") is None
    assert sh.workout_signature(None) is None


# ── compare_with_history ────────────────────────────────────────
def _log(id_, date, workout, pace, hr, sport="Run"):
    return {"id": id_, "date": date, "schedule_workout": workout,
            "avg_pace": pace, "avg_hr": hr, "sport": sport}


def test_compare_returns_none_when_current_unclassifiable():
    current = {"id": "999", "schedule_workout": "FR' Z2", "avg_pace": "6'00\"", "avg_hr": 150}
    result = sh.compare_with_history(current, [_log("1", "2026-06-01", "FR' Z2", "6'10\"", 152)])
    assert result is None


def test_compare_returns_none_when_no_same_type_sample():
    current = {"id": "999", "schedule_workout": "10-12k P'530-540/km",
               "avg_pace": "5'30\"", "avg_hr": 150}
    history = [_log("1", "2026-06-01", "1200*3 + 400*6", "4'40\"", 165)]
    assert sh.compare_with_history(current, history) is None


def test_compare_computes_pace_and_hr_delta_direction():
    current = {"id": "999", "schedule_workout": "10-12k P'530-540/km",
               "avg_pace": "5'20\"", "avg_hr": 145}
    history = [
        _log("1", "2026-06-01", "10-12k P'530-540/km", "5'40\"", 150),
        _log("2", "2026-05-25", "10-12k P'530-540/km", "5'40\"", 150),
    ]
    result = sh.compare_with_history(current, history)
    assert result is not None
    assert result.matched_count == 2
    # 5'20" = 320s；歷史平均 5'40" = 340s → 快 20 秒（負值）
    assert result.pace_delta_sec == -20
    assert "快 20 秒" in result.pace_text
    # 145 - 150 = -5 → 較低
    assert result.hr_delta_bpm == -5
    assert "低 5" in result.hr_text
    assert result.sample_dates == ["2026-06-01", "2026-05-25"]


def test_compare_excludes_self_and_non_run_sport():
    current = {"id": "999", "schedule_workout": "10-12k P'530-540/km",
               "avg_pace": "5'20\"", "avg_hr": 145}
    history = [
        _log("999", "2026-06-08", "10-12k P'530-540/km", "5'20\"", 145),   # 自己，應排除
        _log("1", "2026-06-01", "10-12k P'530-540/km", "5'40\"", 150, sport="Ride"),  # 非跑步，應排除
        _log("2", "2026-05-25", "10-12k P'530-540/km", "5'45\"", 148),
    ]
    result = sh.compare_with_history(current, history)
    assert result is not None
    assert result.matched_count == 1
    assert result.sample_dates == ["2026-05-25"]


def test_compare_limits_to_max_samples():
    current = {"id": "999", "schedule_workout": "10-12k P'530-540/km",
               "avg_pace": "5'20\"", "avg_hr": 145}
    history = [_log(str(i), f"2026-06-{i:02d}", "10-12k P'530-540/km", "5'40\"", 150)
               for i in range(1, 10)]
    result = sh.compare_with_history(current, history, max_samples=3)
    assert result.matched_count == 3


def test_compare_missing_pace_or_hr_reports_insufficient_text():
    current = {"id": "999", "schedule_workout": "10-12k P'530-540/km",
               "avg_pace": None, "avg_hr": None}
    history = [_log("1", "2026-06-01", "10-12k P'530-540/km", "5'40\"", 150)]
    result = sh.compare_with_history(current, history)
    assert result is not None
    assert result.pace_delta_sec is None
    assert "不足" in result.pace_text
    assert result.hr_delta_bpm is None
    assert "不足" in result.hr_text
