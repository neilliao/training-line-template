"""schedule_parser 測試。

重點：P0-B「個人具名課表優先於 @AII 全員」。
真實案例 2026-06-01 D1：同時有 @AII 全員 與「小明、學姊、Angela 10-12k」具名分組，
舊版因 is_all 短路只取全員、漏個人指定。修正後個人具名應優先。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import schedule_parser as sp


# 真實 06/01 D1：@AII 全員 + 小明具名分組（個人指定）
D1_ALL_AND_NAMED = """2026 06/01-06/07
Day1
@AII 40-60min FR'

小明、學姊、Angela
10-12k HR 135-145 bpm

Cooper  Rest
"""

# 純 @AII，小明未被具名分組 → 應取全員
D1_ALL_ONLY = """2026 06/01-06/07
Day1
@All 8k Z2
"""

# 小明在具名分組、無 @AII（回歸：原本就會的情況）
D2_NAMED_ONLY = """2026 06/01-06/07
Day2
小欣、小明、麗芬、VV、祖君
20-30min FR'
"""


def test_named_individual_overrides_all():
    """個人具名課表優先於 @AII 全員。"""
    parsed = sp.parse_schedule(D1_ALL_AND_NAMED)
    d1 = parsed["days"]["D1"]
    assert d1["is_for_me"] is True
    assert "10-12k" in d1["my_workout"], f"應取個人具名 10-12k，實得：{d1['my_workout']!r}"
    assert "全員" not in d1["my_workout"], f"不該 fallback 全員：{d1['my_workout']!r}"


def test_pure_all_uses_all():
    """只有 @AII、小明未具名 → 取全員。"""
    parsed = sp.parse_schedule(D1_ALL_ONLY)
    d1 = parsed["days"]["D1"]
    assert d1["is_for_me"] is True
    assert "8k Z2" in d1["my_workout"]
    assert "全員" in d1["my_workout"]


def test_named_group_workout_regression():
    """小明在具名分組、無 @AII → 取該組課表（不可因重構壞掉）。"""
    parsed = sp.parse_schedule(D2_NAMED_ONLY)
    d2 = parsed["days"]["D2"]
    assert d2["is_for_me"] is True
    assert "20-30min FR'" in d2["my_workout"], f"實得：{d2['my_workout']!r}"
