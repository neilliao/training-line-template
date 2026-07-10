"""身體資料全量落地 Firebase（資料主權，正本自持）。

intervals.icu 只即時拉、不落地：活動列表雖存進 training_logs，但只挑了幾個欄位；
逐點 streams、每日 wellness 完全沒存。本模組把「完整原始資料」整包存進 Firestore，
之後 intervals.icu 帳號掛了 / 資料被清，原作者 自己手上仍有正本。

三個新集合：
  - icu_activities/{activity_id}    intervals.icu 活動完整原始 dict（不挑欄位）
  - activity_streams/{activity_id}  逐點 streams 全部 type，JSON→gzip→bytes 存
                                     （>900KB 用 activity_streams/{id}_part2, _part3... 續存）
  - icu_wellness/{date}             每日 wellness 完整原始 dict（CTL/ATL/HRV/睡眠...）

連線複用 firebase_client._init()；intervals 認證複用 intervals_client 的
BASE_URL / _auth()。寫入一律 merge=True，只動這三個新集合，絕不碰
training_logs / schedules 既有欄位。

CLI：
  python data_vault.py --backfill        全量回填（2023-01-01 起）
  python data_vault.py --backfill 30     回填最近 30 天
  python data_vault.py --backfill --dry-run   只印格式不寫 Firestore
"""
import argparse
import gzip
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

# 直接執行本檔（CLI 模式）才需要 .env：INTERVALS_API_KEY 是 intervals_client
# 在 import 當下就讀進模組常數，必須搶在 `import intervals_client` 之前載入，
# 否則 CLI 會用到空字串 API_KEY 打出 401。以 library 被 poller.py 等匯入時，
# 呼叫端早已在自己的入口 load_dotenv() 過，這裡略過即可（也讓沒裝
# python-dotenv 的測試用 python 能單獨 import 本檔跑純函式測試）。
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

import intervals_client as ic
import requests

# ics_builder 只用到 re/datetime，無重依賴，可安心在模組層 import
# （複用它的 parse_week_start，不要另刻一套週起始日解析邏輯）。
import ics_builder

# firebase_client（firebase_admin 依賴較重）一律延遲到函式內 import，
# 讓 clean_for_firestore / chunk_bytes 這類純函式可以在沒裝 firebase_admin
# 的環境（例如跑測試的 python）下被單獨 import，呼應本 repo 既有慣例
# （見 env_snapshot.py / illness_watch.py）。

BACKFILL_START_DATE = "2023-01-01"
STREAM_SLEEP_SEC = 1.5          # 每場 streams 間隔，別打 intervals.icu 太兇
MAX_CHUNK_BYTES = 900_000       # Firestore 單 doc 上限 1MB，gzip bytes 留安全邊界
SCHEMA_VERSION = 1
PROGRESS_EVERY = 20

ACTIVITIES_COLLECTION = "icu_activities"
STREAMS_COLLECTION = "activity_streams"
WELLNESS_COLLECTION = "icu_wellness"
COACH_HISTORY_COLLECTION = "coach_history"
DEFAULT_COACH_HISTORY_PATH = "docs/coach-history/merged-timeline.jsonl"


# ── 純函式：Firestore 資料清理 / bytes 分塊（離線可測，無外部依賴）──────

