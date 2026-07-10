"""Garmin 每日壓力＋Body Battery＋睡眠呼吸/睡眠窗＋整點壓力＋全天心率 → Firestore `garmin_wellness` 同步。

- doc id = YYYY-MM-DD，merge:true 冪等；只寫有值的 key（省略而非寫 null）
- 睡眠呼吸：sleepRespiration / wakeRespiration（次/分）＋ sleepStartLocal / sleepEndLocal（入睡時間窗）
- 整點壓力：stress_hourly＝24 格每小時平均（index=當地小時，缺測 null），不存 3 分鐘原始明細
- 全天心率：hr_5min＝[{"m": 分鐘偏移, "hr": hr}, ...]，dailyHeartRate 原始 2 分鐘粒度抽稀成
  5 分鐘桶（省空間，口徑同 wellness-dashboard app.py 的 /api/intraday-hr，唯輸出用分鐘偏移數字
  非 "HH:MM" 字串；用 map 陣列而非 [[m, hr], ...] 巢狀陣列——Firestore 不接受 array-of-array）
- 認證：GARTH_TOKEN env（Vercel）優先，否則 ~/.garth-training-line（本機）
- 例行觸發：poller 每天第一次跑時呼叫 maybe_daily_sync()（_meta 記台北日期防重複）
- 回填：`python garmin_wellness_sync.py 90` 補過去 90 天
"""
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

COLLECTION = "garmin_wellness"
META_DOC = "garmin_wellness_sync"
GARTH_TOKEN_DIR = os.path.expanduser("~/.garth-training-line")
DEFAULT_SYNC_DAYS = 3  # 每日例行往回補 3 天：自癒缺口、覆寫前一天的盤中不完整值

TPE = ZoneInfo("Asia/Taipei")


def _firestore_garth_token():
    """讀 Firestore _meta/garth_token 的最新 token（本機 garth_refresh.py 定時
    續期後寫入）。讀不到回 None。"""
    try:
        import firebase_client as fb
        db = fb._init()
        snap = db.collection("_meta").document("garth_token").get()
        return snap.to_dict().get("token") if snap.exists else None
    except Exception as e:
        print(f"[garmin-sync] 讀 Firestore token 失敗：{e}")
        return None


def _garth():
    """garth lazy import＋認證。失敗回 None（呼叫端靜默略過，不影響 poller 主流程）。

    token 來源優先序（2026-07-10 改）：Firestore _meta/garth_token（本機
    garth_refresh.py 每幾小時續期寫入，永遠最新）→ GARTH_TOKEN env（部署時
    凍結，oauth2 約 24 小時就過期，只當備援）→ 本機 ~/.garth-training-line。
    oauth2 到期後 garth 的自動 exchange 會被 Garmin TLS 指紋防護擋（403），
    serverless 端不自己換發，靠本機續期管線餵新 token。"""
    try:
        import garth
        token = _firestore_garth_token() or os.getenv("GARTH_TOKEN")
        if token:
            garth.client.loads(token)
        else:
            garth.resume(GARTH_TOKEN_DIR)
        return garth
    except Exception as e:
        print(f"[garmin-sync] 認證失敗：{e}")
        return None


def build_stress_doc(calendar_date, overall, rest_s, low_s, medium_s, high_s):
    """單日壓力 doc（純函式）。秒→分鐘取整；overall 負值（Garmin 表示無資料）不寫。"""
    doc = {"date": str(calendar_date)}
    if overall is not None and overall >= 0:
        doc["stress"] = overall
    for v, key in ((rest_s, "restMin"), (low_s, "lowMin"),
                   (medium_s, "mediumMin"), (high_s, "highMin")):
        if v is not None:
            doc[key] = round(v / 60)
    return doc


def bb_min_max(values_array):
    """從 body_battery_values_array 取當日最高/最低（純函式）。無有效值回 None, None。"""
    levels = [row[2] for row in (values_array or [])
              if len(row) > 2 and row[2] is not None]
    if not levels:
        return None, None
    return min(levels), max(levels)


