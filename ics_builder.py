"""課表 → iCalendar (.ics) 組裝器（純函式，無 I/O）。

供 webhook_server 的 GET /schedule.ics 訂閱端點使用：
webhook 負責讀 Firebase 課表 + token 認證，這裡只負責把
schedule_parser 產出的 days dict 組成 RFC 5545 文字。

規則：
- 每個非休息日一個全天 VEVENT（休息日/待補/非本人課表跳過）
- UID 用日期組成（trainingline-YYYY-MM-DD@training-line），訂閱刷新時是更新不是重複
- VALARM 用相對正向 TRIGGER PT6H30M（全天事件 DTSTART=00:00 → 當天 06:30 提醒）
- 換行一律 CRLF、文字跳脫與 75 octets 折行照 RFC 5545
"""
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

CRLF = "\r\n"
PRODID = "-//training-line//schedule//ZH"
CAL_NAME = "跑步課表"
CAL_TZ = "Asia/Taipei"
UID_SUFFIX = "@training-line"
# 全天事件 DTSTART 為當日 00:00，正向 6.5 小時 = 當天 06:30
ALARM_TRIGGER = "PT6H30M"
ALARM_NOTE = (
    "提醒時間設定為當天 06:30。"
    "若手機日曆不吃自訂提醒時間，Apple 行事曆對全天事件預設 09:00 提醒。"
)
MAX_LINE_OCTETS = 75  # RFC 5545 §3.1：每行含屬性名不超過 75 octets

_WEEK_START_RE = re.compile(r"(\d{4})\s+(\d{2})/(\d{2})")
_PENDING_MARKERS = ("（待補）", "(待補)")


def parse_week_start(week_range: str) -> Optional[date]:
    """從課表 week_range（例：「2026 07/06-07/12」）取 D1（週一）日期。"""
    m = _WEEK_START_RE.search(week_range or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def escape_text(value: str) -> str:
    """RFC 5545 §3.3.11 TEXT 跳脫：反斜線、分號、逗號、換行。"""
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def fold_line(line: str) -> str:
    """RFC 5545 §3.1 折行：每行 ≤75 octets，續行為 CRLF + 單一空白。

    以 UTF-8 位元組計，且不可切在多位元組字元中間。
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= MAX_LINE_OCTETS:
        return line

    parts = []
    remaining = encoded
    is_first = True
    while remaining:
        # 續行開頭的空白也佔 1 octet
        limit = MAX_LINE_OCTETS if is_first else MAX_LINE_OCTETS - 1
        chunk = remaining[:limit]
        # 別切在 UTF-8 continuation byte（0b10xxxxxx）中間
        while chunk and len(chunk) < len(remaining) and (remaining[len(chunk)] & 0xC0) == 0x80:
            chunk = chunk[:-1]
        parts.append(("" if is_first else " ") + chunk.decode("utf-8"))
        remaining = remaining[len(chunk):]
        is_first = False
    return CRLF.join(parts)


def _is_trainable(info: dict) -> bool:
    """非休息、屬於本人、且有實際課表內容才產生事件。"""
    if not info.get("is_for_me", False):
        return False
    if info.get("is_rest", False):
        return False
    workout = (info.get("my_workout") or "").strip()
    if not workout or workout in _PENDING_MARKERS:
        return False
    return True


def _iter_week_events(days: dict, base_date: date):
    """依 D1–D7 走訪一週，yield (日期, 課表文字)。"""
    for i in range(7):
        info = (days or {}).get(f"D{i + 1}", {}) or {}
        if not _is_trainable(info):
            continue
        yield base_date + timedelta(days=i), (info.get("my_workout") or "").strip()


def _build_event_lines(day_date: date, workout: str, dtstamp_str: str) -> list:
    date_str = day_date.strftime("%Y%m%d")
    next_day_str = (day_date + timedelta(days=1)).strftime("%Y%m%d")
    description = f"{workout}\n\n{ALARM_NOTE}"
    return [
        "BEGIN:VEVENT",
        f"UID:trainingline-{day_date.isoformat()}{UID_SUFFIX}",
        f"DTSTAMP:{dtstamp_str}",
        f"DTSTART;VALUE=DATE:{date_str}",
        f"DTEND;VALUE=DATE:{next_day_str}",
        f"SUMMARY:跑步課表：{escape_text(workout)}",
        f"DESCRIPTION:{escape_text(description)}",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "DESCRIPTION:跑步課表提醒",
        f"TRIGGER;RELATED=START:{ALARM_TRIGGER}",
        "END:VALARM",
        "END:VEVENT",
    ]


def build_schedule_ics(
    days: dict,
    base_date: Optional[date],
    next_days: Optional[dict] = None,
    next_base_date: Optional[date] = None,
    dtstamp: Optional[datetime] = None,
) -> str:
    """把一到兩週課表組成 iCalendar 文字（CRLF 結尾、UTF-8）。

    Args:
        days: 本週 schedule_parser 的 days dict（D1–D7）
        base_date: 本週 D1（週一）日期；None 表示本週沒課表，跳過
        next_days / next_base_date: 下週課表（有才給）
        dtstamp: DTSTAMP 用時間（測試注入用），預設現在 UTC
    """
    stamp = dtstamp or datetime.now(timezone.utc)
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(timezone.utc)
    dtstamp_str = stamp.strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CAL_NAME}",
        f"X-WR-TIMEZONE:{CAL_TZ}",
    ]
    for week_days, week_base in ((days, base_date), (next_days, next_base_date)):
        if week_base is None:
            continue
        for day_date, workout in _iter_week_events(week_days, week_base):
            lines.extend(_build_event_lines(day_date, workout, dtstamp_str))
    lines.append("END:VCALENDAR")

    return CRLF.join(fold_line(line) for line in lines) + CRLF
