"""
今日教練 Flex 卡：吃 wellness-dashboard /api/coach 的 JSON，組成 LINE Flex bubble。
純函式、無外部依賴。設計系統：與 v2 網頁同色系（mindflows 色票，見 flex_tokens.py），
背景 paper 卡片圓角 12px。
所有 text component 一律非空（LINE 空 text → push 400）。
所有 color 一律合法 hex：/api/coach 的 *_color 欄是語意 token（good/ok/warn/none），
不是 hex；直接灌進 LINE color 會 push 400，必須經 _safe_color 轉換。
"""
from __future__ import annotations  # 讓 `dict | None` 等註解相容 Python 3.9（/usr/bin/python3）

import re

import flex_tokens as t

ACCENT = t.WOOD
AMBER = t.AMBER

_HEX_COLOR = re.compile(r"^#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")
# dashboard /api/coach 的 hrv_color / form_color 值域
_COLOR_TOKENS = {
    "good": t.GREEN,
    "ok": t.GREEN,
    "warn": t.AMBER,
    "none": t.TEXT_MUTED,  # 無資料
}


def _safe_color(value, default: str) -> str:
    """回傳保證合法的 LINE hex color。
    value 可能是 hex、語意 token（good/ok/warn/none）、None 或其他；
    非 hex 又非已知 token 時回傳 default。LINE 只收 #RRGGBB / #RRGGBBAA。"""
    if isinstance(value, str):
        if _HEX_COLOR.match(value):
            return value
        if value in _COLOR_TOKENS:
            return _COLOR_TOKENS[value]
    return default


def _stat_cell(emoji: str, value: str, label: str, val_color: str = t.TEXT_MAIN) -> dict:
    return {
        "type": "box", "layout": "vertical",
        "backgroundColor": t.BG_CARD, "cornerRadius": "10px",
        "paddingTop": "10px", "paddingBottom": "10px",
        "paddingStart": "6px", "paddingEnd": "6px",
        "alignItems": "center", "flex": 1,
        "contents": [
            {"type": "text", "text": emoji, "size": "lg", "align": "center"},
            {"type": "text", "text": value, "size": "xs", "weight": "bold",
             "color": val_color, "align": "center", "wrap": True},
            {"type": "text", "text": label, "size": "xxs",
             "color": t.TEXT_MUTED, "align": "center"},
        ],
    }


