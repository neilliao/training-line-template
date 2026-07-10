"""生病前兆偵測（Whoop/Oura 式恢復邏輯）。

三指標：靜息心率（intervals.icu wellness `restingHR`）、心率變異（同 `hrv`）、
睡眠呼吸（Firebase `garmin_wellness.sleepRespiration`）。

判定邏輯（純函式，全部可獨立測試）：
- 個人基準線＝最近 60 個有效值（最多回看 90 天）的中位數與 MAD
- 今日偏差 z＝(今日值 − 中位數) / (MAD × 1.4826)（換算成等效標準差）
- 紅色預警＝三項同時異常（RHR z≥2 升、HRV z≤-2 降、睡眠呼吸 z≥2 升）
- 黃色留意＝任兩項異常；其餘＝綠燈
- 基準線有效值不足 60、或任一指標今日缺值 → 不判定（誠實，寧可不報不誤報）

每日流程（maybe_daily_check，由 poller 每輪呼叫）：
- 台北 06:00 前不跑（睡眠資料多半還沒同步上來）
- _meta/illness_watch 記台北日期防重複；今日已判定過直接跳過
- 先便宜檢查今日三值是否到齊（1 次 intervals API＋1 筆 Firestore 讀），
  今日 garmin doc 還沒有 sleepRespiration 時直接打 Garmin respiration 端點補一次；
  任一今日值還沒到 → 本輪放棄、下一輪 poll 再試（不設 meta）
- 到齊才抓 90 天歷史算基準線 → 判定結果（含綠燈）寫進
  `garmin_wellness/{今日}` doc 的 `illness_watch` 欄位（wellness 儀表板讀這裡）
- 紅/黃才推 LINE 預警卡；綠燈不推不吵

本機驗證：`python illness_watch.py`（dry-run：只算不寫不推）。
"""
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import flex_tokens as ft

TPE = ZoneInfo("Asia/Taipei")

HISTORY_DAYS = 90          # 最多回看 90 天
MIN_BASELINE_SAMPLES = 60  # 基準線最少 60 個有效值，不足不判定
MAD_TO_SIGMA = 1.4826      # MAD → 等效標準差（常態分布一致性係數）
Z_ALERT = 2.0              # 異常門檻（等效 2 個標準差）
EARLIEST_CHECK_HOUR = 6    # 台北 06:00 前不判定（睡眠資料未同步）

META_DOC = "illness_watch"
FIELD = "illness_watch"    # 寫進 garmin_wellness/{date} 的欄位名

LEVEL_RED = "red"
LEVEL_YELLOW = "yellow"
LEVEL_GREEN = "green"
LEVEL_NONE = "none"        # 不判定（資料不足）

# 指標定義：(key, 顯示名, 單位, 異常方向)  direction=+1 升異常 / -1 降異常
METRICS = (
    ("rhr",  "靜息心率（RHR）", "bpm",  +1),
    ("hrv",  "心率變異（HRV）", "ms",   -1),
    ("resp", "睡眠呼吸",        "次/分", +1),
)


# ── 純函式：基準線 / z 分數 / 三色判定 ─────────────────────────────

def baseline(values: list):
    """個人基準線：取最近 60 個有效值算中位數與 robust sigma（MAD×1.4826）。

    values 依時間舊→新排列，可含 None（缺測日）。
    有效值不足 60、或波動為 0 無法衡量偏差 → 回 None（不判定）。
    """
    valid = [v for v in (values or []) if v is not None]
    if len(valid) < MIN_BASELINE_SAMPLES:
        return None
    window = valid[-MIN_BASELINE_SAMPLES:]
    med = statistics.median(window)
    mad = statistics.median(abs(v - med) for v in window)
    sigma = mad * MAD_TO_SIGMA
    if sigma == 0:
        # MAD 為 0（超過半數值相同）退回平均絕對偏差；仍為 0 就放棄判定
        mean_ad = sum(abs(v - med) for v in window) / len(window)
        sigma = mean_ad * 1.2533
    if sigma == 0:
        return None
    return med, sigma


def z_score(today, med, sigma):
    """今日偏差（等效標準差數）。"""
    return (today - med) / sigma


def classify(flags: list) -> str:
    """異常旗標 → 三色。三項全異常=紅；任兩項=黃；其餘=綠。"""
    n = sum(1 for f in flags if f)
    if n >= 3:
        return LEVEL_RED
    if n == 2:
        return LEVEL_YELLOW
    return LEVEL_GREEN