def build_respiration_fields(resp):
    """從 respiration 回應萃取睡眠/清醒呼吸與睡眠時間窗（純函式）。

    負值（Garmin 表示無資料）不寫；時間戳去掉尾端 ".0" 存 ISO 字串。
    """
    doc = {}
    for src, key in (("avgSleepRespirationValue", "sleepRespiration"),
                     ("avgWakingRespirationValue", "wakeRespiration")):
        v = (resp or {}).get(src)
        if v is not None and v >= 0:
            doc[key] = v
    for src, key in (("sleepStartTimestampLocal", "sleepStartLocal"),
                     ("sleepEndTimestampLocal", "sleepEndLocal")):
        v = (resp or {}).get(src)
        if v:
            doc[key] = str(v)[:19]
    return doc


def stress_hourly_from_values(values_array, tz=TPE):
    """3 分鐘級壓力明細 → 24 格每小時平均（純函式）。

    輸入列＝[epoch_ms, stressLevel]；負值＝該時段無測量，跳過。
    回傳固定 24 格陣列（index=當地小時 0-23），整小時無有效值給 None。
    """
    buckets = [[] for _ in range(24)]
    for row in (values_array or []):
        if len(row) < 2 or row[1] is None or row[1] < 0:
            continue
        hour = datetime.fromtimestamp(row[0] / 1000, tz).hour
        buckets[hour].append(row[1])
    return [round(sum(b) / len(b)) if b else None for b in buckets]


def _local_offset_min(local_iso, gmt_iso):
    """dailyHeartRate 回應的 local/GMT 起點時間差（分鐘）；解析不了當 0。
    Garmin 回 '2026-07-10T00:00:00.0' 這種一位小數格式，截前 19 碼再 parse。"""
    try:
        lo = datetime.fromisoformat((local_iso or "")[:19])
        gm = datetime.fromisoformat((gmt_iso or "")[:19])
    except ValueError:
        return 0
    return round((lo - gm).total_seconds() / 60)


