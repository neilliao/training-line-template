"""
賽事 Flex Message 建構器
- 賽事詳情 bubble（含倒數 + 檢核表）
- 賽事 Carousel（多場賽事）
- 登錄引導 bubble
設計系統：與 v2 網頁同色系（mindflows 色票，見 flex_tokens.py）
"""
from datetime import date

import flex_tokens as t

# ── 色彩（同源 flex_tokens）───────────────────────────────────
C_GOLD   = t.AMBER
C_HEADER = t.AMBER_DEEP   # header 白字承載，需加深版
C_DARK   = t.WOOD
C_BODY   = t.BG_BODY
C_GREEN  = t.GREEN
C_RED    = t.RED
C_MUTED  = t.TEXT_MUTED
C_CARD   = t.BG_CARD


def _days_until(date_str: str) -> int:
    try:
        race_date = date.fromisoformat(date_str)
        return (race_date - date.today()).days
    except Exception:
        return 999


def _countdown_color(days: int) -> str:
    if days <= 14:
        return C_RED
    if days <= 30:
        return C_GOLD
    return C_GREEN


def _checklist_row(item: dict, race_id: str = "") -> dict:
    done = item.get("done", False)
    text = item.get("item", "")
    dot_color = C_GREEN if done else t.BORDER
    text_color = t.TEXT_MUTED if done else t.TEXT_MAIN

    row = {
        "type": "box", "layout": "horizontal",
        "paddingTop": "7px", "paddingBottom": "7px",
        "paddingStart": "10px", "paddingEnd": "10px",
        "backgroundColor": C_CARD, "cornerRadius": "8px",
        "contents": [
            # 勾選圓點
            {
                "type": "box", "layout": "vertical",
                "backgroundColor": dot_color,
                "width": "16px", "height": "16px",
                "cornerRadius": "8px",
                "justifyContent": "center", "alignItems": "center",
                "contents": []
            },
            {"type": "box", "layout": "vertical", "width": "10px", "contents": []},
            {
                "type": "text", "text": text,
                "size": "sm", "color": text_color,
                "flex": 1, "wrap": True,
                "decoration": "line-through" if done else "none"
            },
            {
                "type": "text",
                "text": "完成" if done else "點擊勾稽",
                "size": "xxs",
                "color": C_GREEN if done else t.SKY_DEEP,
                "flex": 0, "align": "end",
                "weight": "bold"
            }
        ]
    }

    # 未完成 + 有 race_id → 整個 box 可點擊（postback）
    if not done and race_id:
        row["action"] = {
            "type": "postback",
            "label": text[:20],
            "data": f"checklist_done:{race_id}:{text}",
            "displayText": f"完成：{text}"
        }

    return row


