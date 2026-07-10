"""
LINE Flex Message 建構器
設計風格：與 wellness-dashboard v2 網頁同色系（mindflows 色票，見 flex_tokens.py）
- 數據清晰，不截字（wrap: true）
- Bento 卡片，圓角 12px
"""
from datetime import datetime

import flex_tokens as t

WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]

# ── 色彩系統（同源 flex_tokens，同網頁 mindflows 色票）────────
C_BG_BODY    = t.BG_BODY     # 整體背景
C_BG_CARD    = t.BG_CARD     # 卡片白底
C_TEXT_MAIN  = t.TEXT_MAIN
C_TEXT_MUTED = t.TEXT_MUTED
C_BLUE       = t.SKY         # 主強調（原「主藍」）
C_ORANGE     = t.AMBER       # 活力強調（原「活力橘」，配速等重點數字）
C_GREEN      = t.GREEN
C_RED        = t.RED
C_CYAN       = t.SKY         # 沒有獨立青色，併入 sky
C_AMBER      = t.AMBER       # 負荷/消耗
C_SEPARATOR  = t.BORDER

# 運動類別 header 底色：不再用彩虹配色，收斂到 mindflows 色系家族，
# 白字疊色一律用「加深版」token 確保對比（見 flex_tokens.py）
SPORT_THEME = {
    "Run":           (t.WOOD,       t.TINT_WOOD,    "RUN"),
    "Ride":          (t.SKY_DEEP,   t.TINT_SKY,     "RIDE"),
    "Swim":          (t.SKY_DEEP,   t.TINT_SKY,     "SWIM"),
    "Walk":          (t.GREEN_DEEP, t.TINT_GREEN,   "WALK"),
    "Hike":          (t.GREEN_DEEP, t.TINT_GREEN,   "HIKE"),
    "Yoga":          (t.AMBER_DEEP, t.TINT_AMBER,   "YOGA"),
    "WeightTraining":(t.INK2,       t.TINT_NEUTRAL, "WEIGHTS"),
    "Workout":       (t.INK2,       t.TINT_NEUTRAL, "WORKOUT"),
    "RopeSkipping":  (t.SKY_DEEP,   t.TINT_SKY,     "JUMP"),
}


