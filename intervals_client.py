"""
intervals.icu API client
"""
import os
import statistics
import requests
from datetime import datetime, timedelta

ATHLETE_ID = os.getenv("INTERVALS_ATHLETE_ID", "")
API_KEY = os.getenv("INTERVALS_API_KEY")
BASE_URL = "https://intervals.icu/api/v1"


def _auth():
    return ("API_KEY", API_KEY)


def get_recent_activities(days=1):
    """取得最近 N 天的活動"""
    oldest = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
    url = f"{BASE_URL}/athlete/{ATHLETE_ID}/activities"
    params = {"oldest": oldest}
    resp = requests.get(url, auth=_auth(), params=params)
    resp.raise_for_status()
    return resp.json()


def get_activities_by_range(start_date: str, end_date: str):
    """取得指定日期區間的活動（YYYY-MM-DD）"""
    url = f"{BASE_URL}/athlete/{ATHLETE_ID}/activities"
    params = {
        "oldest": f"{start_date}T00:00:00",
        "newest": f"{end_date}T23:59:59",
    }
    resp = requests.get(url, auth=_auth(), params=params)
    resp.raise_for_status()
    return resp.json()


def get_activity_detail(activity_id):
    """取得單筆活動完整數據"""
    url = f"{BASE_URL}/activity/{activity_id}"
    params = {"intervals": "true"}
    resp = requests.get(url, auth=_auth(), params=params)
    resp.raise_for_status()
    return resp.json()


def get_wellness(start_date: str, end_date: str):
    """取得 wellness 數據（CTL/ATL/TSB）
    date format: YYYY-MM-DD
    """
    url = f"{BASE_URL}/athlete/{ATHLETE_ID}/wellness"
    params = {"oldest": start_date, "newest": end_date}
    resp = requests.get(url, auth=_auth(), params=params)
    resp.raise_for_status()
    return resp.json()


def classify_daily_activities(activities: list) -> list:
    """
    同一天多筆活動，判斷每筆是暖身 / 主課表 / 緩跑
    回傳每筆加上 'role': 'warmup' | 'main' | 'cooldown' | 'standalone'
    """
    runs = [a for a in activities if a.get("type") == "Run"]
    if len(runs) <= 1:
        for a in activities:
            a["role"] = "standalone"
        return activities

    # 依時間排序
    runs.sort(key=lambda a: a.get("start_date_local", ""))

    # 找訓練負荷最高的為主課表
    main_idx = max(range(len(runs)),
                   key=lambda i: runs[i].get("icu_training_load") or runs[i].get("trimp") or 0)

    for i, a in enumerate(runs):
        if i == main_idx:
            a["role"] = "main"
        elif i < main_idx:
            a["role"] = "warmup"
        else:
            a["role"] = "cooldown"

    # 非跑步活動不受影響
    for a in activities:
        if a.get("type") != "Run":
            a["role"] = "standalone"

    return activities


def format_activity_summary(activity: dict) -> dict:
    """將活動數據整理為推播用的摘要"""
    sport = activity.get("type", "Unknown")
    name = activity.get("name", "訓練")
    distance_m = activity.get("distance", 0) or 0
    distance_km = round(distance_m / 1000, 2)
    moving_time_s = activity.get("moving_time", 0) or 0
    moving_time = str(timedelta(seconds=moving_time_s))

    avg_hr = activity.get("average_heartrate")
    max_hr = activity.get("max_heartrate")
    avg_pace_s = (moving_time_s / distance_km) if distance_km > 0 else None
    avg_pace = f"{int(avg_pace_s // 60)}'{int(avg_pace_s % 60):02d}\"" if avg_pace_s else "N/A"

    trimp = activity.get("trimp")
    load = activity.get("training_load")

    date_str = activity.get("start_date_local", "")[:10]

    return {
        "id": activity.get("id"),
        "date": date_str,
        "sport": sport,
        "name": name,
        "distance_km": distance_km,
        "moving_time": moving_time,
        "moving_time_sec": moving_time_s,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "avg_pace": avg_pace,
        "trimp": trimp,
        "load": load,
        # 額外欄位
        "icu_training_load": activity.get("icu_training_load"),
        "average_cadence": activity.get("average_cadence"),
        "average_stride": activity.get("average_stride"),
        "total_elevation_gain": activity.get("total_elevation_gain"),
        "average_temp": activity.get("average_temp"),
        "calories": activity.get("calories"),
        "icu_rpe": activity.get("icu_rpe"),
        "icu_hr_zone_times": activity.get("icu_hr_zone_times"),
        "interval_summary": activity.get("interval_summary"),
        "icu_atl": activity.get("icu_atl"),
        "icu_ctl": activity.get("icu_ctl"),
        "role": activity.get("role", "standalone"),
    }


