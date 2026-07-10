"""Garmin 跑姿資料（running dynamics）：抓取與比對。

intervals.icu 拿不到的錶上實測欄位（觸地時間/垂直振幅/垂直比/步幅/呼吸/功率），
直接從 Garmin Connect 抓，寫進 Firebase training_logs 的 dynamics 欄位。

認證走 garth（官方已棄置但可用）：GARTH_TOKEN env（Vercel/Actions）優先，
本機 fallback ~/.garth-training-line。取 token 方法見 memory reference_garmin_auth_method。

比對邏輯：Garmin 活動與 intervals 活動沒有共用 ID，用「同一天 + 距離差 <5% 或
<100m」配對（一天多趟時距離是可靠的區分鍵，實測 Gold Coast 當天三趟
42.67/0.5/0.47km 都能分開對上）。

衝擊負荷（impactLoadKm，2026-07-10 新增）：Garmin app「衝擊負荷因素」圖表背後的真實欄位，
只在單筆活動詳情端點 `/activity-service/activity/{id}` 的 `summaryDTO.impactLoad`
才有（批次列表端點沒有），單位公尺，實測 7540 對應 app 顯示 7.54km（活動 i164172593，
Garmin activityId=23535187319，2026-07-09 松山區間歇）。每場活動配對成功後多打一次
這個端點（不是每次列表查詢都要），失敗靜默回 None，不影響其餘跑姿欄位落地。
"""
import os

GARTH_TOKEN_DIR = os.path.expanduser("~/.garth-training-line")
DIST_TOL_PCT = 0.05   # 距離容差 5%
DIST_TOL_MIN_M = 100  # 或絕對 100m（短程活動百分比太嚴）

_client = None


def _garth_client():
    """garth lazy init + cache。沒 token / 沒裝 garth 回 None（呼叫端靜默略過）。
    import 放函式內：本機系統 python3 沒裝 garth，頂層 import 會炸整包。"""
    global _client
    if _client is not None:
        return _client
    try:
        import garth
    except Exception:
        return None
    try:
        token = os.environ.get("GARTH_TOKEN", "")
        if token:
            garth.client.loads(token)
        elif os.path.isdir(GARTH_TOKEN_DIR):
            garth.resume(GARTH_TOKEN_DIR)
        else:
            return None
        _client = garth.client
    except Exception:
        return None
    return _client


def _round1(v):
    return round(v, 1) if v is not None else None


def map_garmin_dynamics(raw: dict) -> dict:
    """Garmin activities list 單筆 → dynamics dict（純函式，離線可測）。

    單位：gct 整數 ms、vo cm 一位小數、vratio % 一位小數、stride 公尺兩位小數、
    resp 次/分一位小數、temp °C 一位小數、power/normPower 整數 W。
    cadence 直接取整——Garmin 的 averageRunningCadenceInStepsPerMinute 已是
    雙腳 spm（實測全馬 163.75），跟 intervals.icu 的單腳值不同，不可再 ×2。
    None 欄位透傳 None（舊錶/短活動可能沒有）。"""
    gct = raw.get("avgGroundContactTime")
    stride = raw.get("avgStrideLength")
    power = raw.get("avgPower")
    norm_power = raw.get("normPower")
    cad = raw.get("averageRunningCadenceInStepsPerMinute")
    return {
        "gct": round(gct) if gct is not None else None,
        "vo": _round1(raw.get("avgVerticalOscillation")),
        "vratio": _round1(raw.get("avgVerticalRatio")),
        "stride": round(stride / 100, 2) if stride is not None else None,
        "resp": _round1(raw.get("avgRespirationRate")),
        "respMin": _round1(raw.get("minRespirationRate")),
        "respMax": _round1(raw.get("maxRespirationRate")),
        "tempMin": _round1(raw.get("minTemperature")),
        "tempMax": _round1(raw.get("maxTemperature")),
        "power": round(power) if power is not None else None,
        "normPower": round(norm_power) if norm_power is not None else None,
        "cadence": round(cad) if cad is not None else None,
    }


def match_garmin_activity(garmin_acts: list, date_str: str, dist_km: float):
    """在 Garmin 活動清單裡找出對應 intervals 活動的那筆（純函式，離線可測）。

    date_str：YYYY-MM-DD；dist_km：intervals 端距離（公里）。
    同一天且距離差 < max(5%, 100m) 的候選中取距離最接近的一筆；沒有回 None。"""
    if not date_str or not dist_km:
        return None
    best, best_diff = None, None
    for a in garmin_acts or []:
        start = (a.get("startTimeLocal") or "")[:10]
        if start != date_str:
            continue
        g_dist = a.get("distance")
        if not g_dist:
            continue
        diff_m = abs(g_dist - dist_km * 1000)
        tol = max(dist_km * 1000 * DIST_TOL_PCT, DIST_TOL_MIN_M)
        if diff_m <= tol and (best_diff is None or diff_m < best_diff):
            best, best_diff = a, diff_m
    return best


def fetch_recent_garmin_runs(limit: int = 20):
    """抓 Garmin 最近的跑步活動原始清單。失敗回 []（呼叫端靜默略過）。"""
    client = _garth_client()
    if client is None:
        return []
    try:
        return client.connectapi(
            "/activitylist-service/activities/search/activities",
            params={"limit": limit, "start": 0, "activityType": "running"}) or []
    except Exception:
        return []


def fetch_impact_load(garmin_activity_id):
    """打單筆活動詳情端點，取真實衝擊負荷（公里，兩位小數）。

    只有這個端點有 summaryDTO.impactLoad（單位公尺），批次列表端點沒有，
    所以每場活動配對成功後要多打一次 API。沒有 activity_id / 沒 garth client /
    呼叫失敗 / 欄位缺都靜默回 None（呼叫端不因此中斷其餘跑姿欄位落地）。"""
    if not garmin_activity_id:
        return None
    client = _garth_client()
    if client is None:
        return None
    try:
        detail = client.connectapi(f"/activity-service/activity/{garmin_activity_id}") or {}
        impact_m = (detail.get("summaryDTO") or {}).get("impactLoad")
        if impact_m is None:
            return None
        return round(impact_m / 1000, 2)
    except Exception:
        return None


def dynamics_for_activity(date_str: str, dist_km: float, garmin_acts: list = None):
    """給一筆 intervals 活動（日期＋距離），回它的 Garmin dynamics dict 或 None。

    garmin_acts 可傳入重用（backfill 逐筆比對時別每筆都打 API）；
    不傳就現抓最近 20 筆。找到對應 Garmin 活動後另打一次詳情端點取
    impactLoadKm（真實衝擊負荷）併入回傳 dict。全部欄位都是 None 的話回 None
    （沒意義不落地）。"""
    if garmin_acts is None:
        garmin_acts = fetch_recent_garmin_runs()
    matched = match_garmin_activity(garmin_acts, date_str, dist_km)
    if not matched:
        return None
    dyn = map_garmin_dynamics(matched)
    dyn["impactLoadKm"] = fetch_impact_load(matched.get("activityId"))
    if all(v is None for v in dyn.values()):
        return None
    return dyn
