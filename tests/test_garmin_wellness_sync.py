"""garmin_wellness_sync 純函式測試（不打網路、不 import garth/firebase）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zoneinfo import ZoneInfo

from garmin_wellness_sync import (_local_offset_min, bb_min_max,
                                  build_respiration_fields, build_stress_doc,
                                  stress_hourly_from_values, thin_hr_5min)

TPE = ZoneInfo("Asia/Taipei")


def test_build_stress_doc_full():
    doc = build_stress_doc("2026-07-09", 34, 248 * 60, 312 * 60, 109 * 60, 5 * 60)
    assert doc == {"date": "2026-07-09", "stress": 34, "restMin": 248,
                   "lowMin": 312, "mediumMin": 109, "highMin": 5}


def test_build_stress_doc_negative_overall_means_no_data():
    # Garmin 無資料日 overall 會給 -1/-2，不能寫進去污染統計
    doc = build_stress_doc("2026-07-01", -1, None, None, None, None)
    assert doc == {"date": "2026-07-01"}


def test_build_stress_doc_partial_fields_omitted_not_null():
    doc = build_stress_doc("2026-07-02", 40, 100 * 60, None, None, None)
    assert "lowMin" not in doc and "highMin" not in doc
    assert doc["restMin"] == 100


def test_bb_min_max_normal():
    arr = [[0, "x", 55, "y"], [1, "x", 24, "y"], [2, "x", 40, "y"]]
    assert bb_min_max(arr) == (24, 55)


def test_bb_min_max_skips_none_and_short_rows():
    arr = [[0, "x"], [1, "x", None, "y"], [2, "x", 30, "y"]]
    assert bb_min_max(arr) == (30, 30)


def test_bb_min_max_empty():
    assert bb_min_max(None) == (None, None)
    assert bb_min_max([]) == (None, None)


def test_build_respiration_fields_full():
    # 2026-07-08 實測回應形狀（時間戳尾端有 ".0" 要去掉）
    resp = {
        "avgSleepRespirationValue": 17.0,
        "avgWakingRespirationValue": 16.0,
        "sleepStartTimestampLocal": "2026-07-07T23:07:15.0",
        "sleepEndTimestampLocal": "2026-07-08T07:09:47.0",
    }
    assert build_respiration_fields(resp) == {
        "sleepRespiration": 17.0,
        "wakeRespiration": 16.0,
        "sleepStartLocal": "2026-07-07T23:07:15",
        "sleepEndLocal": "2026-07-08T07:09:47",
    }


def test_build_respiration_fields_negative_and_missing_omitted():
    # 負值＝Garmin 無資料，不寫；缺 key 也不寫（省略而非 null）
    resp = {"avgSleepRespirationValue": -1.0, "avgWakingRespirationValue": None}
    assert build_respiration_fields(resp) == {}
    assert build_respiration_fields(None) == {}
    assert build_respiration_fields({}) == {}


def test_stress_hourly_basic_bucketing():
    # 台北 2026-07-08 00:00 = epoch 1783440000000 ms
    base = 1783440000000
    hour_ms = 3600 * 1000
    arr = [
        [base, 20], [base + 180 * 1000, 30],          # 00 時 → avg 25
        [base + hour_ms, 40],                          # 01 時 → 40
        [base + 2 * hour_ms, -1],                      # 02 時只有無效值 → None
    ]
    result = stress_hourly_from_values(arr, tz=TPE)
    assert len(result) == 24
    assert result[0] == 25
    assert result[1] == 40
    assert result[2] is None
    assert result[3:] == [None] * 21


def test_stress_hourly_skips_bad_rows():
    base = 1783440000000
    arr = [[base], [base, None], [base, -2], [base, 55]]
    result = stress_hourly_from_values(arr, tz=TPE)
    assert result[0] == 55


def test_stress_hourly_empty():
    assert stress_hourly_from_values(None) == [None] * 24
    assert stress_hourly_from_values([]) == [None] * 24


# ── 全天心率抽稀 ──────────────────────────────────────────────────

def test_local_offset_min_utc8():
    # 台北 UTC+8：local 00:00 對到 GMT 前一天 16:00 → 差 480 分鐘
    off = _local_offset_min("2026-07-10T00:00:00.0", "2026-07-09T16:00:00.0")
    assert off == 480


def test_local_offset_min_unparseable_defaults_zero():
    assert _local_offset_min("garbage", "2026-07-09T16:00:00.0") == 0
    assert _local_offset_min(None, None) == 0


def test_thin_hr_5min_buckets_and_averages():
    # 2 分鐘粒度資料落進同一個 5 分鐘桶取平均，offset=0（GMT=local）
    base = 1783468800000  # 2026-07-08T00:00:00Z（整日 0 點，方便驗算分鐘偏移）
    minute_ms = 60_000
    values = [
        [base, 96],
        [base + 2 * minute_ms, 80],
        [base + 4 * minute_ms, 84],       # 三點都在 00:00-00:04 → 桶 0，平均 86.67→87
        [base + 6 * minute_ms, 100],      # 桶 1（分鐘偏移 5）
    ]
    result = thin_hr_5min(values, offset_min=0)
    # 輸出用 map 陣列（非巢狀 [[m,hr],...]）——Firestore 拒絕 array-of-array
    assert result[0] == {"m": 0, "hr": round((96 + 80 + 84) / 3)}
    assert result[1] == {"m": 5, "hr": 100}


def test_thin_hr_5min_skips_none_hr():
    base = 1783468800000
    values = [[base, None], [base, 90]]
    assert thin_hr_5min(values, offset_min=0) == [{"m": 0, "hr": 90}]


def test_thin_hr_5min_wraps_minute_offset_to_day():
    # offset 推到隔天也要 mod 1440 回到 0-1435 範圍
    base = 1783468800000
    values = [[base, 70]]
    result = thin_hr_5min(values, offset_min=1440)
    assert result == [{"m": 0, "hr": 70}]


def test_thin_hr_5min_empty():
    assert thin_hr_5min(None, offset_min=0) == []
    assert thin_hr_5min([], offset_min=0) == []