def assess(history: dict, today: dict) -> dict:
    """三指標判定主函式（純函式）。

    history = {"rhr": [...], "hrv": [...], "resp": [...]}（舊→新，可含 None，不含今日）
    today   = {"rhr": 63, "hrv": 29.0, "resp": 17.0}（任一可為 None）

    回傳 {"level": red/yellow/green/none, "reason": ...(僅 none), "metrics": {...}}
    metrics 每項＝{"today", "baseline", "z", "abnormal"}。
    """
    missing = [key for key, *_ in METRICS if today.get(key) is None]
    if missing:
        return {"level": LEVEL_NONE, "reason": f"今日缺值：{','.join(missing)}"}

    metrics = {}
    flags = []
    for key, _name, _unit, direction in METRICS:
        base = baseline(history.get(key))
        if base is None:
            return {"level": LEVEL_NONE, "reason": f"基準線資料不足：{key}"}
        med, sigma = base
        z = z_score(today[key], med, sigma)
        abnormal = (z >= Z_ALERT) if direction > 0 else (z <= -Z_ALERT)
        flags.append(abnormal)
        metrics[key] = {
            "today": today[key],
            "baseline": round(med, 1),
            "z": round(z, 2),
            "abnormal": abnormal,
        }
    return {"level": classify(flags), "metrics": metrics}


# ── 預警卡（紅/黃才推）─────────────────────────────────────────────

_HEADLINES = {
    LEVEL_RED: ("身體預警", "三個身體訊號同時異常，可能要生病了，今天建議休息或極輕鬆",
                ft.RED_DEEP),
    LEVEL_YELLOW: ("身體留意", "兩個身體訊號偏離平常，先觀察身體感覺，今天建議降低強度",
                   ft.AMBER_DEEP),
}


def build_alert_flex(result: dict) -> dict:
    """紅/黃判定 → LINE Flex 預警卡（三指標「今日 vs 你的正常值」列＋建議）。"""
    title, headline, header_color = _HEADLINES[result["level"]]
    rows = []
    for key, name, unit, direction in METRICS:
        m = result["metrics"][key]
        if m["abnormal"]:
            note = "偏高" if direction > 0 else "偏低"
            note_color = ft.RED if result["level"] == LEVEL_RED else ft.AMBER
        else:
            note, note_color = "正常", ft.GREEN
        rows.append({
            "type": "box", "layout": "horizontal", "margin": "md",
            "contents": [
                {"type": "text", "text": name, "size": "sm",
                 "color": ft.TEXT_MUTED, "flex": 5},
                {"type": "text",
                 "text": f"{m['today']:g} / 平常 {m['baseline']:g} {unit}",
                 "size": "sm", "color": ft.TEXT_MAIN, "align": "end", "flex": 6},
                {"type": "text", "text": note, "size": "sm", "weight": "bold",
                 "color": note_color, "align": "end", "flex": 2},
            ],
        })

    bubble = {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": header_color, "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": title, "size": "xs",
                 "color": "#FFFFFFCC", "weight": "bold"},
                {"type": "text", "text": headline, "size": "sm",
                 "color": ft.WHITE, "wrap": True, "margin": "sm"},
            ],
        },
        "body": {
            "type": "box", "layout": "vertical",
            "backgroundColor": ft.BG_CARD, "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "今日 vs 你的正常值", "size": "xs",
                 "color": ft.ACCENT, "weight": "bold"},
                *rows,
                {"type": "separator", "margin": "lg", "color": ft.BORDER},
                {"type": "text", "margin": "lg", "size": "xs", "wrap": True,
                 "color": ft.TEXT_MUTED,
                 "text": "基準來自你近 60 天的個人數據。有喉嚨痛、疲倦等症狀請以身體感覺為準。"},
            ],
        },
    }
    return {"type": "flex", "altText": f"{title}：{headline}"[:100],
            "contents": bubble}


# ── 資料收集 ────────────────────────────────────────────────────────

def _today_tpe() -> str:
    return datetime.now(TPE).date().isoformat()


def _fetch_intervals_series(today: str):
    """intervals.icu wellness：回 (rhr_history, hrv_history, today_rhr, today_hrv)。
    history 依日期補洞成連續序列（缺日＝None），不含今日。
    """
    import intervals_client as ic
    start = (datetime.fromisoformat(today).date()
             - timedelta(days=HISTORY_DAYS)).isoformat()
    data = ic.get_wellness(start, today)
    by_date = {d.get("id"): d for d in data}

    rhr_hist, hrv_hist = [], []
    day = datetime.fromisoformat(start).date()
    end = datetime.fromisoformat(today).date()
    while day < end:
        row = by_date.get(day.isoformat()) or {}
        rhr_hist.append(row.get("restingHR"))
        hrv_hist.append(row.get("hrv"))
        day += timedelta(days=1)
    trow = by_date.get(today) or {}
    return rhr_hist, hrv_hist, trow.get("restingHR"), trow.get("hrv")