def _weekday(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return WEEKDAY_ZH[dt.weekday()]
    except Exception:
        return ""


def _fmt_sec(seconds: int) -> str:
    m = seconds // 60
    if m >= 60:
        return f"{m//60}h{m%60}m"
    return f"{m}m"


def _separator():
    return {"type": "separator", "margin": "lg", "color": C_SEPARATOR}


def _stat_card(label: str, value: str, value_color: str = None, flex: int = 1):
    """Bento 風格數據卡片：白底圓角、彩色數值"""
    color = value_color or C_BLUE
    return {
        "type": "box",
        "layout": "vertical",
        "flex": flex,
        "backgroundColor": C_BG_CARD,
        "cornerRadius": "12px",
        "paddingAll": "10px",
        "contents": [
            {"type": "text", "text": value, "size": "md",
             "weight": "bold", "color": color, "wrap": True},
            {"type": "text", "text": label, "size": "xxs",
             "color": C_TEXT_MUTED, "margin": "xs", "wrap": True}
        ]
    }


def _zone_bar(zone_times: list) -> list:
    if not zone_times or len(zone_times) < 3:
        return []

    z1 = zone_times[0] + zone_times[1]
    z2 = zone_times[2]
    z3 = sum(zone_times[3:])
    total = z1 + z2 + z3
    if total == 0:
        return []

    def pct(v):
        return max(int(v / total * 100), 1)

    z1p, z2p, z3p = pct(z1), pct(z2), pct(z3)

    def seg(color, flex_v):
        return {"type": "box", "layout": "vertical",
                "flex": flex_v, "height": "12px",
                "backgroundColor": color, "contents": []}

    bar = {
        "type": "box", "layout": "horizontal",
        "cornerRadius": "6px", "margin": "sm",
        "contents": [seg(C_CYAN, z1p), seg(C_GREEN, z2p), seg(C_RED, z3p)]
    }

    # 標籤：時間 + 百分比
    def zone_label(text, color, flex_v, align="start"):
        return {"type": "text", "text": text, "size": "xxs",
                "color": color, "flex": flex_v, "align": align, "wrap": True}

    label_row = []
    if z1p >= 10:
        label_row.append(zone_label(f"Z1-2 {z1p}%", C_CYAN, z1p))
    else:
        label_row.append({"type": "filler"})

    if z2p >= 10:
        label_row.append(zone_label(f"Z3 {z2p}%", C_GREEN, z2p, "center"))
    else:
        label_row.append({"type": "filler"})

    if z3p >= 10:
        label_row.append(zone_label(f"Z4+ {z3p}%", C_RED, z3p, "end"))
    else:
        label_row.append({"type": "filler"})

    labels = {"type": "box", "layout": "horizontal",
              "margin": "xs", "contents": label_row}

    extra = []
    if z3p < 10 and z3 > 0:
        extra.append({"type": "text", "text": f"Z4+：{_fmt_sec(z3)}  ({z3p}%)",
                      "size": "xxs", "color": C_RED, "align": "end", "margin": "xs"})

    return [bar, labels] + extra


def _schedule_section(status: str = "free", workout: str = None, detail: str = None) -> list:
    if status == "matched":
        return [
            _separator(),
            {
                "type": "box", "layout": "vertical",
                "backgroundColor": t.TINT_GREEN, "cornerRadius": "12px", "paddingAll": "12px",
                "contents": [
                    {
                        "type": "box", "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "課表勾稽",
                             "size": "xs", "color": C_TEXT_MUTED, "flex": 1},
                            {"type": "text", "text": "✅ 已勾稽",
                             "size": "xs", "color": C_GREEN, "weight": "bold", "align": "end"}
                        ]
                    },
                    {"type": "text", "text": workout or "", "size": "sm",
                     "color": C_TEXT_MAIN, "margin": "sm", "wrap": True},
                    {"type": "text", "text": "按照課表跑，你好棒 💪",
                     "size": "xs", "color": C_GREEN, "margin": "sm", "weight": "bold"}
                ]
            }
        ]

    elif status == "unmatched":
        contents = [
            {
                "type": "box", "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": "課表勾稽",
                     "size": "xs", "color": C_TEXT_MUTED, "flex": 1},
                    {"type": "text", "text": "⚠️ 未對應",
                     "size": "xs", "color": C_AMBER, "weight": "bold", "align": "end"}
                ]
            }
        ]
        if workout:
            contents.append({"type": "text", "text": f"建議課表：{workout}",
                              "size": "sm", "color": C_TEXT_MAIN, "margin": "sm", "wrap": True})
        contents.append({"type": "text", "text": "加油喔！🔥",
                         "size": "xs", "color": C_AMBER, "margin": "sm", "weight": "bold"})
        return [
            _separator(),
            {"type": "box", "layout": "vertical",
             "backgroundColor": t.TINT_AMBER, "cornerRadius": "12px", "paddingAll": "12px",
             "contents": contents}
        ]

    elif status == "partial":
        contents = [
            {
                "type": "box", "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": "課表勾稽",
                     "size": "xs", "color": C_TEXT_MUTED, "flex": 1},
                    {"type": "text", "text": "🟡 部分達成",
                     "size": "xs", "color": C_AMBER, "weight": "bold", "align": "end"}
                ]
            }
        ]
        if workout:
            contents.append({"type": "text", "text": workout, "size": "sm",
                             "color": C_TEXT_MAIN, "margin": "sm", "wrap": True})
        if detail:
            contents.append({"type": "text", "text": detail, "size": "xs",
                             "color": C_AMBER, "margin": "sm", "weight": "bold", "wrap": True})
        return [
            _separator(),
            {"type": "box", "layout": "vertical",
             "backgroundColor": t.TINT_AMBER, "cornerRadius": "12px", "paddingAll": "12px",
             "contents": contents}
        ]

    else:  # free
        return [
            _separator(),
            {
                "type": "box", "layout": "vertical",
                "backgroundColor": t.TINT_NEUTRAL, "cornerRadius": "12px", "paddingAll": "12px",
                "contents": [
                    {
                        "type": "box", "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "自我訓練",
                             "size": "xs", "color": C_TEXT_MUTED, "flex": 1},
                            {"type": "text", "text": "🏃 無課表",
                             "size": "xs", "color": C_TEXT_MUTED, "align": "end"}
                        ]
                    },
                    {"type": "text", "text": "要留意休息狀況喔！😴",
                     "size": "xs", "color": C_TEXT_MUTED, "margin": "sm"}
                ]
            }
        ]


