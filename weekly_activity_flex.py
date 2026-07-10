"""
本週活動 Flex Carousel
Card 1：週總量摘要（亮色 header）
Card 2+：各活動（跑步用 flex_builder，其他用各自模板）
設計系統：與 v2 網頁同色系（mindflows 色票，見 flex_tokens.py）
"""
from datetime import date, timedelta, datetime
import firebase_client as fb
import flex_builder as fb_flex
import flex_tokens as t

WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]

# ── 運動設定：收斂到 mindflows 色系家族，與 flex_builder.SPORT_THEME 同分類邏輯 ──
SPORT_CONFIG = {
    "Run":            {"color": t.WOOD,       "light": t.TINT_WOOD,    "label": "跑步",   "unit": "km"},
    "VirtualRun":     {"color": t.WOOD,       "light": t.TINT_WOOD,    "label": "跑步機", "unit": "km"},
    "Walk":           {"color": t.GREEN_DEEP, "light": t.TINT_GREEN,   "label": "步行",   "unit": "km"},
    "Hike":           {"color": t.GREEN_DEEP, "light": t.TINT_GREEN,   "label": "健行",   "unit": "km"},
    "Ride":           {"color": t.SKY_DEEP,   "light": t.TINT_SKY,     "label": "騎乘",   "unit": "km"},
    "Yoga":           {"color": t.AMBER_DEEP, "light": t.TINT_AMBER,   "label": "瑜伽",   "unit": "min"},
    "Swim":           {"color": t.SKY_DEEP,   "light": t.TINT_SKY,     "label": "游泳",   "unit": "km"},
    "WeightTraining": {"color": t.INK2,       "light": t.TINT_NEUTRAL, "label": "重訓",   "unit": "min"},
    "Workout":        {"color": t.INK2,       "light": t.TINT_NEUTRAL, "label": "訓練",   "unit": "min"},
    "JumpRope":       {"color": t.SKY_DEEP,   "light": t.TINT_SKY,     "label": "跳繩",   "unit": "min"},
}

def _cfg(sport: str) -> dict:
    return SPORT_CONFIG.get(sport, {
        "color": t.INK2, "light": t.TINT_NEUTRAL, "label": sport, "unit": "min"
    })


def _secs_to_hm(secs: int) -> str:
    if not secs:
        return "—"
    h, m = divmod(secs, 3600)
    m = m // 60
    return f"{h}h{m:02d}m" if h else f"{m}min"


def _parse_moving_time(mt) -> int:
    """把 moving_time 字串轉為秒數"""
    try:
        parts = str(mt).split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        pass
    return 0


def _extract_location(name: str, sport: str) -> str:
    """從活動名稱提取地點（移除後綴如「跑步」「步行」）"""
    for suffix in ["跑步", "步行", "騎乘", "游泳", "健行", "訓練"]:
        name = name.replace(suffix, "").strip()
    # 移除日期格式 20260416
    import re
    name = re.sub(r"\s*-?\s*\d{8}", "", name).strip()
    name = re.sub(r"\s*-\s*$", "", name).strip()
    return name if name else ""


# ── Card 1：週總量摘要 ────────────────────────────────────────