def _fetch_resp_series(db, today: str):
    """Firebase garmin_wellness：回 (resp_history, today_resp)，history 不含今日。"""
    start = (datetime.fromisoformat(today).date()
             - timedelta(days=HISTORY_DAYS)).isoformat()
    docs = {d.id: d.to_dict() for d in db.collection("garmin_wellness")
            .where("date", ">=", start).where("date", "<=", today).stream()}
    hist = []
    day = datetime.fromisoformat(start).date()
    end = datetime.fromisoformat(today).date()
    while day < end:
        hist.append((docs.get(day.isoformat()) or {}).get("sleepRespiration"))
        day += timedelta(days=1)
    return hist, (docs.get(today) or {}).get("sleepRespiration")


def _today_resp_or_fetch(db, today: str):
    """今日睡眠呼吸：先讀 garmin_wellness doc；還沒有就直接打 Garmin 補一次並寫回。"""
    snap = db.collection("garmin_wellness").document(today).get()
    doc = snap.to_dict() if snap.exists else {}
    v = (doc or {}).get("sleepRespiration")
    if v is not None:
        return v
    try:
        import garmin_wellness_sync as gws
        g = gws._garth()
        if g is None:
            return None
        resp = g.connectapi(f"/wellness-service/wellness/daily/respiration/{today}")
        fields = gws.build_respiration_fields(resp)
        if fields:
            fields["date"] = today
            db.collection("garmin_wellness").document(today).set(fields, merge=True)
        return fields.get("sleepRespiration")
    except Exception as e:
        print(f"[illness] 今日呼吸補抓失敗：{e}")
        return None


def run_assessment(today: str = None) -> dict:
    """抓真實資料跑一次判定（不寫不推）。回傳 assess 結果＋today 日期。"""
    today = today or _today_tpe()
    import firebase_client as fb
    db = fb._init()
    rhr_hist, hrv_hist, t_rhr, t_hrv = _fetch_intervals_series(today)
    resp_hist, t_resp = _fetch_resp_series(db, today)
    result = assess(
        {"rhr": rhr_hist, "hrv": hrv_hist, "resp": resp_hist},
        {"rhr": t_rhr, "hrv": t_hrv, "resp": t_resp},
    )
    result["date"] = today
    return result


# ── 每日流程（poller 每輪呼叫）─────────────────────────────────────

def maybe_daily_check():
    """每台北日判定一次；資料還沒到齊就本輪放棄、下輪再試。回傳是否完成判定。"""
    try:
        now = datetime.now(TPE)
        if now.hour < EARLIEST_CHECK_HOUR:
            return False
        today = now.date().isoformat()

        import firebase_client as fb
        db = fb._init()
        meta_ref = db.collection("_meta").document(META_DOC)
        snap = meta_ref.get()
        if snap.exists and snap.to_dict().get("date") == today:
            return False  # 今天已判定過

        # 先便宜確認今日三值到齊，缺任一就等下一輪（不設 meta）
        rhr_hist, hrv_hist, t_rhr, t_hrv = _fetch_intervals_series(today)
        if t_rhr is None or t_hrv is None:
            print("[illness] 今日 RHR/HRV 未到，下輪再試")
            return False
        t_resp = _today_resp_or_fetch(db, today)
        if t_resp is None:
            print("[illness] 今日睡眠呼吸未到，下輪再試")
            return False

        resp_hist, _ = _fetch_resp_series(db, today)
        result = assess(
            {"rhr": rhr_hist, "hrv": hrv_hist, "resp": resp_hist},
            {"rhr": t_rhr, "hrv": t_hrv, "resp": t_resp},
        )
        result["checked_at"] = datetime.now(TPE).isoformat(timespec="seconds")

        # 判定結果（含綠燈/資料不足）寫進當日 garmin_wellness doc，儀表板讀這裡
        db.collection("garmin_wellness").document(today).set(
            {"date": today, FIELD: result}, merge=True)

        if result["level"] in _HEADLINES:
            import line_notifier as ln
            ln.send_flex(build_alert_flex(result))
            print(f"[illness] {result['level']} 預警已推播")
        else:
            print(f"[illness] 判定 {result['level']}，不推播")

        meta_ref.set({"date": today}, merge=True)
        return True
    except Exception as e:
        print(f"[illness] 每日判定失敗：{e}")
        return False


if __name__ == "__main__":
    # dry-run：抓真實資料算今天的判定，只印不寫不推
    from dotenv import load_dotenv
    load_dotenv()
    import json
    print(json.dumps(run_assessment(), ensure_ascii=False, indent=2))