def _drift_row(drift: int) -> dict:
    """心率漂移列：同配速下後段比前段高幾 bpm，越小代表有氧越穩。"""
    if drift <= 4:
        color, emoji = C_GREEN, "🟢"
    elif drift <= 9:
        color, emoji = C_AMBER, "🟡"
    else:
        color, emoji = C_RED, "🔴"
    sign = f"+{drift}" if drift >= 0 else str(drift)
    return {
        "type": "box", "layout": "horizontal",
        "contents": [
            {"type": "text", "text": "心率漂移  同配速",
             "size": "sm", "color": C_TEXT_MUTED, "flex": 3},
            {"type": "text", "text": f"{emoji} {sign} bpm",
             "size": "sm", "color": color, "weight": "bold", "flex": 4, "align": "end"}
        ]
    }


def _ai_section(ai_comment: str) -> list:
    if not ai_comment:
        return []
    return [
        _separator(),
        {
            "type": "box", "layout": "vertical",
            "backgroundColor": t.TINT_SKY, "cornerRadius": "12px", "paddingAll": "12px",
            "contents": [
                {
                    "type": "box", "layout": "horizontal", "alignItems": "center",
                    "contents": [
                        {"type": "text", "text": "AI 分析", "size": "xs",
                         "color": C_BLUE, "weight": "bold", "flex": 1},
                    ]
                },
                {"type": "text", "text": ai_comment, "size": "xs",
                 "color": C_TEXT_MAIN, "wrap": True, "margin": "sm"}
            ]
        }
    ]


