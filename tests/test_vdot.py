import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import vdot


def test_anchor_vdot50_paces_match_daniels_table():
    # Daniels 官方表 VDOT 50：T=4'15"/km、M≈4'31"/km、I≈3'55"/km
    assert abs(vdot.pace_sec_per_km(50, vdot.PCT_T) - 255) <= 3
    assert abs(vdot.pace_sec_per_km(50, vdot.PCT_M) - 271) <= 4
    assert abs(vdot.pace_sec_per_km(50, vdot.PCT_I) - 235) <= 6


def test_estimate_vdot_10k_50min():
    # 10K 50:00 大約 VDOT 38-39
    v = vdot.estimate_vdot(10.0, 50.0)
    assert 37.0 <= v <= 40.0


def test_estimate_vdot_marathon_hot_day():
    # 全馬 5:15:18（315.3 分）大約 VDOT 26-30（高溫掉速）
    v = vdot.estimate_vdot(42.2, 315.3)
    assert 26.0 <= v <= 30.0


def test_paces_monotonic():
    # 同一 VDOT 下，E 最慢、R 最快
    v = 38.0
    e = vdot.pace_sec_per_km(v, vdot.PCT_E_LOW)
    m = vdot.pace_sec_per_km(v, vdot.PCT_M)
    t = vdot.pace_sec_per_km(v, vdot.PCT_T)
    i = vdot.pace_sec_per_km(v, vdot.PCT_I)
    r = vdot.pace_sec_per_km(v, vdot.PCT_R)
    assert e > m > t > i > r


def test_training_paces_format():
    paces = vdot.training_paces(38.0)
    assert set(paces) == {"E 輕鬆跑", "M 馬拉松配速", "T 閾值", "I 間歇", "R 重複"}
    assert all("'" in p for p in paces.values())