def _build_summary_card(logs: list, week_label: str) -> dict:
    from collections import defaultdict

    sport_totals = defaultdict(lambda: {"count": 0, "dist_km": 0.0, "secs": 0})
    active_dates = set()

    for log in logs:
        sport = log.get("sport", "Unknown")
        sport_totals[sport]["count"] += 1
        sport_totals[sport]["dist_km"] += log.get("distance_km") or 0
        sport_totals[sport]["secs"] += _parse_moving_time(log.get("moving_time", ""))
        d = log.get("date", "")
        if d:
            active_dates.add(d)

    total_run_km = sum(
        v["dist_km"] for k, v in sport_totals.items() if k in ("Run", "VirtualRun")
    )
    active_days = len(active_dates)

    # 運動列表行
    sport_rows = []
    for sport, totals in sorted(sport_totals.items()):
        cfg = _cfg(sport)
        color  = cfg["color"]
        label  = cfg["label"]
        count  = totals["count"]
        dist   = totals["dist_km"]
        secs   = totals["secs"]

        vol_parts = []
        if dist > 0:
            vol_parts.append(f"{dist:.1f}km")
        vol_parts.append(_secs_to_hm(secs))
        vol_str = "  ".join(vol_parts)

        sport_rows.append({
            "type": "box", "layout": "horizontal",
            "paddingTop": "9px", "paddingBottom": "9px",
            "paddingStart": "14px", "paddingEnd": "14px",
            "backgroundColor": "#FFFFFF", "cornerRadius": "10px",
            "contents": [
                {"type": "box", "layout": "vertical",
                 "backgroundColor": color, "width": "4px",
                 "cornerRadius": "4px", "contents": [{"type": "filler"}]},
                {"type": "box", "layout": "vertical", "width": "10px", "contents": []},
                {"type": "text", "text": label, "size": "sm",
                 "weight": "bold", "color": t.TEXT_MAIN, "flex": 1},
                {"type": "text", "text": f"{count}次",
                 "size": "xs", "color": t.TEXT_MUTED, "flex": 0},
                {"type": "box", "layout": "vertical", "width": "10px", "contents": []},
                {"type": "text", "text": vol_str, "size": "xs",
                 "color": color, "weight": "bold", "flex": 0, "align": "end"},
            ]
        })

    if not sport_rows:
        sport_rows.append({"type": "text", "text": "本週尚無活動紀錄",
                           "size": "sm", "color": t.TEXT_MUTED, "align": "center"})

    # ── 頂部三格統計 ─────────────────────────────────────────
    def top_stat(label, value, color):
        return {
            "type": "box", "layout": "vertical",
            "backgroundColor": "#FFFFFF26", "cornerRadius": "10px",
            "paddingAll": "10px", "alignItems": "center", "flex": 1,
            "contents": [
                {"type": "text", "text": value, "size": "lg",
                 "weight": "bold", "color": "#FFFFFF", "align": "center"},
                {"type": "text", "text": label, "size": "xxs",
                 "color": "#FFFFFFB3", "align": "center"}
            ]
        }

    run_str   = f"{total_run_km:.1f}km" if total_run_km else "—"
    types_str = f"{len(sport_totals)}種"
    days_str  = f"{active_days}天"

    return {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": t.WOOD,
            "paddingTop": "20px", "paddingBottom": "20px",
            "paddingStart": "18px", "paddingEnd": "18px",
            "contents": [
                {"type": "text", "text": "本週活動",
                 "size": "xxs", "color": "#FFFFFFB3", "weight": "bold"},
                {"type": "text", "text": week_label,
                 "size": "xl", "weight": "bold", "color": "#FFFFFF", "margin": "xs"},
                {
                    "type": "box", "layout": "horizontal",
                    "margin": "lg", "spacing": "sm",
                    "contents": [
                        top_stat("跑量", run_str, t.AMBER),
                        top_stat("活動天", days_str, t.GREEN),
                        top_stat("種類", types_str, t.SKY),
                    ]
                }
            ]
        },
        "body": {
            "type": "box", "layout": "vertical",
            "backgroundColor": t.BG_BODY, "paddingAll": "14px", "spacing": "sm",
            "contents": [
                {"type": "separator", "color": t.BORDER},
                *sport_rows
            ]
        },
        "styles": {
            "header": {"backgroundColor": t.WOOD},
            "body":   {"backgroundColor": t.BG_BODY}
        }
    }


# ── Card：非跑步活動 ──────────────────────────────────────────