def build_run_bubble(s: dict, schedule_status: str = "free", schedule_workout: str = None, schedule_detail: str = None) -> dict:
    date_str = s.get("date", "")
    weekday  = _weekday(date_str)
    role     = s.get("role", "standalone")
    role_suffix = {"warmup": "  暖身", "cooldown": "  緩跑"}.get(role, "")
    accent, _, sport_label = SPORT_THEME["Run"]
    sport_label = sport_label + role_suffix

    dist = s.get("distance_km", 0)
    pace = s.get("avg_pace", "—")
    time = s.get("moving_time", "—")
    name = s.get("name", "跑步")
    act_id = str(s.get("id", ""))

    hr_avg  = s.get("avg_hr")
    hr_max  = s.get("max_hr")
    hr_str  = f"{hr_avg} / {hr_max} bpm" if hr_avg else "—"

    temp    = s.get("average_temp")
    weather = s.get("weather") or {}
    cond_emoji = weather.get("condition_emoji", "")
    cond       = weather.get("condition", "")
    apparent   = weather.get("apparent_temp_c")

    weather_line = ""
    if temp and cond:
        weather_line = f"{cond_emoji} {cond}  {round(temp,1)}°C"
        if apparent and abs(apparent - temp) >= 1:
            weather_line += f"  體感{round(apparent,1)}°C"
    elif temp:
        weather_line = f"{round(temp,1)}°C"

    # ── Header ────────────────────────────────────────────
    header = {
        "type": "box", "layout": "vertical",
        "backgroundColor": accent,
        "paddingTop": "16px", "paddingBottom": "16px",
        "paddingStart": "16px", "paddingEnd": "16px",
        "contents": [
            {
                "type": "box", "layout": "horizontal", "alignItems": "center",
                "contents": [
                    {"type": "text", "text": date_str,
                     "size": "sm", "weight": "bold", "color": "#FFFFFF", "flex": 0},
                    {"type": "text", "text": f"  週{weekday}",
                     "size": "sm", "color": "#FFE0CC", "flex": 1},
                    {"type": "text", "text": sport_label,
                     "size": "sm", "weight": "bold", "color": "#FFFFFF",
                     "align": "end", "flex": 0}
                ]
            },
            {
                "type": "box", "layout": "horizontal", "margin": "sm",
                "contents": [
                    {"type": "text", "text": name,
                     "size": "xs", "color": "#FFE0CC", "flex": 1, "wrap": True},
                    *(
                        [{"type": "text", "text": weather_line,
                          "size": "xs", "color": "#FFE0CC",
                          "align": "end", "flex": 0, "wrap": True}]
                        if weather_line else []
                    )
                ]
            },
            {
                "type": "box", "layout": "baseline", "margin": "md",
                "contents": [
                    {"type": "text", "text": str(dist),
                     "size": "5xl", "weight": "bold", "color": "#FFFFFF", "flex": 0},
                    {"type": "text", "text": " km",
                     "size": "lg", "color": "#FFE0CC", "gravity": "bottom", "flex": 0}
                ]
            }
        ]
    }

    # ── Body（精簡版：時間/配速、心率、課表勾稽）─────────────
    body = []

    body.append({
        "type": "box", "layout": "horizontal", "spacing": "sm",
        "contents": [
            _stat_card("時間", time, C_TEXT_MAIN),
            _stat_card("配速 /km", pace, C_ORANGE),
        ]
    })

    body.append(_separator())
    body.append({
        "type": "box", "layout": "horizontal",
        "contents": [
            {"type": "text", "text": "心率  均 / 最高",
             "size": "sm", "color": C_TEXT_MUTED, "flex": 3},
            {"type": "text", "text": hr_str,
             "size": "sm", "color": C_RED, "weight": "bold", "flex": 4, "align": "end"}
        ]
    })

    drift = s.get("cardiac_drift")
    if drift is not None and role not in ("warmup", "cooldown"):
        body.append(_drift_row(drift))

    if role not in ("warmup", "cooldown"):
        body.extend(_schedule_section(schedule_status, schedule_workout, schedule_detail))
        es = s.get("exec_score")
        if es is not None and schedule_status in ("matched", "partial"):
            body.append({
                "type": "box", "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": "達成度", "size": "sm", "color": C_TEXT_MUTED, "flex": 3},
                    {"type": "text", "text": f"{es} 分 · {s.get('exec_label', '')}",
                     "size": "sm", "color": C_TEXT_MAIN, "weight": "bold", "flex": 4, "align": "end"},
                ]
            })

    # ── Footer：詳細數據 + 深度分析按鈕 ────────────────────────
    # 深度分析僅主課表/獨立訓練有（暖身/緩跑不分析，同 poller.py ai_comment 的 gating）
    footer = None
    if act_id:
        buttons = [{
            "type": "button",
            "action": {
                "type": "postback",
                "label": "查看詳細數據",
                "data": f"detail:{act_id}"
            },
            "style": "secondary",
            "height": "sm",
            "color": t.BORDER
        }]
        if role not in ("warmup", "cooldown"):
            buttons.append({
                "type": "button",
                "action": {
                    "type": "postback",
                    "label": "深度分析",
                    "data": f"deep:{act_id}"
                },
                "style": "secondary",
                "height": "sm",
                "color": t.BORDER
            })
        footer = {
            "type": "box", "layout": "vertical",
            "backgroundColor": C_BG_BODY,
            "paddingAll": "12px", "spacing": "xs",
            "contents": buttons
        }

    bubble = {
        "type": "bubble", "size": "mega",
        "header": header,
        "body": {
            "type": "box", "layout": "vertical",
            "backgroundColor": C_BG_BODY,
            "paddingAll": "14px", "spacing": "sm",
            "contents": body
        },
        "styles": {
            "header": {"backgroundColor": accent},
            "body":   {"backgroundColor": C_BG_BODY}
        }
    }
    if footer:
        bubble["footer"] = footer

    return {"type": "flex", "altText": f"跑步完成 {dist}km  {pace}/km", "contents": bubble}