def build_race_bubble(race: dict) -> dict:
    """單場賽事詳情 bubble"""
    name      = race.get("name", "賽事")
    race_date = race.get("date", "")
    location  = race.get("location", "")
    dist_km   = race.get("distance_km", 0)
    race_id   = race.get("race_id", "")
    checklist = race.get("checklist", [])

    days = _days_until(race_date)
    cntdown_color = _countdown_color(days)

    # 日期顯示
    try:
        from datetime import datetime
        dt = datetime.strptime(race_date, "%Y-%m-%d")
        MONTH_ZH = ["", "一月", "二月", "三月", "四月", "五月", "六月",
                    "七月", "八月", "九月", "十月", "十一月", "十二月"]
        date_display = f"{dt.year} / {dt.month:02d} / {dt.day:02d}"
    except Exception:
        date_display = race_date

    # 距離標籤
    if dist_km == 42.195:
        dist_label = "全馬 42.195km"
    elif dist_km == 21.0975:
        dist_label = "半馬 21.0975km"
    elif dist_km > 0:
        dist_label = f"{dist_km}km"
    else:
        dist_label = ""

    # 倒數文字
    if days < 0:
        countdown_text = "已完賽"
        countdown_val  = "DONE"
    elif days == 0:
        countdown_text = "今天就是比賽日！"
        countdown_val  = "GO!"
    else:
        countdown_text = "距離比賽"
        countdown_val  = f"{days}天"

    # 檢核進度
    total = len(checklist)
    done_count = sum(1 for c in checklist if c.get("done"))
    progress_pct = int(done_count / total * 100) if total else 0

    # 進度條（用連續方塊模擬）
    filled = round(progress_pct / 10)
    bar_cells = []
    for i in range(10):
        bar_cells.append({
            "type": "box", "layout": "vertical", "flex": 1,
            "backgroundColor": C_GREEN if i < filled else t.BORDER,
            "height": "6px",
            "cornerRadius": "3px",
            "contents": []
        })
        if i < 9:
            bar_cells.append({"type": "box", "layout": "vertical",
                               "width": "3px", "contents": []})

    # 檢核表
    checklist_rows = [_checklist_row(c, race_id) for c in checklist]
    undone_items = [c["item"] for c in checklist if not c.get("done")]

    body_contents = [
        # 倒數 + 完成度（並排）
        {
            "type": "box", "layout": "horizontal",
            "spacing": "sm",
            "contents": [
                {
                    "type": "box", "layout": "vertical",
                    "backgroundColor": C_CARD, "cornerRadius": "12px",
                    "paddingAll": "14px", "alignItems": "center", "flex": 1,
                    "contents": [
                        {"type": "text", "text": countdown_val, "size": "xxl",
                         "weight": "bold", "color": cntdown_color, "align": "center"},
                        {"type": "text", "text": countdown_text, "size": "xxs",
                         "color": C_MUTED, "align": "center"}
                    ]
                },
                {
                    "type": "box", "layout": "vertical",
                    "backgroundColor": C_CARD, "cornerRadius": "12px",
                    "paddingAll": "14px", "alignItems": "center", "flex": 1,
                    "contents": [
                        {"type": "text", "text": f"{done_count}/{total}",
                         "size": "xxl", "weight": "bold",
                         "color": C_GREEN if done_count == total else t.TEXT_MAIN,
                         "align": "center"},
                        {"type": "text", "text": "備賽完成度", "size": "xxs",
                         "color": C_MUTED, "align": "center"},
                        {
                            "type": "box", "layout": "horizontal",
                            "margin": "sm", "spacing": "none",
                            "contents": bar_cells
                        }
                    ]
                }
            ]
        },
        # 備賽清單標題（純文字）
        {"type": "text", "text": "備賽清單",
         "size": "xs", "color": C_MUTED, "weight": "bold", "margin": "md"},
        *checklist_rows,
    ]

    if undone_items:
        body_contents.append({
            "type": "text", "text": "點擊項目即可完成勾稽",
            "size": "xxs", "color": t.TEXT_MUTED, "wrap": True, "margin": "sm"
        })

    return {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": C_HEADER,
            "paddingTop": "20px", "paddingBottom": "20px",
            "paddingStart": "18px", "paddingEnd": "18px",
            "contents": [
                # 賽事標籤 + 地點
                {
                    "type": "box", "layout": "horizontal",
                    "alignItems": "center",
                    "contents": [
                        {"type": "text", "text": "賽事目標",
                         "size": "xs", "color": "#FDE68A", "weight": "bold", "flex": 1},
                        *([{"type": "text", "text": location,
                            "size": "xs", "color": "#FDE68AB3",
                            "flex": 0, "align": "end"}] if location else [])
                    ]
                },
                {"type": "text", "text": name,
                 "size": "xl", "weight": "bold", "color": "#FFFFFF",
                 "margin": "sm", "wrap": True},
                # 距離 + 日期行
                {
                    "type": "box", "layout": "horizontal",
                    "margin": "sm", "spacing": "sm",
                    "contents": [
                        *([{"type": "text", "text": dist_label,
                            "size": "xs", "color": "#FDE68A", "flex": 0}] if dist_label else []),
                        {"type": "text", "text": date_display,
                         "size": "xs", "color": "#FDE68AB3",
                         "flex": 0}
                    ]
                }
            ]
        },
        "body": {
            "type": "box", "layout": "vertical",
            "backgroundColor": C_BODY, "paddingAll": "14px", "spacing": "sm",
            "contents": body_contents
        },
        "styles": {
            "header": {"backgroundColor": C_HEADER},
            "body":   {"backgroundColor": C_BODY}
        }
    }