# ── Cardiac Drift（心率漂移）────────────────────────────────
# 同配速下，跑越久心率越往上飄 = 有氧耐力指標。越小越好。
# 純函式 compute_drift 可獨立測試；get_cardiac_drift 負責抓 stream。

DRIFT_WARMUP_SEC = 300       # 前 5 分鐘暖身爬升期，不計入穩態
DRIFT_MIN_STEADY_SEC = 600   # 穩態段至少 10 分鐘才算
DRIFT_MIN_POINTS = 30
DRIFT_PACE_CV_MAX = 0.20     # 配速變異係數上限，超過視為間歇/變速跑，不算漂移


def compute_drift(time, hr, velocity=None):
    """穩態段後半 median HR - 前半 median HR（bpm）。

    回 int（正值=越跑心率越飄高=有氧不足）或 None（資料不足/間歇/配速不穩）。
    純函式、無外部依賴。
    """
    if not time or not hr:
        return None
    n = min(len(time), len(hr))
    idx = [i for i in range(n)
           if time[i] is not None and hr[i] and time[i] >= DRIFT_WARMUP_SEC]
    if len(idx) < DRIFT_MIN_POINTS:
        return None
    t0, t1 = time[idx[0]], time[idx[-1]]
    if (t1 - t0) < DRIFT_MIN_STEADY_SEC:
        return None

    # 配速穩定性 gate：間歇/變速跑的漂移無意義
    if velocity:
        vs = [velocity[i] for i in idx
              if i < len(velocity) and velocity[i] and velocity[i] > 1.0]
        if len(vs) >= DRIFT_MIN_POINTS:
            mean_v = statistics.mean(vs)
            if mean_v > 0 and statistics.pstdev(vs) / mean_v > DRIFT_PACE_CV_MAX:
                return None

    mid_t = (t0 + t1) / 2
    early = [hr[i] for i in idx if time[i] <= mid_t]
    late = [hr[i] for i in idx if time[i] > mid_t]
    if len(early) < 10 or len(late) < 10:
        return None
    return round(statistics.median(late) - statistics.median(early))


def get_cardiac_drift(activity_id):
    """抓 activity streams 算 cardiac drift，回 int(bpm) 或 None。"""
    url = f"{BASE_URL}/activity/{activity_id}/streams"
    params = {"types": "time,heartrate,velocity_smooth"}
    resp = requests.get(url, auth=_auth(), params=params)
    resp.raise_for_status()
    streams = {s.get("type"): s.get("data") for s in resp.json()}
    return compute_drift(
        streams.get("time"), streams.get("heartrate"), streams.get("velocity_smooth")
    )


# ── 間歇逐組真資料（icu_intervals：WORK/RECOVERY 分段、真距離、真配速） ──

RECOVERY_JOG_SPEED = 1.4  # m/s，恢復段均速高於此＝緩跑，低於＝站休（走路以下）
WALK_AS_WORK_FACTOR = 1.75  # WORK 配速慢於工作段中位數這個倍數＝走路被 icu 誤標，改列恢復
CONTINUOUS_GAP_SEC = 5  # elapsed 與 moving 差在此秒數內＝段內沒停，視為連續（同一趟被拆圈）


def _fmt_pace(sec_per_km):
    if not sec_per_km or sec_per_km <= 0:
        return None
    return f"{int(sec_per_km) // 60}'{int(sec_per_km) % 60:02d}\""