def clean_for_firestore(obj):
    """遞迴清理任意 JSON 結構使其符合 Firestore 限制，回傳全新物件（不 mutate 原物件）。

    - dict：value 為 None 的 key 整個省略（不是寫 null）；key 一律轉字串
    - list：內含巢狀 list（array-of-array，Firestore 不支援）時，攤平成
      {"0": ..., "1": ...} 形式的 dict；一般 list 則逐一清理，None 元素省略
    - 不支援的型別（例如物件、set）轉字串；str/int/float/bool/bytes 原樣保留
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {
            str(k): clean_for_firestore(v)
            for k, v in obj.items()
            if v is not None
        }
    if isinstance(obj, (list, tuple)):
        if any(isinstance(item, (list, tuple)) for item in obj):
            return {
                str(i): clean_for_firestore(item)
                for i, item in enumerate(obj)
                if item is not None
            }
        return [clean_for_firestore(item) for item in obj if item is not None]
    if isinstance(obj, (str, int, float, bool, bytes)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj
    return str(obj)


def chunk_bytes(data: bytes, chunk_size: int = MAX_CHUNK_BYTES) -> list:
    """把 bytes 切成每塊 <= chunk_size 的清單（純函式）。

    空 bytes 回傳空清單；資料量小於 chunk_size 時回傳單一元素清單。
    """
    if not data:
        return []
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


# ── icu_activities：完整原始活動 dict ──────────────────────────────

def _activity_already_vaulted(activity_id: str) -> bool:
    import firebase_client as fb
    db = fb._init()
    doc = db.collection(ACTIVITIES_COLLECTION).document(str(activity_id)).get()
    return doc.exists and bool(doc.to_dict().get("vault_saved_at"))


def land_activity(activity: dict, dry_run: bool = False) -> bool:
    """把單筆 intervals.icu 活動完整原始 dict 存入 icu_activities。

    回傳 True＝新存（或 dry_run 下「本來會存」），False＝已存在略過。
    """
    activity_id = str(activity.get("id"))
    if not dry_run and _activity_already_vaulted(activity_id):
        return False

    cleaned = clean_for_firestore(dict(activity))
    cleaned["vault_saved_at"] = _now_iso()

    if dry_run:
        print(f"  [dry-run] icu_activities/{activity_id}：{len(cleaned)} 個欄位")
        return True

    import firebase_client as fb
    db = fb._init()
    db.collection(ACTIVITIES_COLLECTION).document(activity_id).set(cleaned, merge=True)
    return True


# ── activity_streams：逐點 streams（gzip + chunk）───────────────────

def _streams_already_vaulted(activity_id: str) -> bool:
    import firebase_client as fb
    db = fb._init()
    doc = db.collection(STREAMS_COLLECTION).document(str(activity_id)).get()
    return doc.exists and bool(doc.to_dict().get("vault_saved_at"))


def land_streams(activity_id, dry_run: bool = False):
    """抓單筆活動全部 stream types，gzip 後存 Firestore（>900KB 自動切塊續存）。

    回傳 meta dict（n_types/n_points/n_chunks/vault_saved_at）；
    該活動沒有 streams 資料時回傳 None。
    """
    activity_id = str(activity_id)
    url = f"{ic.BASE_URL}/activity/{activity_id}/streams"
    resp = requests.get(url, auth=ic._auth(), timeout=30)
    resp.raise_for_status()
    streams = resp.json()
    if not streams:
        return None

    raw = json.dumps(streams).encode("utf-8")
    gz = gzip.compress(raw)
    chunks = chunk_bytes(gz)
    n_points = max((len(s.get("data") or []) for s in streams), default=0)

    meta = {
        "n_types": len(streams),
        "n_points": n_points,
        "n_chunks": len(chunks),
        "schema_version": SCHEMA_VERSION,
        "vault_saved_at": _now_iso(),
    }

    if dry_run:
        print(f"  [dry-run] activity_streams/{activity_id}：{meta} gz_bytes={len(gz)}")
        return meta

    import firebase_client as fb
    db = fb._init()
    main_doc = dict(meta)
    main_doc["gz"] = chunks[0]
    db.collection(STREAMS_COLLECTION).document(activity_id).set(main_doc, merge=True)
    for i, chunk in enumerate(chunks[1:], start=2):
        db.collection(STREAMS_COLLECTION).document(f"{activity_id}_part{i}").set(
            {"gz": chunk, "part": i, "vault_saved_at": meta["vault_saved_at"]},
            merge=True,
        )
    return meta


def read_streams(activity_id):
    """讀回並解壓某活動的 streams（跨 chunk 拼接），回傳原始 API 結構。

    找不到資料回 None。供抽驗/下游使用，不是落地流程本身的一部分。
    """
    import firebase_client as fb
    activity_id = str(activity_id)
    db = fb._init()
    main = db.collection(STREAMS_COLLECTION).document(activity_id).get()
    if not main.exists:
        return None
    main_data = main.to_dict()
    n_chunks = main_data.get("n_chunks", 1)
    gz = main_data.get("gz") or b""
    for i in range(2, n_chunks + 1):
        part = db.collection(STREAMS_COLLECTION).document(f"{activity_id}_part{i}").get()
        if part.exists:
            gz += bytes(part.to_dict().get("gz") or b"")
    if not gz:
        return None
    raw = gzip.decompress(bytes(gz))
    return json.loads(raw)


# ── icu_wellness：每日完整原始 dict ─────────────────────────────────

def land_wellness_range(start_date: str, end_date: str, dry_run: bool = False) -> int:
    """一次範圍查詢批量寫入 icu_wellness。回傳寫入（或 dry_run 下會寫入）的天數。

    範圍夠大時（例如全量回填上千天）逐筆 Firestore 寫入本身要跑好一段時間，
    每 PROGRESS_EVERY 筆印一次進度，避免長時間毫無輸出被誤判成卡死
    （2026-07-10 全量回填實測：這段沒印東西，原作者 查 Firestore 兩次沒變化以為卡住）。
    """
    days = ic.get_wellness(start_date, end_date)
    total = len(days) if days else 0
    print(f"[data_vault] wellness 共 {total} 天")
    if not days:
        return 0

    db = None
    if not dry_run:
        import firebase_client as fb
        db = fb._init()
    n = 0
    for day in days:
        date_str = day.get("id") or day.get("date")
        if not date_str:
            continue
        cleaned = clean_for_firestore(dict(day))
        cleaned["vault_saved_at"] = _now_iso()
        if dry_run:
            print(f"  [dry-run] icu_wellness/{date_str}：{len(cleaned)} 個欄位")
        else:
            db.collection(WELLNESS_COLLECTION).document(str(date_str)).set(cleaned, merge=True)
        n += 1
        if n % PROGRESS_EVERY == 0 or n == total:
            print(f"[data_vault] wellness 進度 {n}/{total}")
    return n


# ── coach_history：教練課表歷史時間軸（merged-timeline.jsonl）───────

def _expand_gap_weeks(gap: dict) -> list:
    """把一段 GAP 區間（after~before）展開成每週一筆缺口週起始日（純函式）。

    例：after=2026-01-12, before=2026-02-23 → 展開成 01-19/01-26/02-02/02-09/02-16
    五筆，讓每一週都能被 doc id 查到「這週就是沒資料」，不是只標一段區間。
    """
    after = date.fromisoformat(gap["after"])
    before = date.fromisoformat(gap["before"])
    weeks = []
    cur = after + timedelta(days=7)
    while cur < before:
        weeks.append(cur.isoformat())
        cur += timedelta(days=7)
    return weeks


def land_coach_history(jsonl_path: str = DEFAULT_COACH_HISTORY_PATH, dry_run: bool = False) -> dict:
    """把教練課表合併時間軸（merged-timeline.jsonl）逐週落地 Firestore coach_history。

    doc id＝週起始日（YYYY-MM-DD）。GAP 標記列（無 week_start，只有 after/before 區間）
    展開成每週一筆缺口紀錄一併寫入，讓查詢某週查不到資料時能分辨「教練那週真的沒發課表」
    還是「漏抓」。merge=True，可重跑冪等。
    """
    db = None
    if not dry_run:
        import firebase_client as fb
        db = fb._init()

    stats = {"weeks_saved": 0, "gap_weeks_saved": 0, "skipped": 0}
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)

            if row.get("source") == "GAP":
                for week_start in _expand_gap_weeks(row):
                    doc = {
                        "week_start": week_start,
                        "source": "GAP",
                        "gap_after": row.get("after"),
                        "gap_before": row.get("before"),
                        "gap_days": row.get("gap_days"),
                        "approx_missing_weeks": row.get("approx_missing_weeks"),
                        "vault_saved_at": _now_iso(),
                    }
                    if dry_run:
                        print(f"  [dry-run] coach_history/{week_start}：GAP（{row.get('after')}~{row.get('before')}）")
                    else:
                        db.collection(COACH_HISTORY_COLLECTION).document(week_start).set(doc, merge=True)
                    stats["gap_weeks_saved"] += 1
                continue

            week_start = row.get("week_start")
            if not week_start:
                stats["skipped"] += 1
                continue
            cleaned = clean_for_firestore(dict(row))
            cleaned["vault_saved_at"] = _now_iso()
            if dry_run:
                print(f"  [dry-run] coach_history/{week_start}：{len(cleaned)} 個欄位（source={row.get('source')}）")
            else:
                db.collection(COACH_HISTORY_COLLECTION).document(week_start).set(cleaned, merge=True)
            stats["weeks_saved"] += 1

    print(
        "[data_vault] coach_history 落地完成："
        f"{stats['weeks_saved']} 週真實資料 + {stats['gap_weeks_saved']} 週 GAP 標記"
        f"（略過 {stats['skipped']} 筆無 week_start），共 "
        f"{stats['weeks_saved'] + stats['gap_weeks_saved']} 筆"
    )
    return stats


# ── coach_history：單週增量落地（教練貼新課表當下觸發）───────────────
#
# land_coach_history 是整批（讀 merged-timeline.jsonl 一次寫完 152 週）；
# 這裡是「教練每次貼課表」的單週增量版本，供 webhook_server.py 在
# fb.save_schedule(parsed) 之後順手呼叫。doc 欄位形狀比照 merged-timeline.jsonl
# 裡 source="firebase" 的既有列（week_start/D1-D7/週末訓練/{人名}_my_workout/
# week_range_firebase/firebase_doc_id），讓 coach_logic_learner.py 讀 coach_history
# 時新舊資料格式一致，不用分兩套解析邏輯。

_DAY_KEY_RE = re.compile(r"^D[1-7]$")


def normalize_schedule_to_coach_history_doc(parsed: dict, week_key: str = None) -> dict:
    """把 schedule_parser.parse_schedule() 的輸出正規化成 coach_history doc 格式（純函式）。

    parsed["week_range"] 解不出週一日期時回 None（呼叫端負責跳過，不寫入垃圾 doc）。
    """
    week_range = parsed.get("week_range", "")
    week_start_date = ics_builder.parse_week_start(week_range)
    if not week_start_date:
        return None

    days = parsed.get("days", {}) or {}
    athlete = os.getenv("ATHLETE_NAME", "小明")

    doc = {
        "week_start": week_start_date.isoformat(),
        "source": "firebase",
        "week_range_firebase": week_range,
    }
    if week_key:
        doc["firebase_doc_id"] = week_key

    my_workout = {}
    for day_key, info in days.items():
        content = (info or {}).get("content", "")
        workout = (info or {}).get("my_workout", "")
        if _DAY_KEY_RE.match(day_key):
            doc[day_key] = content
            my_workout[day_key] = workout
        elif "週末" in day_key:
            doc["週末訓練"] = content
            doc[f"{athlete}_週末my_workout"] = workout

    if my_workout:
        doc[f"{athlete}_my_workout"] = my_workout

    ai_analysis = parsed.get("ai_analysis") or {}
    if ai_analysis.get("goal"):
        doc["ai_analysis_goal"] = ai_analysis["goal"]

    return doc


def land_schedule_week(parsed: dict, week_key: str = None, dry_run: bool = False):
    """單週增量落地：把剛解析完的課表 merge 進 coach_history/{week_start}。

    給 webhook_server.py 在 fb.save_schedule(parsed) 之後呼叫（教練每次貼課表就補一筆），
    讓 coach_logic_learner.py 不用等整批 land_coach_history 重跑就能看到最新一週。
    回傳寫入的 week_start（doc id）；week_range 解不出週一日期時回 None，不寫入。
    """
    doc = normalize_schedule_to_coach_history_doc(parsed, week_key)
    if doc is None:
        print(f"[data_vault] 課表週期無法解析週起始日，略過 coach_history 增量落地：{parsed.get('week_range')!r}")
        return None

    cleaned = clean_for_firestore(doc)
    cleaned["vault_saved_at"] = _now_iso()

    if dry_run:
        print(f"  [dry-run] coach_history/{doc['week_start']}：{len(cleaned)} 個欄位（單週增量）")
        return doc["week_start"]

    import firebase_client as fb
    db = fb._init()
    db.collection(COACH_HISTORY_COLLECTION).document(doc["week_start"]).set(cleaned, merge=True)
    print(f"[data_vault] coach_history/{doc['week_start']} 單週增量落地完成")
    return doc["week_start"]


# ── 回填 CLI：斷點續傳、進度印出 ────────────────────────────────────

def backfill(start_date: str, end_date: str = None, dry_run: bool = False) -> dict:
    """回填指定區間的活動 + streams + wellness。可重跑（已存在且 vault_saved_at
    存在的活動/streams 跳過），streams 逐場間隔 STREAM_SLEEP_SEC 秒。

    回傳統計 dict，供呼叫端印出報告。
    """
    end_date = end_date or date.today().isoformat()
    print(f"[data_vault] 回填區間 {start_date} ~ {end_date}" + ("（dry-run）" if dry_run else ""))
    started_at = time.monotonic()

    activities = ic.get_activities_by_range(start_date, end_date)
    total = len(activities)
    print(f"[data_vault] 共 {total} 筆活動")

    stats = {
        "activities_total": total,
        "activities_saved": 0,
        "activities_skipped": 0,
        "streams_saved": 0,
        "streams_skipped": 0,
        "streams_failed": 0,
        "wellness_days": 0,
    }

    for i, activity in enumerate(activities, start=1):
        activity_id = str(activity.get("id"))

        if land_activity(activity, dry_run=dry_run):
            stats["activities_saved"] += 1
        else:
            stats["activities_skipped"] += 1

        if not dry_run and _streams_already_vaulted(activity_id):
            stats["streams_skipped"] += 1
        else:
            try:
                meta = land_streams(activity_id, dry_run=dry_run)
                if meta:
                    stats["streams_saved"] += 1
                else:
                    stats["streams_skipped"] += 1
            except Exception as e:
                print(f"  [streams] {activity_id} 失敗：{e}")
                stats["streams_failed"] += 1
            time.sleep(STREAM_SLEEP_SEC)

        if i % PROGRESS_EVERY == 0 or i == total:
            print(f"[data_vault] 進度 {i}/{total}")

    stats["wellness_days"] = land_wellness_range(start_date, end_date, dry_run=dry_run)

    elapsed = time.monotonic() - started_at
    stats["elapsed_sec"] = round(elapsed, 1)
    print(
        "[data_vault] 完成："
        f"活動 新存{stats['activities_saved']}/跳過{stats['activities_skipped']}，"
        f"streams 新存{stats['streams_saved']}/跳過{stats['streams_skipped']}"
        f"/失敗{stats['streams_failed']}，"
        f"wellness {stats['wellness_days']} 天，耗時 {stats['elapsed_sec']}s"
    )
    return stats


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="intervals.icu 資料全量落地 Firebase")
    parser.add_argument(
        "--backfill",
        nargs="?",
        const="ALL",
        default=None,
        metavar="DAYS",
        help="回填天數（往回推算），省略天數＝全部歷史（自 %s 起）" % BACKFILL_START_DATE,
    )
    parser.add_argument(
        "--land-coach-history",
        nargs="?",
        const=DEFAULT_COACH_HISTORY_PATH,
        default=None,
        metavar="JSONL_PATH",
        help="把教練課表合併時間軸落地 coach_history（省略路徑＝%s）" % DEFAULT_COACH_HISTORY_PATH,
    )
    parser.add_argument("--dry-run", action="store_true", help="只印格式，不寫 Firestore")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    if args.land_coach_history is not None:
        land_coach_history(args.land_coach_history, dry_run=args.dry_run)
        return

    if args.backfill is None:
        print("用法：python data_vault.py --backfill [days] [--dry-run]")
        print("      python data_vault.py --land-coach-history [jsonl_path] [--dry-run]")
        return

    if args.backfill == "ALL":
        start_date = BACKFILL_START_DATE
    else:
        days = int(args.backfill)
        start_date = (date.today() - timedelta(days=days)).isoformat()

    backfill(start_date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
