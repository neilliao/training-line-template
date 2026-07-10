"""
Firebase Firestore client
Collections:
  - training_logs: 每次訓練紀錄
  - schedules: 每週教練課表
  - weekly_reports: 週報快照
"""
import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

_db = None


def _init():
    global _db
    if _db is None:
        if not firebase_admin._apps:
            # 優先用 JSON 字串（Railway 環境變數），fallback 用本機檔案路徑
            cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
            if cred_json:
                import json
                cred_dict = json.loads(cred_json)
                cred = credentials.Certificate(cred_dict)
            else:
                cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "./serviceAccountKey.json")
                cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        _db = firestore.client()
    return _db


# ── Training Logs ──────────────────────────────────────────

def save_training_log(summary: dict):
    """儲存單次訓練紀錄，以 activity id 為文件 ID 避免重複"""
    db = _init()
    doc_id = str(summary["id"])
    ref = db.collection("training_logs").document(doc_id)
    if ref.get().exists:
        return False  # 已存在，略過
    summary["saved_at"] = datetime.now().isoformat()
    ref.set(summary)
    return True


def get_week_activities(start_date: str, end_date: str) -> list:
    """取得指定日期區間的訓練紀錄（YYYY-MM-DD）"""
    db = _init()
    docs = (
        db.collection("training_logs")
        .where("date", ">=", start_date)
        .where("date", "<=", end_date)
        .stream()
    )
    return [d.to_dict() for d in docs]


def get_last_notified_activity_id():
    """取得上次推播的活動 ID，用於判斷是否有新活動"""
    db = _init()
    ref = db.collection("_meta").document("last_notified")
    doc = ref.get()
    if doc.exists:
        return doc.to_dict().get("activity_id")
    return None


def set_last_notified_activity_id(activity_id: str):
    db = _init()
    db.collection("_meta").document("last_notified").set({
        "activity_id": activity_id,
        "updated_at": datetime.now().isoformat(),
    })


def is_activity_notified(activity_id: str) -> bool:
    """確認某筆活動是否已推播過"""
    db = _init()
    ref = db.collection("_meta").document(f"notified_{activity_id}")
    return ref.get().exists


def set_activity_notified(activity_id: str):
    """標記某筆活動已推播"""
    db = _init()
    db.collection("_meta").document(f"notified_{activity_id}").set({
        "activity_id": activity_id,
        "notified_at": datetime.now().isoformat(),
    })


# ── Schedules ──────────────────────────────────────────────

def save_schedule(parsed: dict):
    """儲存解析後的週課表，以 week_range 為 key"""
    db = _init()
    week_key = parsed.get("week_range", "").replace(" ", "_").replace("/", "-")
    if not week_key:
        week_key = datetime.now().strftime("%Y-W%W")
    ref = db.collection("schedules").document(week_key)
    ref.set(parsed)
    return week_key


def get_schedule(week_key: str):
    db = _init()
    ref = db.collection("schedules").document(week_key)
    doc = ref.get()
    return doc.to_dict() if doc.exists else None


def get_training_log(activity_id: str) -> dict:
    """取得單筆訓練紀錄"""
    db = _init()
    doc = db.collection("training_logs").document(str(activity_id)).get()
    return doc.to_dict() if doc.exists else None