def thin_hr_5min(values, offset_min, bucket_min=5):
    """dailyHeartRate 的 heartRateValues（[[epoch_ms, hr], ...]，2 分鐘粒度）
    → [{"m": 分鐘偏移, "hr": 平均hr}, ...] 5 分鐘桶平均（純函式，離線可測）。

    輸出刻意用「list of map」而非 [[m, hr], ...] 巢狀陣列——Firestore 寫入直接拒絕
    array-of-array（"400 Nested arrays are not allowed"，2026-07-10 實測），
    map 陣列則允許，key 縮寫 m/hr 省空間。
    分鐘偏移＝當地時間 0 點起算的分鐘數（0-1435），依 bucket_min 對齊。
    hr 為 null（沒戴錶）的點略過；輸出照時間排序。
    """
    buckets = {}
    for pair in values or []:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        ts, hr = pair[0], pair[1]
        if ts is None or hr is None:
            continue
        local_min = ts // 60000 + offset_min
        buckets.setdefault(local_min // bucket_min, []).append(hr)
    out = []
    for key in sorted(buckets):
        minute_offset = (key * bucket_min) % (24 * 60)
        out.append({"m": minute_offset, "hr": round(sum(buckets[key]) / len(buckets[key]))})
    return out


def _fetch_daily_hr_5min(g, date_str):
    """單日全天心率抽稀（1 次 API）。抓不到/沒資料回空 dict（不影響其他欄位）。"""
    try:
        display_name = (g.client.profile or {}).get("displayName")
        if not display_name:
            return {}
        data = g.connectapi(
            f"/wellness-service/wellness/dailyHeartRate/{display_name}",
            params={"date": date_str},
        ) or {}
        offset = _local_offset_min(data.get("startTimestampLocal"), data.get("startTimestampGMT"))
        points = thin_hr_5min(data.get("heartRateValues"), offset)
        return {"hr_5min": points} if points else {}
    except Exception as e:
        print(f"[garmin-sync] dailyHeartRate {date_str} 失敗：{e}")
        return {}


def _fetch_day_extras(g, date_str):
    """單日睡眠呼吸/睡眠窗＋整點壓力＋全天心率（3 次 API）。單一端點失敗只損失該部分。"""
    doc = {}
    try:
        resp = g.connectapi(f"/wellness-service/wellness/daily/respiration/{date_str}")
        doc.update(build_respiration_fields(resp))
    except Exception as e:
        print(f"[garmin-sync] respiration {date_str} 失敗：{e}")
    try:
        detail = g.connectapi(f"/wellness-service/wellness/dailyStress/{date_str}")
        hourly = stress_hourly_from_values((detail or {}).get("stressValuesArray"))
        if any(v is not None for v in hourly):
            doc["stress_hourly"] = hourly
    except Exception as e:
        print(f"[garmin-sync] dailyStress {date_str} 失敗：{e}")
    doc.update(_fetch_daily_hr_5min(g, date_str))
    return doc


def sync_recent(days=DEFAULT_SYNC_DAYS):
    """抓最近 N 天寫入 Firestore。回傳寫入天數；任何失敗回 0（不 raise）。"""
    g = _garth()
    if g is None:
        return 0
    try:
        import firebase_client as fb
        db = fb._init()

        docs = {}
        # 各階段獨立 try：單一端點/模型失敗只損失該部分，不歸零整次同步
        try:
            for r in g.DailyStress.list(period=days):
                d = build_stress_doc(r.calendar_date, r.overall_stress_level,
                                     r.rest_stress_duration, r.low_stress_duration,
                                     r.medium_stress_duration, r.high_stress_duration)
                docs[d["date"]] = d
        except Exception as e:
            print(f"[garmin-sync] DailyStress 失敗：{e}")
        try:
            # 舊版 garth（<0.5）沒有 DailyBodyBatteryStress，略過不影響其他欄位
            bb_model = getattr(g, "DailyBodyBatteryStress", None)
            for r in (bb_model.list(days=days) if bb_model else []):
                key = str(r.calendar_date)
                doc = docs.setdefault(key, {"date": key})
                lo, hi = bb_min_max(r.body_battery_values_array)
                if lo is not None:
                    doc["bodyBatteryMin"] = lo
                    doc["bodyBatteryMax"] = hi
        except Exception as e:
            print(f"[garmin-sync] BodyBattery 失敗：{e}")

        # 睡眠呼吸/睡眠窗＋整點壓力（逐日 2 次 API）
        today_tpe = datetime.now(TPE).date()
        for i in range(days):
            key = (today_tpe - timedelta(days=i)).isoformat()
            doc = docs.setdefault(key, {"date": key})
            doc.update(_fetch_day_extras(g, key))

        for key, doc in docs.items():
            db.collection(COLLECTION).document(key).set(doc, merge=True)
        print(f"[garmin-sync] 寫入 {len(docs)} 天")
        return len(docs)
    except Exception as e:
        print(f"[garmin-sync] 同步失敗：{e}")
        return 0


def maybe_daily_sync():
    """每台北日只跑一次（_meta 防重複）。給 poller 每次呼叫，成本＝一次 Firestore 讀。"""
    try:
        import firebase_client as fb
        db = fb._init()
        today_tpe = datetime.now(TPE).date().isoformat()
        meta_ref = db.collection("_meta").document(META_DOC)
        snap = meta_ref.get()
        if snap.exists and snap.to_dict().get("date") == today_tpe:
            return False
        n = sync_recent()
        if n > 0:
            meta_ref.set({"date": today_tpe}, merge=True)
        return n > 0
    except Exception as e:
        print(f"[garmin-sync] daily check 失敗：{e}")
        return False


if __name__ == "__main__":
    is_dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    days = int(args[0]) if args else DEFAULT_SYNC_DAYS
    if is_dry_run:
        # 只打 API 印出新欄位，不碰 Firestore
        g = _garth()
        if g is None:
            sys.exit(1)
        today = datetime.now(TPE).date()
        for i in range(days):
            key = (today - timedelta(days=i)).isoformat()
            print(key, _fetch_day_extras(g, key))
    else:
        print(f"回填 {days} 天 → {sync_recent(days=days)} 天寫入")
