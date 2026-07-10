"""
一次性：把 intervals.icu 所有活動存入 Firebase
執行：python3 _backfill_icu.py [YYYY-MM-DD]（可選起始日，預設 2026-01-01）
"""
# 腳本已移入 scripts/，把專案根目錄加回 import path 才能匯入根目錄模組
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import sys
from dotenv import load_dotenv
load_dotenv()

import intervals_client as ic
import firebase_client as fb

start = sys.argv[1] if len(sys.argv) > 1 else "2026-01-01"
from datetime import date
end = date.today().isoformat()

print(f"[backfill] 抓取 {start} ~ {end}")
acts = ic.get_activities_by_range(start, end)
print(f"[backfill] 共 {len(acts)} 筆活動")

saved = skipped = 0
for a in acts:
    summary = ic.format_activity_summary(a)
    ok = fb.save_training_log(summary)
    if ok:
        saved += 1
        print(f"  存入：{summary['date']} {summary['sport']} {summary['name']}")
    else:
        skipped += 1

print(f"\n完成：新存 {saved} 筆，跳過（已存在）{skipped} 筆")