def build_detail_bubble(s: dict) -> dict:
    """詳細數據 bubble，由 postback 觸發推播"""
    date_str = s.get("date", "")
    weekday  = _weekday(date_str)
    dist     = s.get("distance_km", 0)
    accent, _, _ = SPORT_THEME["Run"]

    cadence = s.get("average_cadence")
    cadence_str = f"{int(cadence * 2)} spm" if cadence else "—"
    stride  = s.get("average_stride")
    stride_str  = f"{round(stride, 2)}m" if stride else "—"
    elev    = s.get("total_elevation_gain")
    elev_str    = f"↑{int(elev)}m" if elev else "—"

    load     = s.get("icu_training_load") or s.get("trimp")
    load_str = str(int(load)) if load else "—"
    calories = s.get("calories")
    cal_str  = str(calories) if calories else "—"
    rpe      = s.get("icu_rpe")
    rpe_str  = f"{rpe} / 10" if rpe else "—"

    temp    = s.get("average_temp")
    weather = s.get("weather") or {}
    cond_emoji = weather.get("condition_emoji", "")
    cond       = weather.get("condition", "")
    temp_str = "—"
    if temp and cond:
        temp_str = f"{cond_emoji} {cond}  {round(temp,1)}°C"
    elif temp:
        temp_str = f"{round(temp,1)}°C"

    interval_summary = s.get("interval_summary")
    interval_str = interval_summary[0] if isinstance(interval_summary, list) and interval_summary else (interval_summary or None)

    header = {
        "type": "box", "layout": "vertical",
        "backgroundColor": accent,
        "paddingTop": "14px", "paddingBottom": "14px",
        "paddingStart": "16px", "paddingEnd": "16px",
        "contents": [
            {
                "type": "box", "layout": "horizontal", "alignItems": "center",
                "contents": [
                    {"type": "text", "text": date_str,
                     "size": "sm", "weight": "bold", "color": "#FFFFFF", "flex": 0},
                    {"type": "text", "text": f"  週{weekday}",
                     "size": "sm", "color": "#FFE0CC", "flex": 1},
                    {"type": "text", "text": f"{dist} km",
                     "size": "sm", "weight": "bold", "color": "#FFFFFF",
                     "align": "end", "flex": 0}
                ]
            },
            {"type": "text", "text": "詳細訓練數據",
             "size": "xs", "color": "#FFE0CC", "margin": "sm"}
        ]
    }

    body = []

    body.append({
        "type": "box", "layout": "horizontal", "spacing": "sm",
        "contents": [
            _stat_card("步頻", cadence_str, C_BLUE),
            _stat_card("步幅", stride_str, C_BLUE),
            _stat_card("爬升", elev_str, C_BLUE),
        ]
    })

    body.append(_separator())
    body.extend(_zone_bar(s.get("icu_hr_zone_times", [])))

    if interval_str:
        body.append({
            "type": "box", "layout": "horizontal", "margin": "md",
            "backgroundColor": t.TINT_GREEN, "cornerRadius": "10px", "paddingAll": "10px",
            "contents": [
                {"type": "text", "text": "⚡  " + interval_str,
                 "size": "sm", "color": C_GREEN, "weight": "bold", "wrap": True}
            ]
        })

    body.append(_separator())
    body.append({
        "type": "box", "layout": "horizontal", "spacing": "sm",
        "contents": [
            _stat_card("訓練負荷", load_str, C_AMBER),
            _stat_card("消耗 (kcal)", cal_str, C_AMBER),
        ]
    })
    body.append({
        "type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm",
        "contents": [
            _stat_card("氣溫", temp_str, C_TEXT_MUTED),
            _stat_card("體感 RPE", rpe_str, C_TEXT_MUTED),
        ]
    })

    bubble = {
        "type": "bubble", "size": "mega",
        "header": header,
        "body": {
            "type": "box", "layout": "vertical",
            "backgroundColor": C_BG_BODY,
            "paddingAll": "14px", "spacing": "sm",
            "contents": body
        },
        "styles": {
            "header": {"backgroundColor": accent},
            "body":   {"backgroundColor": C_BG_BODY}
        }
    }
    return {"type": "flex", "altText": f"詳細數據 {date_str} {dist}km", "contents": bubble}


