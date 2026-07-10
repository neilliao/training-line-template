import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import garmin_dynamics as gd


RAW = {
    "activityId": 23535187319,
    "startTimeLocal": "2026-07-05 06:21:13",
    "distance": 42665.0,
    "avgGroundContactTime": 270.9,
    "avgVerticalOscillation": 8.01,
    "avgVerticalRatio": 8.78,
    "avgStrideLength": 92.65,
    "avgRespirationRate": 36.86,
    "minRespirationRate": 19.67,
    "maxRespirationRate": 50.92,
    "minTemperature": 17.0,
    "maxTemperature": 27.0,
    "avgPower": 250.0,
    "normPower": 270.0,
    "averageRunningCadenceInStepsPerMinute": 163.75,
}


def test_map_garmin_dynamics_units():
    dyn = gd.map_garmin_dynamics(RAW)
    assert dyn["gct"] == 271          # ms 取整
    assert dyn["vo"] == 8.0           # cm 一位小數
    assert dyn["vratio"] == 8.8
    assert dyn["stride"] == 0.93      # cm → m 兩位小數
    assert dyn["resp"] == 36.9
    assert dyn["respMin"] == 19.7
    assert dyn["respMax"] == 50.9
    assert dyn["tempMin"] == 17.0     # 錶上實測溫度範圍（°C）
    assert dyn["tempMax"] == 27.0
    assert dyn["power"] == 250
    assert dyn["normPower"] == 270
    assert dyn["cadence"] == 164      # Garmin 已是雙腳 spm，不可再 ×2（328 是不可能的步頻）


def test_map_garmin_dynamics_none_fields_pass_through():
    dyn = gd.map_garmin_dynamics({"startTimeLocal": "2026-07-05 06:21:13"})
    assert all(v is None for v in dyn.values())


def test_match_by_date_and_distance():
    acts = [
        {"startTimeLocal": "2026-07-05 06:21:13", "distance": 42665.0},
        {"startTimeLocal": "2026-07-05 05:50:00", "distance": 500.0},
        {"startTimeLocal": "2026-07-04 06:00:00", "distance": 42665.0},
    ]
    # 同一天兩趟距離差很大，各自對到正確那筆
    assert gd.match_garmin_activity(acts, "2026-07-05", 42.67)["distance"] == 42665.0
    assert gd.match_garmin_activity(acts, "2026-07-05", 0.5)["distance"] == 500.0
    # 日期不對就不配
    assert gd.match_garmin_activity(acts, "2026-07-06", 42.67) is None


def test_match_distance_tolerance():
    acts = [{"startTimeLocal": "2026-07-05 06:00:00", "distance": 10000.0}]
    # 5% 容差內配得上
    assert gd.match_garmin_activity(acts, "2026-07-05", 10.3) is not None
    # 超出容差配不上
    assert gd.match_garmin_activity(acts, "2026-07-05", 12.0) is None
    # 短程用絕對 100m 容差（5% 太嚴）
    short = [{"startTimeLocal": "2026-07-05 06:00:00", "distance": 500.0}]
    assert gd.match_garmin_activity(short, "2026-07-05", 0.58) is not None


def test_match_missing_inputs():
    assert gd.match_garmin_activity([], "2026-07-05", 10.0) is None
    assert gd.match_garmin_activity(None, "2026-07-05", 10.0) is None
    assert gd.match_garmin_activity([RAW], "", 10.0) is None
    assert gd.match_garmin_activity([RAW], "2026-07-05", 0) is None


def test_dynamics_for_activity_all_none_returns_none():
    acts = [{"startTimeLocal": "2026-07-05 06:00:00", "distance": 10000.0}]
    # 配得上但沒有任何跑姿欄位 → None（不落地沒意義的空 dict）
    assert gd.dynamics_for_activity("2026-07-05", 10.0, garmin_acts=acts) is None


def test_dynamics_for_activity_happy_path():
    dyn = gd.dynamics_for_activity("2026-07-05", 42.67, garmin_acts=[RAW])
    assert dyn["gct"] == 271
    assert dyn["cadence"] == 164


# ── impactLoad（真實衝擊負荷，2026-07-10 新增） ──

def test_fetch_impact_load_converts_meters_to_km(monkeypatch):
    """實測值：activityId=23535187319，summaryDTO.impactLoad=7540 → 7.54km（與
    Garmin app「衝擊負荷因素」圖表顯示的 7.54 公里吻合）。"""
    class FakeClient:
        def connectapi(self, path, **kwargs):
            assert path == "/activity-service/activity/23535187319"
            return {"summaryDTO": {"impactLoad": 7540.0}}

    monkeypatch.setattr(gd, "_garth_client", lambda: FakeClient())
    assert gd.fetch_impact_load(23535187319) == 7.54


def test_fetch_impact_load_missing_field_returns_none(monkeypatch):
    class FakeClient:
        def connectapi(self, path, **kwargs):
            return {"summaryDTO": {}}

    monkeypatch.setattr(gd, "_garth_client", lambda: FakeClient())
    assert gd.fetch_impact_load(23535187319) is None


def test_fetch_impact_load_no_client_returns_none(monkeypatch):
    monkeypatch.setattr(gd, "_garth_client", lambda: None)
    assert gd.fetch_impact_load(23535187319) is None


def test_fetch_impact_load_no_activity_id_returns_none():
    assert gd.fetch_impact_load(None) is None
    assert gd.fetch_impact_load(0) is None


def test_fetch_impact_load_api_error_returns_none(monkeypatch):
    class FakeClient:
        def connectapi(self, path, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(gd, "_garth_client", lambda: FakeClient())
    assert gd.fetch_impact_load(23535187319) is None


def test_dynamics_for_activity_merges_impact_load_km(monkeypatch):
    """dynamics_for_activity 找到配對的 Garmin 活動後，應併入 impactLoadKm。"""
    monkeypatch.setattr(gd, "fetch_impact_load", lambda act_id: 7.54 if act_id == 23535187319 else None)
    dyn = gd.dynamics_for_activity("2026-07-05", 42.67, garmin_acts=[RAW])
    assert dyn["impactLoadKm"] == 7.54


def test_dynamics_for_activity_impact_load_none_still_returns_other_fields(monkeypatch):
    """impactLoad 抓失敗（沒 token／API 掛）不該連累其他已經抓到的跑姿欄位。"""
    monkeypatch.setattr(gd, "fetch_impact_load", lambda act_id: None)
    dyn = gd.dynamics_for_activity("2026-07-05", 42.67, garmin_acts=[RAW])
    assert dyn["gct"] == 271
    assert dyn["impactLoadKm"] is None
