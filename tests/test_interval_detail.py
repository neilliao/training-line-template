import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from intervals_client import parse_icu_intervals


def _work(dist, sec, hr=160):
    return {"type": "WORK", "distance": dist, "moving_time": sec, "average_heartrate": hr}


def _rec(sec, dist=50):
    return {"type": "RECOVERY", "distance": dist, "moving_time": sec, "elapsed_time": sec}


def test_work_pace_uses_only_work_segments():
    ivs = [_work(200, 42), _rec(95), _work(200, 40), _rec(95), _work(200, 44)]
    d = parse_icu_intervals(ivs)
    assert d["n_work"] == 3
    assert d["work_dist_m"] == 200
    # (42+40+44)/3 = 42s / 0.2km = 210 s/km = 3'30"
    assert d["avg_work_pace"] == "3'30\""
    assert d["best_work_pace"] == "3'20\""
    assert d["worst_work_pace"] == "3'40\""


def test_standing_rest_detected():
    # 恢復段 95 秒只移動 50m（0.53 m/s）＝站休
    ivs = [_work(200, 42), _rec(95, dist=50), _work(200, 40), _rec(95, dist=50)]
    d = parse_icu_intervals(ivs)
    assert d["recovery_kind"] == "站休"
    assert d["avg_recovery_sec"] == 95


def test_jog_recovery_detected():
    # 恢復段 180 秒移動 400m（2.2 m/s）＝緩跑
    ivs = [_work(400, 100), {"type": "RECOVERY", "distance": 400, "moving_time": 180, "elapsed_time": 180},
           _work(400, 98), {"type": "RECOVERY", "distance": 400, "moving_time": 180, "elapsed_time": 180}]
    d = parse_icu_intervals(ivs)
    assert d["recovery_kind"] == "緩跑"


def test_single_work_returns_none():
    assert parse_icu_intervals([_work(200, 42)]) is None
    assert parse_icu_intervals([]) is None
    assert parse_icu_intervals(None) is None


def test_autolap_continuous_run_returns_none():
    # 連續跑開自動分圈：每個 lap 都是 WORK、沒有 RECOVERY → 不是間歇，
    # 不能讓 AI 把穩定跑當間歇課評（6/21 10k 實例）
    ivs = [_work(1000, 390, hr=169) for _ in range(9)]
    assert parse_icu_intervals(ivs) is None


def test_tiny_work_segments_skipped():
    # <50m 的 WORK 是雜訊（自動分圈邊角），不算組
    ivs = [_work(30, 8), _work(200, 42), _rec(90), _work(200, 40)]
    d = parse_icu_intervals(ivs)
    assert d["n_work"] == 2


def _iv(t, dist, moving, elapsed, hr):
    return {"type": t, "distance": dist, "moving_time": moving,
            "elapsed_time": elapsed, "average_heartrate": hr}


# 2026-07-09 松山區間歇（i164172593）icu_intervals 實資料：
# 實跑 400/200/走200/400/200/走200/1000(休5分)/200x6，icu 把走路段標成 WORK、
# 把 1000 拆成 400+400+200 三個連續 lap。
REAL_20260709 = [
    _iv("WORK", 405, 106, 106, 168), _iv("WORK", 226, 61, 164, 160),
    _iv("WORK", 201, 125, 125, 158),          # 走路段被誤標 WORK（10'21"/km）
    _iv("RECOVERY", 14, 76, 76, 138),
    _iv("WORK", 401, 105, 105, 165), _iv("WORK", 12, 9, 18, 182),
    _iv("WORK", 203, 50, 140, 159), _iv("RECOVERY", 243, 181, 246, 158),
    _iv("WORK", 400, 112, 112, 167), _iv("WORK", 400, 121, 121, 184),
    _iv("WORK", 200, 56, 56, 186),            # ↑三段連續＝同一趟 1000m
    _iv("RECOVERY", 238, 294, 294, 143),
    _iv("WORK", 199, 45, 45, 157), _iv("RECOVERY", 27, 101, 107, 157),
    _iv("WORK", 197, 50, 50, 163), _iv("RECOVERY", 50, 101, 107, 158),
    _iv("WORK", 198, 44, 44, 161), _iv("RECOVERY", 44, 101, 102, 161),
    _iv("WORK", 195, 43, 43, 169), _iv("WORK", 202, 48, 127, 171),
    _iv("RECOVERY", 53, 102, 102, 165), _iv("WORK", 190, 48, 48, 170),
    _iv("WORK", 1, 2, 5, 185),
]


def test_real_20260709_walk_excluded_and_1000_merged():
    d = parse_icu_intervals(REAL_20260709)
    dists = [w["dist_m"] for w in d["work_reps"]]
    # 實跑結構＝400/200/400/200/1000/200x6 共 11 組
    assert d["n_work"] == 11
    assert 1000 in dists                      # 拆圈合併回一趟
    assert 201 not in dists                   # 走路段不算衝的段落
    thousand = next(w for w in d["work_reps"] if w["dist_m"] == 1000)
    assert thousand["sec"] == 289             # 112+121+56
    assert thousand["hr"] == 178              # 時間加權 167/184/186
    # 最慢組＝合併後的 1000m（289 s/km），不再是走路的 10'21"
    assert d["worst_work_pace"] == "4'49\""


def test_pause_inside_lap_not_merged():
    # 相鄰兩個 WORK 但第二段 elapsed >> moving（段內有停）＝真的分開兩組，不可併
    ivs = [_iv("WORK", 405, 106, 106, 168), _iv("WORK", 226, 61, 164, 160),
           _iv("RECOVERY", 50, 95, 95, 140),
           _iv("WORK", 400, 105, 105, 165)]
    d = parse_icu_intervals(ivs)
    assert d["n_work"] == 3
