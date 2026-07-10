"""ics_builder 純函式測試。

重點：RFC 5545 跳脫與 CRLF、UID 穩定（訂閱刷新=更新不重複）、
休息日/待補跳過、空課表仍回有效空日曆、75 octets 折行不切壞 UTF-8。
"""
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ics_builder as icsb

BASE = date(2026, 7, 6)  # 週一
STAMP = datetime(2026, 7, 10, 0, 0, 0, tzinfo=timezone.utc)


def _day(workout, is_rest=False, is_for_me=True):
    return {"is_for_me": is_for_me, "is_rest": is_rest, "my_workout": workout}


def _unfold(ics: str) -> str:
    """還原 RFC 5545 折行（CRLF + 空白 → 接回），方便斷言內容。"""
    return ics.replace("\r\n ", "")


DAYS = {
    "D1": _day("8-10k Z2"),
    "D2": _day("休息", is_rest=True),
    "D3": _day("", is_for_me=False),
    "D4": _day("1000*3 P'106-108 R200m3' R5'"),
    "D5": _day("（待補）"),
    "D6": _day("12k FR'"),
    "D7": _day("休息", is_rest=True),
}


# ── 基本結構 ─────────────────────────────────────────────

def test_calendar_structure_and_headers():
    ics = icsb.build_schedule_ics(DAYS, BASE, dtstamp=STAMP)
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.endswith("END:VCALENDAR\r\n")
    assert "VERSION:2.0" in ics
    assert "X-WR-CALNAME:跑步課表" in ics
    assert "X-WR-TIMEZONE:Asia/Taipei" in ics


def test_crlf_line_endings_only():
    ics = icsb.build_schedule_ics(DAYS, BASE, dtstamp=STAMP)
    # 去掉 CRLF 後不應殘留任何裸 \n 或 \r
    stripped = ics.replace("\r\n", "")
    assert "\n" not in stripped
    assert "\r" not in stripped


# ── 事件產生：休息日/待補/非本人跳過 ─────────────────────

def test_rest_and_pending_days_skipped():
    ics = _unfold(icsb.build_schedule_ics(DAYS, BASE, dtstamp=STAMP))
    assert ics.count("BEGIN:VEVENT") == 3  # D1、D4、D6
    assert "trainingline-2026-07-06@training-line" in ics  # D1
    assert "trainingline-2026-07-09@training-line" in ics  # D4
    assert "trainingline-2026-07-11@training-line" in ics  # D6
    assert "trainingline-2026-07-07@training-line" not in ics  # D2 休息
    assert "trainingline-2026-07-08@training-line" not in ics  # D3 非本人
    assert "trainingline-2026-07-10@training-line" not in ics  # D5 待補
    assert "待補" not in ics


def test_all_day_event_dates_and_summary():
    ics = _unfold(icsb.build_schedule_ics({"D1": _day("8-10k Z2")}, BASE, dtstamp=STAMP))
    assert "DTSTART;VALUE=DATE:20260706" in ics
    assert "DTEND;VALUE=DATE:20260707" in ics
    assert "SUMMARY:跑步課表：8-10k Z2" in ics


def test_valarm_relative_positive_trigger():
    ics = _unfold(icsb.build_schedule_ics({"D1": _day("8-10k Z2")}, BASE, dtstamp=STAMP))
    assert "BEGIN:VALARM" in ics
    assert "TRIGGER;RELATED=START:PT6H30M" in ics
    # DESCRIPTION 註明 Apple 全天事件預設提醒行為
    assert "09:00" in ics


# ── UID 穩定 ─────────────────────────────────────────────

def test_uid_stable_across_builds():
    a = icsb.build_schedule_ics(DAYS, BASE, dtstamp=STAMP)
    b = icsb.build_schedule_ics(
        DAYS, BASE, dtstamp=datetime(2026, 7, 12, 3, 0, 0, tzinfo=timezone.utc)
    )
    uids_a = [l for l in _unfold(a).split("\r\n") if l.startswith("UID:")]
    uids_b = [l for l in _unfold(b).split("\r\n") if l.startswith("UID:")]
    assert uids_a == uids_b
    assert uids_a == sorted(set(uids_a))  # 無重複


# ── 跳脫 ─────────────────────────────────────────────────

def test_escape_special_chars():
    assert icsb.escape_text("a,b;c\nd\\e") == "a\\,b\\;c\\nd\\\\e"
    assert icsb.escape_text("x\r\ny") == "x\\ny"


def test_summary_escaped_in_output():
    days = {"D1": _day("間歇 200*6, r1'40s; 收操")}
    ics = _unfold(icsb.build_schedule_ics(days, BASE, dtstamp=STAMP))
    assert "SUMMARY:跑步課表：間歇 200*6\\, r1'40s\\; 收操" in ics


def test_multiline_workout_escaped_into_description():
    days = {"D1": _day("10k Z2\n心率壓 150 以下")}
    ics = _unfold(icsb.build_schedule_ics(days, BASE, dtstamp=STAMP))
    assert "DESCRIPTION:10k Z2\\n心率壓 150 以下\\n\\n" in ics


# ── 折行 ─────────────────────────────────────────────────

def test_fold_line_max_75_octets_and_utf8_safe():
    long_workout = "課表內容超長" * 20  # 大量多位元組字元
    ics = icsb.build_schedule_ics({"D1": _day(long_workout)}, BASE, dtstamp=STAMP)
    for line in ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    # 折行還原後內容完整（沒切壞 UTF-8、沒掉字）
    assert long_workout in _unfold(ics)


def test_fold_short_line_untouched():
    assert icsb.fold_line("VERSION:2.0") == "VERSION:2.0"


# ── 空課表 / 兩週 ────────────────────────────────────────

def test_empty_schedule_returns_valid_empty_calendar():
    ics = icsb.build_schedule_ics({}, None, dtstamp=STAMP)
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.endswith("END:VCALENDAR\r\n")
    assert "BEGIN:VEVENT" not in ics
    assert "X-WR-CALNAME:跑步課表" in ics


def test_two_weeks_merged():
    next_days = {"D1": _day("6k E")}
    ics = _unfold(
        icsb.build_schedule_ics(
            {"D1": _day("8k Z2")}, BASE,
            next_days=next_days, next_base_date=date(2026, 7, 13),
            dtstamp=STAMP,
        )
    )
    assert ics.count("BEGIN:VEVENT") == 2
    assert "trainingline-2026-07-06@training-line" in ics
    assert "trainingline-2026-07-13@training-line" in ics


# ── week_range 解析 ──────────────────────────────────────

def test_parse_week_start():
    assert icsb.parse_week_start("2026 07/06-07/12") == date(2026, 7, 6)
    assert icsb.parse_week_start("") is None
    assert icsb.parse_week_start("沒有日期") is None
    assert icsb.parse_week_start("2026 13/99-13/99") is None