_DEEP_SECTIONS = [
    # (deep_analysis key, 顯示標題, 淡色底 token)
    ("today_performance", "今日表現", "TINT_NEUTRAL"),
    ("history_comparison", "跟歷史同類課表比較", "TINT_SKY"),
    ("training_phase", "目前所處訓練階段", "TINT_AMBER"),
    ("body_signals", "身體訊號", "TINT_GREEN"),
    ("advice", "建議", "TINT_WOOD"),
]


def _deep_section_box(title: str, text: str, tint_name: str) -> dict:
    tint = getattr(t, tint_name)
    return {
        "type": "box", "layout": "vertical",
        "backgroundColor": tint, "cornerRadius": "12px", "paddingAll": "12px",
        "margin": "sm",
        "contents": [
            {"type": "text", "text": title, "size": "xs",
             "color": C_TEXT_MUTED, "weight": "bold"},
            {"type": "text", "text": text or "這部分資料不足", "size": "sm",
             "color": C_TEXT_MAIN, "wrap": True, "margin": "xs"},
        ]
    }


def build_deep_analysis_bubble(s: dict) -> dict:
    """深度分析 bubble（第二層），由 `deep:{act_id}` postback 觸發顯示。
    內容在推播當下（poller.py）就已經生成好存在 s["deep_analysis"]，這裡只負責排版，
    不現場呼叫 LLM（按鈕點下去要秒開，見 CLAUDE.md 深度分析設計說明）。"""
    date_str = s.get("date", "")
    weekday  = _weekday(date_str)
    dist     = s.get("distance_km", 0)
    accent, _, _ = SPORT_THEME["Run"]

    deep = s.get("deep_analysis") or {}

    header = {
        "type": "box", "layout": "vertical",
        "backgroundColor": accent,
        "paddingTop": "14px", "paddingBottom": "14px",
        "paddingStart": "16px", "paddingEnd": "16px",
        "contents": [
            {
                "type": "box", "layout": "horizontal", "alignItems": "center",
                "contents": [
                    {"type": "text", "text": date_str,
                     "size": "sm", "weight": "bold", "color": "#FFFFFF", "flex": 0},
                    {"type": "text", "text": f"  週{weekday}",
                     "size": "sm", "color": "#FFE0CC", "flex": 1},
                    {"type": "text", "text": f"{dist} km",
                     "size": "sm", "weight": "bold", "color": "#FFFFFF",
                     "align": "end", "flex": 0}
                ]
            },
            {"type": "text", "text": "深度分析",
             "size": "xs", "color": "#FFE0CC", "margin": "sm"}
        ]
    }

    body = []
    for key, title, tint_name in _DEEP_SECTIONS:
        text = deep.get(key)
        if not text:
            continue
        body.append(_deep_section_box(title, text, tint_name))

    if not body:
        body.append({"type": "text", "text": "深度分析尚未生成完成，稍後再試一次。",
                     "size": "sm", "color": C_TEXT_MUTED, "wrap": True})

    bubble = {
        "type": "bubble", "size": "giga",
        "header": header,
        "body": {
            "type": "box", "layout": "vertical",
            "backgroundColor": C_BG_BODY,
            "paddingAll": "14px", "spacing": "xs",
            "contents": body
        },
        "styles": {
            "header": {"backgroundColor": accent},
            "body":   {"backgroundColor": C_BG_BODY}
        }
    }
    return {"type": "flex", "altText": f"深度分析 {date_str} {dist}km", "contents": bubble}