def get_recent_training_logs(limit: int = 40) -> list:
    """取最近 N 筆訓練紀錄（date DESC），供深度分析「歷史同類課表比較」用
    （schedule_history.compare_with_history 篩同類/排除自己）。"""
    db = _init()
    docs = (
        db.collection("training_logs")
        .order_by("date", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    return [d.to_dict() for d in docs]


def get_coach_logic() -> dict:
    """讀 `_meta/coach_logic`（coach_logic_learner.py 持續學習系統輸出），
    供深度分析「目前所處訓練階段」段落讀取 logic_summary / based_on_latest_week。"""
    db = _init()
    doc = db.collection("_meta").document("coach_logic").get()
    return doc.to_dict() if doc.exists else None


def update_schedule_ai_analysis(week_key: str, ai_analysis: dict):
    """更新週課表的 AI 分析結果"""
    db = _init()
    db.collection("schedules").document(week_key).update({"ai_analysis": ai_analysis})


def get_latest_schedule():
    db = _init()
    docs = (
        db.collection("schedules")
        .order_by("parsed_at", direction=firestore.Query.DESCENDING)
        .limit(1)
        .stream()
    )
    for doc in docs:
        return doc.to_dict()
    return None


def get_recent_schedules(limit=8):
    """取最近 N 筆課表（parsed_at DESC），供「依日期挑所屬週」勾稽用。"""
    db = _init()
    docs = (
        db.collection("schedules")
        .order_by("parsed_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    return [doc.to_dict() for doc in docs]


# ── Schedule 勾稽：標記已完成 ──────────────────────────────

def mark_schedule_day_completed(week_key: str, day_key: str, activity_summary: dict):
    """將課表某天標記為已完成，並附上實際訓練摘要"""
    db = _init()
    ref = db.collection("schedules").document(week_key)
    doc = ref.get()
    if not doc.exists:
        return False
    data = doc.to_dict()
    if day_key in data.get("days", {}):
        data["days"][day_key]["completed"] = True
        data["days"][day_key]["actual"] = activity_summary
        ref.set(data)
        return True
    return False


# ── Races ──────────────────────────────────────────────────

DEFAULT_CHECKLIST = [
    {"item": "報名", "done": False},
    {"item": "機票/交通", "done": False},
    {"item": "住宿", "done": False},
    {"item": "跑鞋", "done": False},
    {"item": "跑衣/壓縮褲", "done": False},
    {"item": "補給品（能量膠/電解質）", "done": False},
    {"item": "帽子/墨鏡", "done": False},
    {"item": "賽前訓練計畫", "done": False},
]


def save_race(race: dict) -> str:
    """新增賽事，回傳 race_id"""
    db = _init()
    race["created_at"] = datetime.now().isoformat()
    if "checklist" not in race:
        race["checklist"] = [dict(item) for item in DEFAULT_CHECKLIST]
    ref = db.collection("races").document()
    ref.set(race)
    return ref.id


def get_upcoming_races() -> list:
    """取得未來所有賽事，依日期排序"""
    db = _init()
    from datetime import date
    today = date.today().isoformat()
    docs = (
        db.collection("races")
        .where("date", ">=", today)
        .order_by("date")
        .stream()
    )
    result = []
    for doc in docs:
        d = doc.to_dict()
        d["race_id"] = doc.id
        result.append(d)
    return result


def get_race(race_id: str) -> dict:
    db = _init()
    doc = db.collection("races").document(race_id).get()
    if doc.exists:
        d = doc.to_dict()
        d["race_id"] = doc.id
        return d
    return None


def update_race_checklist(race_id: str, item_name: str, done: bool) -> bool:
    """勾稽賽事檢核表某項目"""
    db = _init()
    ref = db.collection("races").document(race_id)
    doc = ref.get()
    if not doc.exists:
        return False
    data = doc.to_dict()
    checklist = data.get("checklist", [])
    for item in checklist:
        if item["item"] == item_name or item_name in item["item"]:
            item["done"] = done
            break
    else:
        return False
    ref.update({"checklist": checklist})
    return True


def save_daily_advice(date_str: str, workout: str, weather: dict, ai_text: str):
    """儲存每日 AI 課表建議，以日期為文件 ID"""
    db = _init()
    db.collection("daily_ai_advice").document(date_str).set({
        "date": date_str,
        "workout": workout,
        "weather": {
            "t_max": weather.get("t_max"),
            "t_min": weather.get("t_min"),
            "humidity": weather.get("humidity"),
            "rain_pct": weather.get("rain_pct"),
            "comfort": weather.get("comfort", ""),
        },
        "ai_advice": ai_text,
        "saved_at": datetime.now().isoformat(),
    })


def add_race_checklist_item(race_id: str, item_name: str) -> bool:
    """新增自訂檢核項目"""
    db = _init()
    ref = db.collection("races").document(race_id)
    doc = ref.get()
    if not doc.exists:
        return False
    data = doc.to_dict()
    checklist = data.get("checklist", [])
    checklist.append({"item": item_name, "done": False})
    ref.update({"checklist": checklist})
    return True
