"""戶外較佳日排序測試（_outdoor_penalty）。

修 Haiku 跨日數字比較凸槌：training-line 先算好排序塞進摘要，AI 只轉述。
真實案例：明（體感33/1.2mm）應比後天（體感40/5.9mm）更適合戶外。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import weather_client as wc


def test_cooler_drier_day_preferred():
    ming = wc._outdoor_penalty(33, 1.2, 78, 53)      # 明：毛毛雨
    houtian = wc._outdoor_penalty(40, 5.9, 100, 61)  # 後天：體感更高、雨更多
    assert ming < houtian, f"明({ming}) 應優於後天({houtian})"


def test_thunder_heavily_penalized():
    clear = wc._outdoor_penalty(30, 0, 20, 1)
    thunder = wc._outdoor_penalty(30, 0, 20, 95)
    assert thunder >= clear + 20


def test_none_inputs_safe():
    assert wc._outdoor_penalty(None, None, None, None) == 0.0


def test_heat_increases_penalty():
    assert wc._outdoor_penalty(38, 0, 0, 1) > wc._outdoor_penalty(26, 0, 0, 1)