def build_generic_bubble(s: dict, schedule_status: str = "free", schedule_workout: str = None, schedule_detail: str = None) -> dict:
    sport    = s.get("sport", "Workout")
    date_str = s.get("date", "")
    weekday  = _weekday(date_str)
    accent, _, label = SPORT_THEME.get(sport, (t.INK2, t.TINT_NEUTRAL, sport.upper()))

    hr_avg  = s.get("avg_hr")
    hr_max  = s.get("max_hr")
    load    = s.get("icu_training_load") or s.get("trimp")
    calories = s.get("calories")
    has_dist = sport in ("Ride", "Swim", "Walk", "Hike")
    dist    = s.get("distance_km", 0)

    temp    = s.get("average_temp")
    weather = s.get("weather") or {}
    cond_emoji = weather.get("condition_emoji", "")
    cond       = weather.get("condition", "")
    weather_line = ""
    if temp and cond:
        weather_line = f"{cond_emoji} {cond}  {round(temp,1)}°C"
    elif temp:
        weather_line = f"{round(temp,1)}°C"

    header = {
        "type": "box", "layout": "vertical",
        "backgroundColor": accent, "paddingAll": "16px",
        "contents": [
            {
                "type": "box", "layout": "horizontal", "alignItems": "center",
                "contents": [
                    {
                        "type": "box", "layout": "vertical", "flex": 1,
                        "contents": [
                            {"type": "text", "text": date_str,
                             "size": "sm", "weight": "bold", "color": "#FFFFFF"},
                            {"type": "text", "text": f"週{weekday}",
                             "size": "xs", "color": "#FFFFFF", "margin": "xs"},
                        ]
                    },
                    {"type": "text", "text": label, "size": "xxl",
                     "weight": "bold", "color": "#FFFFFF", "align": "end", "flex": 0}
                ]
            },
            {
                "type": "box", "layout": "horizontal", "margin": "sm",
                "contents": [
                    {"type": "text", "text": s.get("name", label),
                     "size": "xs", "color": "#FFFFFF", "flex": 1, "wrap": True},
                    *(
                        [{"type": "text", "text": weather_line,
                          "size": "xs", "color": "#FFFFFF",
                          "align": "end", "flex": 0}]
                        if weather_line else []
                    )
                ]
            }
        ]
    }

    body = []
    row1 = [_stat_card("時間", s.get("moving_time", "—"), C_TEXT_MAIN)]
    if has_dist and dist > 0:
        row1.insert(0, _stat_card("距離", f"{dist} km", C_BLUE))
    if hr_avg:
        row1.append(_stat_card("心率", f"{hr_avg}/{hr_max}", C_RED))
    body.append({"type": "box", "layout": "horizontal", "spacing": "sm", "contents": row1})

    if load or calories:
        row2 = []
        if load:
            row2.append(_stat_card("訓練負荷", str(int(load)), C_AMBER))
        if calories:
            row2.append(_stat_card("消耗 (kcal)", str(calories), C_AMBER))
        body.append({"type": "box", "layout": "horizontal",
                     "margin": "sm", "spacing": "sm", "contents": row2})

    body.extend(_schedule_section(schedule_status, schedule_workout))

    bubble = {
        "type": "bubble", "size": "mega",
        "header": header,
        "body": {
            "type": "box", "layout": "vertical",
            "backgroundColor": C_BG_BODY,
            "paddingAll": "14px", "spacing": "sm",
            "contents": body
        },
        "styles": {
            "header": {"backgroundColor": accent},
            "body":   {"backgroundColor": C_BG_BODY}
        }
    }
    return {"type": "flex", "altText": f"{label}完成", "contents": bubble}


def build_flex(summary: dict, schedule_status: str = "free",
               schedule_workout: str = None, ai_comment: str = "",
               schedule_detail: str = None) -> dict:
    if summary.get("sport") == "Run":
        msg = build_run_bubble(summary, schedule_status, schedule_workout, schedule_detail)
    else:
        msg = build_generic_bubble(summary, schedule_status, schedule_workout, schedule_detail)

    if ai_comment:
        msg["contents"]["body"]["contents"].extend(_ai_section(ai_comment))

    return msg
