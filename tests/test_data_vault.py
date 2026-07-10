"""data_vault 純函式測試（不打網路、不碰 Firestore）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_vault import (
    _expand_gap_weeks,
    chunk_bytes,
    clean_for_firestore,
    land_schedule_week,
    normalize_schedule_to_coach_history_doc,
)


# ── clean_for_firestore ──────────────────────────────────────────

def test_clean_for_firestore_omits_none_values():
    assert clean_for_firestore({"a": 1, "b": None, "c": "x"}) == {"a": 1, "c": "x"}


def test_clean_for_firestore_keeps_falsy_non_none_values():
    # 0 / False / "" 是有意義的資料，只有 None 才省略
    assert clean_for_firestore({"a": 0, "b": False, "c": ""}) == {
        "a": 0, "b": False, "c": "",
    }


def test_clean_for_firestore_nested_dict_omits_none_recursively():
    obj = {"outer": {"keep": 1, "drop": None}, "top_none": None}
    assert clean_for_firestore(obj) == {"outer": {"keep": 1}}


def test_clean_for_firestore_flattens_nested_arrays():
    # array-of-array（如 latlng streams）Firestore 不支援，攤平成 index -> value 的 dict
    obj = {"latlng": [[25.03, 121.5], [25.04, 121.51]]}
    assert clean_for_firestore(obj) == {
        "latlng": {"0": [25.03, 121.5], "1": [25.04, 121.51]}
    }


def test_clean_for_firestore_plain_list_untouched_shape():
    obj = {"hr": [120, 130, None, 140]}
    # None 元素省略，其餘保留為一般 list（非 nested）
    assert clean_for_firestore(obj) == {"hr": [120, 130, 140]}


def test_clean_for_firestore_stringifies_unsupported_types():
    class Weird:
        def __str__(self):
            return "weird-obj"

    assert clean_for_firestore({"x": Weird()}) == {"x": "weird-obj"}
    assert clean_for_firestore({"s": {1, 2, 3}}) == {"s": str({1, 2, 3})}


def test_clean_for_firestore_keys_stringified():
    assert clean_for_firestore({1: "a", 2: "b"}) == {"1": "a", "2": "b"}


def test_clean_for_firestore_does_not_mutate_input():
    original = {"a": 1, "b": None, "nested": {"c": None, "d": 2}}
    snapshot = {"a": 1, "b": None, "nested": {"c": None, "d": 2}}
    clean_for_firestore(original)
    assert original == snapshot


def test_clean_for_firestore_scalars_passthrough():
    assert clean_for_firestore(None) is None
    assert clean_for_firestore(42) == 42
    assert clean_for_firestore(3.14) == 3.14
    assert clean_for_firestore(True) is True
    assert clean_for_firestore("text") == "text"


# ── chunk_bytes ───────────────────────────────────────────────────

def test_chunk_bytes_empty_returns_empty_list():
    assert chunk_bytes(b"") == []
    assert chunk_bytes(None) == []


def test_chunk_bytes_single_chunk_when_under_limit():
    data = b"x" * 100
    chunks = chunk_bytes(data, chunk_size=900_000)
    assert chunks == [data]


def test_chunk_bytes_splits_when_over_limit():
    data = b"a" * 250
    chunks = chunk_bytes(data, chunk_size=100)
    assert len(chunks) == 3
    assert [len(c) for c in chunks] == [100, 100, 50]
    assert b"".join(chunks) == data


def test_chunk_bytes_exact_multiple_of_chunk_size():
    data = b"b" * 200
    chunks = chunk_bytes(data, chunk_size=100)
    assert len(chunks) == 2
    assert b"".join(chunks) == data


# ── _expand_gap_weeks ────────────────────────────────────────────

def test_expand_gap_weeks_single_missing_week():
    gap = {"after": "2025-03-24", "before": "2025-04-07", "gap_days": 14, "approx_missing_weeks": 1}
    assert _expand_gap_weeks(gap) == ["2025-03-31"]


def test_expand_gap_weeks_multi_week_gap():
    gap = {"after": "2026-01-12", "before": "2026-02-23", "gap_days": 42, "approx_missing_weeks": 5}
    assert _expand_gap_weeks(gap) == [
        "2026-01-19", "2026-01-26", "2026-02-02", "2026-02-09", "2026-02-16",
    ]


def test_expand_gap_weeks_no_gap_between_adjacent_weeks():
    # after/before 剛好差 7 天代表沒有缺口週（只是正常週界）
    gap = {"after": "2026-01-05", "before": "2026-01-12"}
    assert _expand_gap_weeks(gap) == []


# ── normalize_schedule_to_coach_history_doc（單週增量落地正規化）───

def _sample_parsed():
    return {
        "week_range": "2026 07/06-07/12",
        "days": {
            "D1": {"content": "@AII 40-60min FR'\n\n小明\nRest", "is_for_me": True,
                   "is_rest": True, "my_workout": "休息"},
            "D4": {"content": "1000*3 P'94-96 R200m3'\n\n小明 選擇性訓練", "is_for_me": True,
                   "is_rest": False, "my_workout": "小明 選擇性訓練"},
            "週末訓練": {"content": "小明 Rest\n修哥 12-15k FR'", "is_for_me": True,
                       "is_rest": True, "my_workout": "休息"},
        },
    }


def test_normalize_schedule_extracts_week_start_from_week_range():
    doc = normalize_schedule_to_coach_history_doc(_sample_parsed())
    assert doc["week_start"] == "2026-07-06"  # 週一
    assert doc["source"] == "firebase"
    assert doc["week_range_firebase"] == "2026 07/06-07/12"


def test_normalize_schedule_maps_day_content_and_my_workout():
    doc = normalize_schedule_to_coach_history_doc(_sample_parsed())
    assert doc["D1"] == "@AII 40-60min FR'\n\n小明\nRest"
    assert doc["D4"] == "1000*3 P'94-96 R200m3'\n\n小明 選擇性訓練"
    assert doc["小明_my_workout"] == {"D1": "休息", "D4": "小明 選擇性訓練"}


def test_normalize_schedule_maps_weekend_key_by_substring_match():
    doc = normalize_schedule_to_coach_history_doc(_sample_parsed())
    assert doc["週末訓練"] == "小明 Rest\n修哥 12-15k FR'"
    assert doc["小明_週末my_workout"] == "休息"


def test_normalize_schedule_includes_firebase_doc_id_when_given():
    doc = normalize_schedule_to_coach_history_doc(_sample_parsed(), week_key="2026_07-06-07-12")
    assert doc["firebase_doc_id"] == "2026_07-06-07-12"


def test_normalize_schedule_omits_firebase_doc_id_when_not_given():
    doc = normalize_schedule_to_coach_history_doc(_sample_parsed())
    assert "firebase_doc_id" not in doc


def test_normalize_schedule_includes_ai_goal_when_present():
    parsed = _sample_parsed()
    parsed["ai_analysis"] = {"goal": "本週維持恢復", "notes": "別加量"}
    doc = normalize_schedule_to_coach_history_doc(parsed)
    assert doc["ai_analysis_goal"] == "本週維持恢復"


def test_normalize_schedule_omits_ai_goal_when_absent():
    doc = normalize_schedule_to_coach_history_doc(_sample_parsed())
    assert "ai_analysis_goal" not in doc


def test_normalize_schedule_unparsable_week_range_returns_none():
    parsed = {"week_range": "（未知週期）", "days": {}}
    assert normalize_schedule_to_coach_history_doc(parsed) is None


# ── land_schedule_week（dry-run 不碰 Firestore）───────────────────

def test_land_schedule_week_dry_run_returns_week_start():
    week_start = land_schedule_week(_sample_parsed(), week_key="2026_07-06-07-12", dry_run=True)
    assert week_start == "2026-07-06"


def test_land_schedule_week_dry_run_unparsable_returns_none():
    parsed = {"week_range": "", "days": {}}
    assert land_schedule_week(parsed, dry_run=True) is None
