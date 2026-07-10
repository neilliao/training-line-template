"""
課表匯入腳本
使用方式：
  python import_schedule.py          ← 等待輸入（貼上課表文字後 Ctrl+D）
  python import_schedule.py --file schedule.txt  ← 從檔案讀取
  python import_schedule.py --text "..."          ← 直接傳入文字
"""
# 腳本已移入 scripts/，把專案根目錄加回 import path 才能匯入根目錄模組
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import os
import sys
import argparse
from dotenv import load_dotenv
load_dotenv()

import firebase_client as fb
import line_notifier as ln
from schedule_parser import parse_schedule, format_schedule_for_line


def run(raw_text: str, notify: bool = True):
    # 解析
    parsed = parse_schedule(raw_text)
    week_range = parsed.get("week_range", "（未識別週期）")
    print(f"解析完成：{week_range}")

    # 列出我的課表
    for day_key, info in parsed["days"].items():
        if info.get("is_for_me"):
            status = "（休息）" if info["is_rest"] else info["my_workout"]
            print(f"  {day_key}: {status}")

    # 存 Firebase
    week_key = fb.save_schedule(parsed)
    print(f"已存入 Firebase，key: {week_key}")

    # 推播 LINE
    if notify:
        msg = format_schedule_for_line(parsed)
        ln.send(msg)
        print("課表推播完成")

    return parsed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="課表文字檔路徑")
    parser.add_argument("--text", help="直接傳入課表文字")
    parser.add_argument("--no-notify", action="store_true", help="不推播 LINE")
    args = parser.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            raw = f.read()
    elif args.text:
        raw = args.text
    else:
        print("請貼上課表文字（貼完後按 Ctrl+D）：")
        raw = sys.stdin.read()

    run(raw, notify=not args.no_notify)