def parse_icu_intervals(icu_intervals: list) -> dict:
    """icu_intervals 原始 list → 間歇結構摘要（純函式，離線可測）。

    回傳 None 表示不是有意義的間歇課（工作段 <2 組，或完全沒有恢復段——
    連續跑開自動分圈時每個 lap 都標 WORK、沒有 RECOVERY，不能當間歇）。否則：
    {
      "n_work": 14, "work_dist_m": 200, "avg_work_pace": "3'29\"",
      "best_work_pace": "3'19\"", "worst_work_pace": "3'40\"",
      "avg_work_hr": 165, "recovery_kind": "站休"|"緩跑"|"混合",
      "avg_recovery_sec": 96,
      "work_reps": [{"dist_m": 204, "sec": 44, "pace": "3'36\"", "hr": 156}, ...]
    }
    組間配速鐵則：只用 WORK 段的真距離/真時間算，恢復段（站休/緩跑）絕不混進配速。

    icu 自動偵測的兩個已知誤判（依實際間歇課資料驗出）在此校正：
    走路段被標成 WORK → 依全場工作段配速中位數剔除改列恢復；
    一趟長間歇被拆成多個連續 lap（如 1000m 拆 400+400+200）→ 合併回一組。
    """
    raw_works, recs = [], []
    for i, iv in enumerate(icu_intervals or []):
        t = iv.get("type")
        dist = iv.get("distance") or 0
        mt = iv.get("moving_time") or iv.get("elapsed_time") or 0
        elapsed = iv.get("elapsed_time") or mt
        if t == "WORK" and dist >= 50 and mt > 0:
            raw_works.append({"dist": dist, "moving": mt, "elapsed": elapsed,
                              "hr": iv.get("average_heartrate"), "idx": i})
        elif t == "RECOVERY" and mt > 0:
            if elapsed < 10:
                continue  # 1-2 秒的假恢復段＝自動分圈 lap 交界雜訊，不是真休息
            speed = dist / elapsed if elapsed else 0
            recs.append({"sec": round(elapsed), "jog": speed >= RECOVERY_JOG_SPEED})

    # 走路誤標校正：配速慢於中位數 1.75 倍的「WORK」不是衝的段落，改列恢復
    if raw_works:
        med = statistics.median(w["moving"] / (w["dist"] / 1000) for w in raw_works)
        kept = []
        for w in raw_works:
            if w["moving"] / (w["dist"] / 1000) > med * WALK_AS_WORK_FACTOR:
                speed = w["dist"] / w["elapsed"] if w["elapsed"] else 0
                recs.append({"sec": round(w["elapsed"]), "jog": speed >= RECOVERY_JOG_SPEED})
            else:
                kept.append(w)
        raw_works = kept

    # 拆圈合併：原始序相鄰（中間沒隔任何段）且兩邊段內都沒停 → 同一趟
    merged = []
    for w in raw_works:
        prev = merged[-1] if merged else None
        if (prev and w["idx"] == prev["idx"] + 1
                and w["elapsed"] - w["moving"] <= CONTINUOUS_GAP_SEC
                and prev["elapsed"] - prev["moving"] <= CONTINUOUS_GAP_SEC):
            if w["hr"] and prev["hr"]:
                prev["hr"] = ((prev["hr"] * prev["moving"] + w["hr"] * w["moving"])
                              / (prev["moving"] + w["moving"]))
            elif w["hr"]:
                prev["hr"] = w["hr"]
            prev["dist"] += w["dist"]
            prev["moving"] += w["moving"]
            prev["elapsed"] += w["elapsed"]
            prev["idx"] = w["idx"]
            continue
        merged.append(dict(w))

    works = []
    for w in merged:
        pace_sec = w["moving"] / (w["dist"] / 1000)
        works.append({"dist_m": round(w["dist"]), "sec": round(w["moving"]),
                      "pace": _fmt_pace(pace_sec), "pace_sec": pace_sec,
                      "hr": round(w["hr"]) if w["hr"] else None})
    if len(works) < 2 or not recs:
        return None

    paces = [w["pace_sec"] for w in works]
    hrs = [w["hr"] for w in works if w["hr"]]
    jogs = sum(1 for r in recs if r["jog"])
    if not recs:
        kind = None
    elif jogs == 0:
        kind = "站休"
    elif jogs == len(recs):
        kind = "緩跑"
    else:
        kind = "混合"

    return {
        "n_work": len(works),
        "work_dist_m": round(sum(w["dist_m"] for w in works) / len(works)),
        "avg_work_pace": _fmt_pace(sum(paces) / len(paces)),
        "best_work_pace": _fmt_pace(min(paces)),
        "worst_work_pace": _fmt_pace(max(paces)),
        "avg_work_hr": round(sum(hrs) / len(hrs)) if hrs else None,
        "recovery_kind": kind,
        "avg_recovery_sec": round(sum(r["sec"] for r in recs) / len(recs)) if recs else None,
        "work_reps": [{k: w[k] for k in ("dist_m", "sec", "pace", "hr")} for w in works],
    }


def get_interval_detail(activity_id):
    """抓單筆活動的間歇逐組真資料。非間歇課或抓取失敗回 None。"""
    url = f"{BASE_URL}/activity/{activity_id}/intervals"
    resp = requests.get(url, auth=_auth(), timeout=15)
    resp.raise_for_status()
    return parse_icu_intervals((resp.json() or {}).get("icu_intervals"))
