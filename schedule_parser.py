"""
教練課表解析器
尋找 ATHLETE_NAME 出現的段落，提取每日課表
"""
import os
import re
from datetime import datetime


ATHLETE_NAME = os.getenv("ATHLETE_NAME", "小明")


def _extract_named_workout(day_content: str) -> str:
    """抓 ATHLETE_NAME 在具名分組裡的課表；找不到回 ""。
    支援：名字與課表同行（「小明 10-12k P'530-540」）、名字在分組名單下一行起的多行課表。"""
    lines = day_content.split("\n")
    my_group_lines = []
    in_my_group = False
    my_workout = ""
    for line in lines:
        stripped = line.strip()
        if ATHLETE_NAME in stripped:
            in_my_group = True
            # 情況一：名字與課表同行
            inline = re.sub(rf"{ATHLETE_NAME}\s*[、,]?\s*", "", stripped).strip()
            inline = re.sub(r"^[、,]\s*", "", inline).strip()
            # 個人課表判斷：含數字或配速符號（P'、FR、k、m）
            is_individual_workout = bool(re.search(r"\d|FR|P'|km|Rest|休息", inline))
            if inline and is_individual_workout:
                return inline
            # 名字在群組名單裡，等下一行的課表
            my_group_lines.append(stripped)
        elif in_my_group:
            # 繼續收集課表行（多行：距離、配速、休息…）；空行/新分組/新 D 段即停
            if not stripped or re.match(r"[A-ZＳ]\s*組|D\d|^-{3}", stripped):
                break
            my_group_lines.append(stripped)

    if not my_workout and my_group_lines:
        if len(my_group_lines) >= 2:
            workout_lines = [l for l in my_group_lines[1:] if not re.match(r"^-{3}", l)]
            candidate = "\n".join(workout_lines)
            # 只有名字（無數字/配速符號）= 課表尚未公布
            if candidate and not re.search(r"\d|FR|P'|km|Rest|休息", candidate):
                my_workout = "（待補）"
            else:
                my_workout = candidate
        else:
            my_workout = my_group_lines[0]
    return my_workout


def parse_schedule(raw_text: str) -> dict:
    """
    解析課表文字，回傳結構化資料
    回傳格式：
    {
        "week_range": "2026 04/13-04/19",
        "days": {
            "D1": {"description": "...", "for_me": True/False, "my_workout": "..."},
            ...
        }
    }
    """
    result = {
        "week_range": "",
        "raw": raw_text,
        "days": {},
        "parsed_at": datetime.now().isoformat(),
    }

    # 抓週期範圍
    week_match = re.search(r"(\d{4}\s+\d{2}/\d{2}-\d{2}/\d{2})", raw_text)
    if week_match:
        result["week_range"] = week_match.group(1).strip()

    # 前處理：移除分隔線、統一空白
    clean_text = re.sub(r"[-─ ]{5,}[^\n]*", "", raw_text)   # 移除 --- 和 - - - 分隔線
    clean_text = re.sub(r"[ \t]+\n", "\n", clean_text)      # 移除行尾空白
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)       # 合併多餘空行

    # 切割各 D 段（D1/Day1/DAY1/day1 或週末）
    _day_seg = r"[Dd](?:[Aa][Yy])?\s*\d+"
    day_pattern = re.compile(
        rf"^({_day_seg}|週末[^\n]*)\s*\n(.*?)(?=^{_day_seg}|^週末|\Z)",
        re.DOTALL | re.MULTILINE
    )

    for match in day_pattern.finditer(clean_text):
        raw_key = match.group(1).strip()
        # 統一 key 格式：D1/Day1/DAY1/day1 → D1
        day_key = re.sub(r"(?i)^d(?:ay)?\s*(\d+)$", r"D\1", raw_key)
        day_content = match.group(2).strip()

        # 判斷是否包含「小明」，或是 @All 全員課表
        is_all = bool(re.search(r"@[Aa][Ll][Ll]|@[Aa][Ii][Ii]", day_content))
        is_for_me = ATHLETE_NAME in day_content or is_all

        # 個人具名課表優先於 @AII 全員：先抓 ATHLETE_NAME 的具名分組課表，
        # 找不到才 fallback 全員（修 06/01 D1：@AII 短路蓋掉「小明 10-12k」的 bug）
        my_workout = ""
        if ATHLETE_NAME in day_content:
            my_workout = _extract_named_workout(day_content)
        if not my_workout and is_all:
            all_match = re.search(r"@[Aa][Ll][Ll]\s*(.+)|@[Aa][Ii][Ii]\s*(.+)", day_content)
            if all_match:
                content = (all_match.group(1) or all_match.group(2) or "").strip()
                my_workout = f"（全員）{content}"

        # 判斷是否為休息日：
        # 只有「Rest」獨立成行、或「小明 Rest」才算小明休息
        # 「Rest 小欣」是別人休息，不影響小明
        is_rest = bool(
            re.search(rf"{ATHLETE_NAME}\s*(Rest|休息)", day_content, re.IGNORECASE) or
            re.search(r"^(Rest|休息)\s*$", day_content, re.IGNORECASE | re.MULTILINE)
        )
        # 若已找到我的課表（且不是 Rest 字串），就不算休息
        if my_workout and my_workout.strip().lower() not in ("休息", "rest"):
            is_rest = False

        result["days"][day_key] = {
            "content": day_content,
            "is_for_me": is_for_me,
            "is_rest": is_rest,
            "my_workout": my_workout if not is_rest else "休息",
        }

    return result


def format_schedule_for_line(parsed: dict) -> str:
    """將解析後課表格式化為 LINE 訊息"""
    lines = [
        f"📋 本週課表 {parsed.get('week_range', '')}",
        "─────────────────",
    ]

    days_order = sorted(
        [k for k in parsed["days"].keys() if re.match(r"Day?\d+", k)],
        key=lambda x: int(re.search(r"\d+", x).group())
    )
    weekend_keys = [k for k in parsed["days"].keys() if "週末" in k]

    for day in days_order + weekend_keys:
        info = parsed["days"][day]
        if info["is_for_me"]:
            label = day.replace("週末有氧區訓練", "週末")
            workout = info["my_workout"] or "（查看課表）"
            lines.append(f"• {label}：{workout}")

    lines.append("─────────────────")
    return "\n".join(lines)


if __name__ == "__main__":
    # 快速測試
    sample = open("sample_schedule.txt").read() if __import__("os").path.exists("sample_schedule.txt") else ""
    if sample:
        parsed = parse_schedule(sample)
        print(format_schedule_for_line(parsed))