def _build_activity_card(log: dict) -> dict:
    sport    = log.get("sport", "Unknown")
    name     = log.get("name", sport)
    date_str = log.get("date", "")
    cfg      = _cfg(sport)
    color    = cfg["color"]
    label    = cfg["label"]

    dist_km  = log.get("distance_km") or 0
    mt_str   = log.get("moving_time", "")
    secs     = _parse_moving_time(mt_str)
    hr       = log.get("avg_hr")
    pace     = log.get("avg_pace", "")
    cals     = log.get("calories")
    location = _extract_location(name, sport)

    # 日期格式化
    weekday_label = ""
    date_display  = date_str
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekday_label = f"週{WEEKDAY_ZH[dt.weekday()]}"
        date_display  = f"{dt.month}/{dt.day}"
    except Exception:
        pass

    # Header 主數字
    if dist_km > 0:
        main_val  = f"{dist_km:.1f}"
        main_unit = "km"
    else:
        main_val  = _secs_to_hm(secs)
        main_unit = ""

    # ── 技術數據格 ────────────────────────────────────────────
    def stat_cell(lbl, val, clr=t.TEXT_MAIN):
        return {
            "type": "box", "layout": "vertical",
            "backgroundColor": "#FFFFFF", "cornerRadius": "10px",
            "paddingTop": "8px", "paddingBottom": "8px",
            "paddingStart": "4px", "paddingEnd": "4px",
            "alignItems": "center", "flex": 1,
            "contents": [
                {"type": "text", "text": val, "size": "xs",
                 "weight": "bold", "color": clr, "align": "center", "wrap": True},
                {"type": "text", "text": lbl, "size": "xxs",
                 "color": t.TEXT_MUTED, "align": "center"}
            ]
        }

    def gap():
        return {"type": "box", "layout": "vertical", "width": "6px", "contents": []}

    cells = []
    if mt_str:
        cells.append(stat_cell("時間", _secs_to_hm(secs)))
    if dist_km > 0 and pace and pace != "N/A":
        cells.append(stat_cell("配速", pace, color))
    if hr:
        cells.append(stat_cell("心率", f"{int(hr)}bpm", t.RED))
    if cals:
        cells.append(stat_cell("消耗", f"{int(cals)}kcal", t.AMBER))

    stats_row = []
    for i, c in enumerate(cells[:4]):
        if i:
            stats_row.append(gap())
        stats_row.append(c)

    # ── 資訊列（日期 + 地點）────────────────────────────────
    info_items = []
    if date_display and weekday_label:
        info_items.append({"type": "text",
                           "text": f"{date_display}  {weekday_label}",
                           "size": "xs", "color": t.TEXT_MUTED, "flex": 0})
    if location:
        if info_items:
            info_items.append({"type": "text", "text": "  ·  ",
                               "size": "xs", "color": t.BORDER, "flex": 0})
        info_items.append({"type": "text", "text": location,
                           "size": "xs", "color": t.TEXT_MUTED, "flex": 1, "wrap": True})

    body_contents = []

    # 運動類型標籤
    body_contents.append({
        "type": "box", "layout": "horizontal",
        "contents": [{
            "type": "box", "layout": "horizontal",
            "backgroundColor": cfg["light"], "cornerRadius": "20px",
            "paddingTop": "3px", "paddingBottom": "3px",
            "paddingStart": "10px", "paddingEnd": "10px", "flex": 0,
            "contents": [{"type": "text", "text": label,
                          "size": "xxs", "color": color, "weight": "bold"}]
        }]
    })

    # 日期 + 地點列
    if info_items:
        body_contents.append({
            "type": "box", "layout": "horizontal",
            "paddingTop": "6px", "paddingBottom": "2px",
            "contents": info_items
        })

    # 技術數據
    if stats_row:
        body_contents.append({
            "type": "box", "layout": "horizontal",
            "spacing": "none", "contents": stats_row
        })

    # ── 天氣（歷史資料查詢）────────────────────────────────────
    wx_emoji = ""
    wx_desc  = ""
    try:
        import weather_client as wc
        wx = wc.get_weather_at_activity(f"{date_str}T09:00:00")
        if wx:
            wx_emoji = wx.get("condition_emoji", "")
            wx_desc  = wx.get("condition", "")
            temp     = wx.get("temp_c")
            if temp is not None:
                wx_desc = f"{wx_emoji} {round(temp)}°C"
            elif wx_emoji:
                wx_desc = wx_emoji
    except Exception:
        pass

    return {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": color,
            "paddingTop": "18px", "paddingBottom": "18px",
            "paddingStart": "18px", "paddingEnd": "18px",
            "contents": [
                # 運動類型 + 天氣（同一行）
                {
                    "type": "box", "layout": "horizontal",
                    "alignItems": "center",
                    "contents": [
                        {"type": "text", "text": label, "size": "xs",
                         "color": "#FFFFFFB3", "weight": "bold", "flex": 1},
                        *([{"type": "text", "text": wx_desc, "size": "xs",
                            "color": "#FFFFFFCC", "flex": 0, "align": "end"}] if wx_desc else [])
                    ]
                },
                # 主數字
                {
                    "type": "box", "layout": "horizontal",
                    "margin": "xs", "alignItems": "flex-end",
                    "contents": [
                        {"type": "text", "text": main_val, "size": "5xl",
                         "weight": "bold", "color": "#FFFFFF", "flex": 0},
                        *([{"type": "text", "text": f"  {main_unit}", "size": "xl",
                            "weight": "bold", "color": "#FFFFFFCC",
                            "gravity": "bottom", "flex": 0}] if main_unit else [])
                    ]
                },
                # 日期 + 地點（純文字，無 badge）
                {
                    "type": "box", "layout": "horizontal",
                    "margin": "sm",
                    "contents": [
                        {"type": "text",
                         "text": "  ".join(filter(None, [date_display, weekday_label, location])),
                         "size": "xs", "color": "#FFFFFFB3", "wrap": True}
                    ]
                }
            ]
        },
        "body": {
            "type": "box", "layout": "vertical",
            "backgroundColor": t.BG_BODY, "paddingAll": "14px", "spacing": "sm",
            "contents": body_contents
        },
        "styles": {
            "header": {"backgroundColor": color},
            "body":   {"backgroundColor": t.BG_BODY}
        }
    }


# ── 主函式 ────────────────────────────────────────────────────

def build_weekly_activity_flex() -> dict:
    today  = date.today()
    monday = today - timedelta(days=today.weekday())
    start  = monday.isoformat()
    end    = today.isoformat()

    logs = fb.get_week_activities(start, end)
    if not logs:
        return None

    logs.sort(key=lambda x: x.get("date", "") + str(x.get("id", "")))

    week_label = f"{monday.month}/{monday.day} – {today.month}/{today.day}"
    bubbles = [_build_summary_card(logs, week_label)]

    for log in logs:
        sport = log.get("sport", "")
        if sport in ("Run", "VirtualRun"):
            s_status  = log.get("schedule_status", "free")
            s_workout = log.get("schedule_workout")
            s_detail  = log.get("schedule_detail")
            ai_comment = log.get("ai_comment", "")
            flex_msg = fb_flex.build_flex(log, s_status, s_workout, ai_comment=ai_comment, schedule_detail=s_detail)
            if flex_msg:
                inner = flex_msg.get("contents", {})
                if inner.get("type") == "bubble":
                    bubbles.append(inner)
                elif inner.get("type") == "carousel":
                    bubbles.extend(inner.get("contents", []))
        else:
            bubbles.append(_build_activity_card(log))

    return {
        "type": "flex",
        "altText": f"本週活動 {week_label}",
        "contents": {"type": "carousel", "contents": bubbles[:12]}
    }