def build_races_carousel(races: list) -> dict:
    """多場賽事 Carousel"""
    if not races:
        return None
    bubbles = [build_race_bubble(r) for r in races[:10]]
    return {
        "type": "flex",
        "altText": f"我的賽事（{len(races)} 場）",
        "contents": {"type": "carousel", "contents": bubbles}
    }


def build_register_guide_bubble() -> dict:
    """登錄賽事引導 bubble（告知輸入格式）"""
    return {
        "type": "flex",
        "altText": "登錄賽事 - 請依格式輸入",
        "contents": {
            "type": "bubble", "size": "mega",
            "header": {
                "type": "box", "layout": "vertical",
                "backgroundColor": C_DARK,
                "paddingAll": "20px",
                "contents": [
                    {"type": "text", "text": "登錄賽事",
                     "size": "xs", "color": t.TEXT_MUTED},
                    {"type": "text", "text": "請依格式輸入賽事資訊",
                     "size": "lg", "weight": "bold", "color": "#FFFFFF",
                     "margin": "sm"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical",
                "backgroundColor": C_BODY, "paddingAll": "16px", "spacing": "md",
                "contents": [
                    {
                        "type": "box", "layout": "vertical",
                        "backgroundColor": t.TEXT_MAIN, "cornerRadius": "12px",
                        "paddingAll": "14px", "spacing": "sm",
                        "contents": [
                            {"type": "text", "text": "輸入格式",
                             "size": "xxs", "color": t.TEXT_MUTED, "weight": "bold"},
                            {"type": "text",
                             "text": "賽事名稱 日期 距離 地點",
                             "size": "sm", "color": "#FFFFFF", "weight": "bold",
                             "margin": "sm"},
                        ]
                    },
                    {
                        "type": "box", "layout": "vertical",
                        "backgroundColor": "#FFFFFF", "cornerRadius": "12px",
                        "paddingAll": "14px", "spacing": "xs",
                        "contents": [
                            {"type": "text", "text": "範例",
                             "size": "xxs", "color": t.TEXT_MUTED, "weight": "bold"},
                            {"type": "text",
                             "text": "黃金海岸馬拉松 2026/07/05 42k 澳洲黃金海岸",
                             "size": "sm", "color": t.TEXT_MAIN, "wrap": True,
                             "margin": "sm"},
                        ]
                    },
                    {
                        "type": "box", "layout": "vertical",
                        "backgroundColor": "#FFFFFF", "cornerRadius": "12px",
                        "paddingAll": "14px", "spacing": "xs",
                        "contents": [
                            {"type": "text", "text": "距離格式", "size": "xxs",
                             "color": t.TEXT_MUTED, "weight": "bold"},
                            {"type": "text",
                             "text": "全馬 / 半馬 / 42k / 21k / 10k",
                             "size": "sm", "color": C_GOLD, "wrap": True,
                             "margin": "sm"},
                        ]
                    },
                    {"type": "text",
                     "text": "輸入後系統自動帶入預設備賽清單，之後可自行勾稽各項目",
                     "size": "xxs", "color": t.TEXT_MUTED, "wrap": True}
                ]
            },
            "styles": {
                "header": {"backgroundColor": C_DARK},
                "body":   {"backgroundColor": C_BODY}
            }
        }
    }


def build_registration_form(data: dict, active_step: str,
                            quick_replies: list = None) -> dict:
    """
    登錄賽事表單 flex message：一張卡片顯示所有欄位狀態，逐步填入
    active_step: "name" | "date" | "distance" | "location"
    """
    from datetime import date as d_cls, timedelta

    name      = data.get("name", "")
    date_str  = data.get("date", "")
    dist_km   = data.get("distance_km")
    location  = data.get("location", "")

    # 格式化顯示值
    if date_str:
        try:
            from datetime import datetime
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            date_display = f"{dt.year}/{dt.month:02d}/{dt.day:02d}"
        except Exception:
            date_display = date_str
    else:
        date_display = ""

    if dist_km == 42.195:
        dist_display = "全馬 42.195 km"
    elif dist_km == 21.0975:
        dist_display = "半馬 21.0975 km"
    elif dist_km and dist_km > 0:
        dist_display = f"{dist_km} km"
    else:
        dist_display = ""

    # ── 進度條點 ─────────────────────────────────────────────
    step_keys = ["name", "date", "distance", "location"]
    step_done = {
        "name":     bool(name),
        "date":     bool(date_str),
        "distance": bool(dist_display),
        "location": bool(location),
    }
    dots = []
    for i, sk in enumerate(step_keys):
        is_curr = (sk == active_step)
        is_done = step_done[sk]
        dots.append({
            "type": "box", "layout": "vertical",
            "width": "20px" if is_curr else "8px",
            "height": "8px", "cornerRadius": "4px",
            "backgroundColor": "#FFFFFF" if is_curr else (
                "#FFFFFFCC" if is_done else "#FFFFFF33"),
            "contents": []
        })
        if i < len(step_keys) - 1:
            dots.append({
                "type": "box", "layout": "vertical",
                "width": "10px", "height": "2px",
                "backgroundColor": "#FFFFFF33", "contents": []
            })

    # ── 欄位卡片 ─────────────────────────────────────────────
    def field_card(step_key, label, value, empty_hint, action=None):
        is_active = (active_step == step_key)
        filled = bool(value)
        bar_color  = C_GREEN if filled else (C_GOLD if is_active else t.BORDER)
        val_color  = t.TEXT_MAIN if filled else (t.AMBER_DEEP if is_active else t.BORDER)
        val_text   = value if filled else (empty_hint if is_active else "—")
        val_weight = "bold" if filled else "regular"

        right = []
        if filled:
            right.append({
                "type": "text", "text": "✓", "size": "sm",
                "color": C_GREEN, "flex": 0, "align": "end"
            })
        elif is_active and action:
            # 日期欄：顯示「點此選擇」提示
            right.append({
                "type": "text", "text": "▶", "size": "xxs",
                "color": C_GOLD, "flex": 0, "align": "end"
            })

        card = {
            "type": "box", "layout": "horizontal",
            "backgroundColor": C_CARD, "cornerRadius": "12px",
            "paddingTop": "12px", "paddingBottom": "12px",
            "paddingEnd": "14px", "paddingStart": "0px",
            "alignItems": "center",
            "contents": [
                # 左側色條
                {
                    "type": "box", "layout": "vertical",
                    "backgroundColor": bar_color,
                    "width": "4px", "cornerRadius": "4px",
                    "contents": [{"type": "filler"}]
                },
                {"type": "box", "layout": "vertical", "width": "12px", "contents": []},
                {
                    "type": "box", "layout": "vertical", "flex": 1,
                    "contents": [
                        {"type": "text", "text": label,
                         "size": "xxs", "color": C_MUTED, "weight": "bold"},
                        {"type": "text", "text": val_text,
                         "size": "sm", "color": val_color,
                         "weight": val_weight, "margin": "xs", "wrap": True}
                    ]
                },
                *right
            ]
        }
        # 日期欄位未填時，整個 card 可點擊（datetimepicker）
        if action and not filled:
            card["action"] = action

        # 地點欄位已填時，附 Google Maps 連結
        if step_key == "location" and filled:
            import urllib.parse
            maps_url = "https://www.google.com/maps/search/" + urllib.parse.quote(value)
            card["action"] = {"type": "uri", "label": "查看地圖", "uri": maps_url}

        return card

    # datetimepicker action
    today_str = d_cls.today().isoformat()
    default_dt = (d_cls.today() + timedelta(days=180)).isoformat()
    date_action = {
        "type": "datetimepicker",
        "label": "選擇日期",
        "data": "wizard_date",
        "mode": "date",
        "initial": date_str if date_str else default_dt,
        "min": today_str,
        "max": "2030-12-31"
    }

    fields = [
        field_card("name",     "賽事名稱", name,         "請輸入賽事名稱…"),
        field_card("date",     "比賽日期", date_display,  "點此選擇日期",   action=date_action),
        field_card("distance", "比賽距離", dist_display,  "請選擇距離"),
        field_card("location", "比賽地點", location,      "請輸入地點（可跳過）"),
    ]

    # 全部必填完成 → 顯示確認按鈕
    body_extra = []
    if name and date_str and dist_display:
        body_extra.append({
            "type": "button",
            "action": {"type": "postback", "label": "確認登錄 →",
                       "data": "wizard_confirm", "displayText": "確認登錄賽事"},
            "style": "primary", "color": C_HEADER,
            "margin": "md", "height": "sm"
        })

    subtitle_map = {
        "name":     "輸入賽事名稱",
        "date":     "選擇比賽日期",
        "distance": "選擇比賽距離",
        "location": "輸入比賽地點（可跳過）",
    }

    bubble = {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": C_HEADER,
            "paddingTop": "20px", "paddingBottom": "18px",
            "paddingStart": "18px", "paddingEnd": "18px",
            "contents": [
                # 進度條
                {
                    "type": "box", "layout": "horizontal",
                    "spacing": "none", "alignItems": "center",
                    "contents": dots
                },
                # 標題：填寫後顯示賽事名，否則顯示「登錄賽事」
                {"type": "text", "text": name if name else "登錄賽事",
                 "size": "xl", "weight": "bold", "color": "#FFFFFF",
                 "margin": "md", "wrap": True},
                {"type": "text", "text": subtitle_map.get(active_step, "填寫比賽資訊"),
                 "size": "xs", "color": "#FDE68A", "margin": "xs"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical",
            "backgroundColor": C_BODY,
            "paddingAll": "14px", "spacing": "sm",
            "contents": fields + body_extra
        },
        "styles": {
            "header": {"backgroundColor": C_HEADER},
            "body":   {"backgroundColor": C_BODY}
        }
    }

    msg = {"type": "flex", "altText": "登錄賽事", "contents": bubble}
    if quick_replies:
        msg["quickReply"] = {
            "items": [
                {"type": "action",
                 "action": {"type": "message", "label": item, "text": item}}
                for item in quick_replies
            ]
        }
    return msg


def build_wizard_bubble(step: int, total: int, title: str,
                        prompt: str, hint: str = "",
                        quick_replies: list = None) -> dict:
    """登錄賽事步驟式對話 Flex bubble"""
    # 進度圓點
    dots = []
    for i in range(1, total + 1):
        is_current = (i == step)
        dots.append({
            "type": "box", "layout": "vertical",
            "width": "10px", "height": "10px",
            "cornerRadius": "5px",
            "backgroundColor": "#FFFFFF" if is_current else "#FFFFFF55",
            "contents": []
        })
        if i < total:
            dots.append({"type": "box", "layout": "vertical",
                         "width": "16px", "height": "2px",
                         "backgroundColor": "#FFFFFF33", "contents": []})

    msg = {
        "type": "flex",
        "altText": f"登錄賽事 步驟 {step}/{total}",
        "contents": {
            "type": "bubble", "size": "mega",
            "header": {
                "type": "box", "layout": "vertical",
                "backgroundColor": C_HEADER,
                "paddingTop": "18px", "paddingBottom": "18px",
                "paddingStart": "18px", "paddingEnd": "18px",
                "contents": [
                    # 步驟進度點
                    {
                        "type": "box", "layout": "horizontal",
                        "alignItems": "center", "spacing": "none",
                        "contents": dots
                    },
                    # 已確認資訊 or 標題
                    {"type": "text", "text": title,
                     "size": "lg", "weight": "bold", "color": "#FFFFFF",
                     "margin": "md", "wrap": True},
                    # 步驟數
                    {"type": "text", "text": f"{step} / {total}",
                     "size": "xxs", "color": "#FDE68A", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical",
                "backgroundColor": C_BODY,
                "paddingAll": "18px", "spacing": "sm",
                "contents": [
                    {"type": "text", "text": prompt,
                     "size": "md", "weight": "bold", "color": t.TEXT_MAIN,
                     "wrap": True},
                    *([{"type": "text", "text": hint, "size": "xs",
                        "color": t.TEXT_MUTED, "wrap": True, "margin": "xs"}] if hint else []),
                ]
            },
            "styles": {
                "header": {"backgroundColor": C_HEADER},
                "body":   {"backgroundColor": C_BODY}
            }
        }
    }

    # Quick Reply 掛在 flex message 外層
    if quick_replies:
        msg["quickReply"] = {
            "items": [
                {"type": "action",
                 "action": {"type": "message", "label": item, "text": item}}
                for item in quick_replies
            ]
        }
    return msg
