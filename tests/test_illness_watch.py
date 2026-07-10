"""illness_watch 純函式測試：基準線 / z 分數 / 三色判定 / 資料不足 / 預警卡。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import illness_watch as iw


def _series(value, n=60):
    """n 天全同值序列（配一點波動避免 sigma=0）。

    一半的值偏離 ±2、一半持平 → 中位數＝value、MAD＝1。
    """
    vals = [value] * n
    for i in range(0, n, 4):
        vals[i] = value + 2
    for i in range(2, n, 4):
        vals[i] = value - 2
    return vals


# ── baseline ────────────────────────────────────────────────────────

def test_baseline_returns_median_and_sigma():
    # Arrange：60 個值，中位數 55，MAD=1
    vals = _series(55)

    # Act
    med, sigma = iw.baseline(vals)

    # Assert
    assert med == 55
    assert sigma == pytest.approx(1 * iw.MAD_TO_SIGMA)


def test_baseline_insufficient_samples_returns_none():
    assert iw.baseline(_series(55, n=59)) is None


def test_baseline_ignores_none_gaps():
    # 70 天中夾 10 天缺測，有效 60 天仍可算
    vals = _series(55, n=60)
    with_gaps = vals[:30] + [None] * 10 + vals[30:]
    assert iw.baseline(with_gaps) is not None


def test_baseline_none_gaps_reduce_valid_count():
    # 60 天但有缺測 → 有效值不足 60 → 不判定
    vals = _series(55, n=60)
    vals[5] = None
    assert iw.baseline(vals) is None


def test_baseline_uses_most_recent_60_valid_values():
    # 前面 30 天高值（80）＋ 後面 60 天低值（55）→ 基準線只看最近 60 個
    vals = _series(80, n=30) + _series(55, n=60)
    med, _ = iw.baseline(vals)
    assert med == 55


def test_baseline_zero_mad_falls_back_to_mean_abs_deviation():
    # 超過半數同值 → MAD=0，退回平均絕對偏差
    vals = [55] * 50 + [60] * 10
    med, sigma = iw.baseline(vals)
    assert med == 55
    assert sigma > 0


def test_baseline_all_identical_returns_none():
    # 完全零波動無法衡量偏差 → 不判定
    assert iw.baseline([55] * 60) is None


def test_baseline_empty_or_none_input():
    assert iw.baseline([]) is None
    assert iw.baseline(None) is None


# ── z_score ─────────────────────────────────────────────────────────

def test_z_score_direction():
    assert iw.z_score(60, 55, 2.5) == pytest.approx(2.0)
    assert iw.z_score(50, 55, 2.5) == pytest.approx(-2.0)
    assert iw.z_score(55, 55, 2.5) == 0


# ── classify ────────────────────────────────────────────────────────

def test_classify_three_flags_is_red():
    assert iw.classify([True, True, True]) == iw.LEVEL_RED


def test_classify_two_flags_is_yellow():
    assert iw.classify([True, False, True]) == iw.LEVEL_YELLOW


def test_classify_one_or_zero_flags_is_green():
    assert iw.classify([True, False, False]) == iw.LEVEL_GREEN
    assert iw.classify([False, False, False]) == iw.LEVEL_GREEN


# ── assess ──────────────────────────────────────────────────────────

def _healthy_history():
    return {
        "rhr": _series(55),    # 中位數 55, sigma≈2.97
        "hrv": _series(30),    # 中位數 30
        "resp": _series(15),   # 中位數 15
    }


def test_assess_green_when_all_normal():
    result = iw.assess(_healthy_history(),
                       {"rhr": 55, "hrv": 30, "resp": 15})
    assert result["level"] == iw.LEVEL_GREEN
    assert result["metrics"]["rhr"]["abnormal"] is False


def test_assess_red_when_all_three_abnormal():
    # RHR 大升、HRV 大降、呼吸大升（都超過 2 個等效標準差）
    result = iw.assess(_healthy_history(),
                       {"rhr": 65, "hrv": 20, "resp": 22})
    assert result["level"] == iw.LEVEL_RED
    assert all(result["metrics"][k]["abnormal"] for k in ("rhr", "hrv", "resp"))


def test_assess_yellow_when_two_abnormal():
    result = iw.assess(_healthy_history(),
                       {"rhr": 65, "hrv": 20, "resp": 15})
    assert result["level"] == iw.LEVEL_YELLOW


def test_assess_direction_matters():
    # RHR 大降、HRV 大升、呼吸大降＝好方向偏離，不算異常 → 綠燈
    result = iw.assess(_healthy_history(),
                       {"rhr": 45, "hrv": 45, "resp": 10})
    assert result["level"] == iw.LEVEL_GREEN


def test_assess_missing_today_value_no_judgment():
    result = iw.assess(_healthy_history(),
                       {"rhr": 55, "hrv": None, "resp": 15})
    assert result["level"] == iw.LEVEL_NONE
    assert "hrv" in result["reason"]


def test_assess_insufficient_baseline_no_judgment():
    history = _healthy_history()
    history["resp"] = _series(15, n=30)  # 只有 30 天呼吸資料
    result = iw.assess(history, {"rhr": 55, "hrv": 30, "resp": 15})
    assert result["level"] == iw.LEVEL_NONE
    assert "resp" in result["reason"]


def test_assess_metrics_contain_today_baseline_z():
    result = iw.assess(_healthy_history(),
                       {"rhr": 61, "hrv": 30, "resp": 15})
    m = result["metrics"]["rhr"]
    assert m["today"] == 61
    assert m["baseline"] == 55
    assert m["z"] == pytest.approx((61 - 55) / (1 * iw.MAD_TO_SIGMA), abs=0.01)


# ── build_alert_flex ────────────────────────────────────────────────

def test_alert_flex_red_card_structure():
    result = iw.assess(_healthy_history(),
                       {"rhr": 65, "hrv": 20, "resp": 22})
    flex = iw.build_alert_flex(result)
    assert flex["type"] == "flex"
    assert flex["contents"]["type"] == "bubble"
    header_texts = [c["text"] for c in flex["contents"]["header"]["contents"]]
    assert any("休息" in t for t in header_texts)
    # altText 不超過 LINE 100 字上限
    assert len(flex["altText"]) <= 100


def test_alert_flex_yellow_uses_amber_header():
    import flex_tokens as ft
    result = iw.assess(_healthy_history(),
                       {"rhr": 65, "hrv": 20, "resp": 15})
    flex = iw.build_alert_flex(result)
    assert flex["contents"]["header"]["backgroundColor"] == ft.AMBER_DEEP