def build(coach: dict, weather: dict | None = None, title: str = "今日教練") -> dict:
    today = coach.get("today") or ""
    is_rest = coach.get("today_is_rest", False)
    today_workout = coach.get("today_workout") or ("休息" if is_rest else "查看課表")
    tomorrow_workout = coach.get("tomorrow_workout") or "待補"
    week_goal = coach.get("week_goal") or ""

    advice_lines = [ln.strip() for ln in (coach.get("advice") or "").split("\n") if ln.strip()]
    if not advice_lines:
        advice_lines = ["今日暫無教練建議，稍後再試"]

    # Header
    header_contents = [
        {"type": "box", "layout": "horizontal", "contents": [
            {"type": "text", "text": title, "size": "xl", "weight": "bold",
             "color": "#FFFFFF", "flex": 1},
        ]},
    ]
    if today:
        header_contents[0]["contents"].append(
            {"type": "text", "text": today, "size": "xs", "color": "#FFFFFFB3",
             "align": "end", "gravity": "center", "flex": 0})
    form_status = coach.get("form_status")
    if form_status:
        # 深藍 header 上用固定淺色（對比 + 避免語意 token 灌進 color）
        header_contents.append(
            {"type": "text", "text": form_status, "size": "xs",
             "color": "#FFFFFFCC", "margin": "sm"})

    # advice 卡
    advice_card = {
        "type": "box", "layout": "vertical",
        "backgroundColor": t.BG_CARD, "cornerRadius": "12px",
        "paddingAll": "14px", "spacing": "sm",
        "contents": [
            {"type": "text", "text": line, "size": "sm", "color": t.TEXT_MAIN, "wrap": True}
            for line in advice_lines
        ],
    }

    # 身體數據 bento（缺值的 cell 不放，確保無空 text）
    cells = []
    hrv = coach.get("hrv")
    if hrv is not None:
        cells.append(_stat_cell("❤️", str(hrv), "HRV", _safe_color(coach.get("hrv_color"), t.TEXT_MAIN)))
    sleep = coach.get("sleepHrs")
    if sleep is not None:
        cells.append(_stat_cell("😴", f"{sleep:g}h", "睡眠"))
    tsb = coach.get("tsb")
    if tsb is not None:
        cells.append(_stat_cell("📈", str(tsb), "TSB", _safe_color(coach.get("form_color"), t.TEXT_MAIN)))

    body_contents = [advice_card]
    if cells:
        body_contents.append({
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "margin": "md", "contents": cells,
        })

    # 跑前重點（wellness /api/coach 的 form_insights 新欄位；缺或空則整塊不顯示）
    insight_rows = []
    dot_colors = {"green": t.GREEN, "yellow": t.AMBER_DEEP, "red": t.RED}
    for it in (coach.get("form_insights") or []):
        msg = (it or {}).get("msg")
        if not msg:
            continue
        topic = it.get("topic") or ""
        text = f"{topic}：{msg}" if topic else msg
        insight_rows.append({"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [
            {"type": "text", "text": "●", "size": "xxs", "flex": 0,
             "color": dot_colors.get(it.get("level"), t.TEXT_MUTED)},
            {"type": "text", "text": text, "size": "xs", "color": t.TEXT_MAIN,
             "wrap": True, "flex": 9},
        ]})
    if insight_rows:
        body_contents.append({
            "type": "box", "layout": "vertical",
            "backgroundColor": t.BG_CARD, "cornerRadius": "12px",
            "paddingAll": "12px", "spacing": "sm", "margin": "md",
            "contents": [
                {"type": "text", "text": "跑前重點", "size": "xxs",
                 "color": t.SKY_DEEP, "weight": "bold"},
                *insight_rows,
            ],
        })

    # 今日天氣區塊（caller 傳 weather_client.forecast_bundle()["today"]；缺則整塊不顯示）
    if weather:
        emoji = weather.get("emoji") or "🌡️"
        desc = weather.get("desc") or ""
        t_max = weather.get("t_max")
        t_min = weather.get("t_min")
        rain_pct = weather.get("rain_pct")
        at_max = weather.get("at_max")
        humidity = weather.get("humidity")
        comfort = weather.get("comfort") or ""

        temp_range = (f"{t_min}–{t_max}°C" if t_min is not None and t_max is not None
                      else (f"{t_max}°C" if t_max is not None else ""))
        top_bits = []
        if desc:
            top_bits.append(f"{emoji} {desc}")
        if temp_range:
            top_bits.append(temp_range)
        if rain_pct is not None:
            top_bits.append(f"☂️ {rain_pct}%")

        wx_rows = []
        if top_bits:
            wx_rows.append({"type": "text", "text": "  ".join(top_bits),
                            "size": "sm", "color": t.TEXT_MAIN, "weight": "bold", "wrap": True})
        sub_bits = []
        if at_max is not None:
            sub_bits.append(f"體感 {at_max}°C")
        if humidity is not None:
            sub_bits.append(f"濕度 {humidity}%")
        if comfort:
            sub_bits.append(comfort)
        if sub_bits:
            c_color = (t.RED if ("熱" in comfort or "危" in comfort)
                       else t.GREEN if comfort in ("舒適", "涼爽")
                       else t.TEXT_MUTED)
            wx_rows.append({"type": "text", "text": "　".join(sub_bits),
                            "size": "xs", "color": c_color, "wrap": True, "margin": "xs"})

        if wx_rows:
            body_contents.append({
                "type": "box", "layout": "vertical",
                "backgroundColor": t.BG_CARD, "cornerRadius": "12px",
                "paddingAll": "12px", "spacing": "xs", "margin": "md",
                "contents": [
                    {"type": "text", "text": "今日天氣", "size": "xxs",
                     "color": t.SKY_DEEP, "weight": "bold"},
                    *wx_rows,
                ],
            })

    # 今日 / 明日課表
    body_contents.append({"type": "separator", "margin": "lg", "color": t.BORDER})
    body_contents.append({
        "type": "box", "layout": "vertical", "margin": "md", "spacing": "sm",
        "contents": [
            {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [
                {"type": "text", "text": "今日", "size": "xs", "color": t.TEXT_MUTED, "flex": 1},
                {"type": "text", "text": today_workout, "size": "sm", "color": t.TEXT_MAIN,
                 "weight": "bold", "wrap": True, "flex": 5},
            ]},
            {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [
                {"type": "text", "text": "明日", "size": "xs", "color": t.TEXT_MUTED, "flex": 1},
                {"type": "text", "text": tomorrow_workout, "size": "sm", "color": t.TEXT_MUTED,
                 "wrap": True, "flex": 5},
            ]},
        ],
    })
    if week_goal:
        body_contents.append({
            "type": "box", "layout": "vertical",
            "backgroundColor": t.TINT_AMBER, "cornerRadius": "10px",
            "paddingAll": "12px", "margin": "md",
            "contents": [
                {"type": "text", "text": "本週目標", "size": "xxs",
                 "color": AMBER, "weight": "bold"},
                {"type": "text", "text": week_goal, "size": "xs",
                 "color": t.TEXT_MAIN, "wrap": True, "margin": "xs"},
            ],
        })

    bubble = {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": ACCENT,
            "paddingTop": "18px", "paddingBottom": "18px",
            "paddingStart": "18px", "paddingEnd": "18px",
            "contents": header_contents,
        },
        "body": {
            "type": "box", "layout": "vertical", "backgroundColor": t.BG_BODY,
            "paddingAll": "16px", "spacing": "md", "contents": body_contents,
        },
    }
    return {"type": "flex", "altText": "今日教練建議", "contents": bubble}


_STATUS_STYLE = {
    "good": (t.GREEN_DEEP, "🟢"),
    "warn": (t.AMBER_DEEP, "🟡"),
    "bad":  (t.RED_DEEP, "🔴"),
}


def build_reply(data: dict) -> dict:
    """對話教練結構化回覆卡：headline/status/rows/tips/ask → 精簡可掃讀的 Flex bubble。
    取代舊版把整段 AI 生成文字塞進純文字訊息的做法（原作者 反饋：不想讀大段文字）。
    data 形狀見 coach_agent.run_coach() 回傳（已經過 _normalize_reply 防呆）。"""
    headline = data.get("headline") or "教練回覆"
    status = data.get("status") if data.get("status") in _STATUS_STYLE else "warn"
    accent, dot = _STATUS_STYLE[status]
    rows = data.get("rows") or []
    tips = data.get("tips") or []
    ask = data.get("ask") or ""

    header_contents = [
        {"type": "box", "layout": "horizontal", "alignItems": "center", "spacing": "sm",
         "contents": [
             {"type": "text", "text": dot, "size": "lg", "flex": 0},
             {"type": "text", "text": headline, "size": "lg", "weight": "bold",
              "color": "#FFFFFF", "flex": 1, "wrap": True},
         ]},
    ]

    body_contents = []
    for r in rows:
        body_contents.append({
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "contents": [
                {"type": "text", "text": r.get("label", ""), "size": "xs",
                 "color": t.TEXT_MUTED, "flex": 2},
                {"type": "text", "text": r.get("value", ""), "size": "sm",
                 "color": t.TEXT_MAIN, "weight": "bold", "wrap": True, "flex": 5},
            ],
        })

    if tips:
        tip_rows = [
            {"type": "text", "text": f"{i}. {tip}", "size": "xs", "color": t.TEXT_MAIN, "wrap": True}
            for i, tip in enumerate(tips, 1)
        ]
        body_contents.append({"type": "separator", "margin": "md", "color": t.BORDER})
        body_contents.append({
            "type": "box", "layout": "vertical",
            "backgroundColor": t.TINT_AMBER, "cornerRadius": "10px",
            "paddingAll": "12px", "margin": "sm", "spacing": "xs",
            "contents": [
                {"type": "text", "text": "建議", "size": "xxs", "color": AMBER, "weight": "bold"},
                *tip_rows,
            ],
        })

    if ask:
        body_contents.append({"type": "separator", "margin": "md", "color": t.BORDER})
        body_contents.append({"type": "text", "text": ask, "size": "xs",
                               "color": t.TEXT_MUTED, "wrap": True, "margin": "sm"})

    if not body_contents:
        body_contents.append({"type": "text", "text": " ", "size": "xs", "color": t.TEXT_MUTED})

    bubble = {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": accent,
            "paddingTop": "18px", "paddingBottom": "18px",
            "paddingStart": "18px", "paddingEnd": "18px",
            "contents": header_contents,
        },
        "body": {
            "type": "box", "layout": "vertical", "backgroundColor": t.BG_BODY,
            "paddingAll": "16px", "spacing": "sm", "contents": body_contents,
        },
    }
    return {"type": "flex", "altText": headline, "contents": bubble}
