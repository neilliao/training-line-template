"""
LINE Bot Webhook 伺服器
功能：接收 LINE 訊息，偵測課表文字並自動解析存入 Firebase
部署：Railway
"""
import os
import requests
import hashlib
import hmac
import base64
from flask import Flask, request, abort
from dotenv import load_dotenv
load_dotenv()

import firebase_client as fb
import schedule_parser as sp
import line_notifier as ln
import race_flex as rf
import flex_tokens as t

app = Flask(__name__)

# ── 登錄賽事對話狀態 ─────────────────────────────────────────
# 步驟：name → date → distance → location → confirm
_RACE_PENDING: dict = {}   # {user_id: {"step": "name"|"date"|"distance"|"location", "data": {...}}}

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")


def _verify_signature(body: bytes, signature: str) -> bool:
    """驗證 LINE 簽名，確保請求來自 LINE"""
    if not LINE_CHANNEL_SECRET:
        return True  # 開發模式：略過驗證
    hash_val = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).digest()
    expected = base64.b64encode(hash_val).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()

    data = request.get_json(silent=True) or {}

    # LINE Verify 會送空 events，直接回 200
    if not data.get("events"):
        return "OK", 200

    if not _verify_signature(body, signature):
        abort(400, "Invalid signature")

    for event in data.get("events", []):
        event_type = event.get("type")
        if event_type == "message":
            _handle_message(event)
        elif event_type == "postback":
            _handle_postback(event)

    return "OK", 200


def _parse_race_input(text: str):
    """
    解析賽事輸入：「賽事名稱 日期 距離 地點」
    回傳 dict 或 None（格式錯誤）
    """
    import re
    parts = text.strip().split()
    if len(parts) < 2:
        return None

    # 找日期（YYYY/MM/DD 或 YYYY-MM-DD）
    date_pat = re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})")
    date_str = None
    date_idx = None
    for i, p in enumerate(parts):
        m = date_pat.search(p)
        if m:
            date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            date_idx = i
            break
    if not date_str:
        return None

    name = " ".join(parts[:date_idx]).strip()
    if not name:
        return None

    remaining = parts[date_idx + 1:]

    # 距離
    dist_km = 0.0
    dist_idx = None
    dist_pat = re.compile(r"(\d+(?:\.\d+)?)\s*k(?:m)?", re.IGNORECASE)
    for i, p in enumerate(remaining):
        if p in ("全馬", "FM"):
            dist_km = 42.195; dist_idx = i; break
        if p in ("半馬", "HM"):
            dist_km = 21.0975; dist_idx = i; break
        m = dist_pat.search(p)
        if m:
            dist_km = float(m.group(1)); dist_idx = i; break

    location_parts = [p for i, p in enumerate(remaining) if i != dist_idx]
    location = " ".join(location_parts).strip()

    return {
        "name": name,
        "date": date_str,
        "distance_km": dist_km,
        "location": location,
    }


def _handle_postback(event: dict):
    """處理 postback 事件（Flex 按鈕點擊）"""
    postback     = event.get("postback", {})
    data         = postback.get("data", "")
    reply_token  = event.get("replyToken", "")
    source       = event.get("source", {})
    user_id      = source.get("userId") or source.get("groupId") or "default"

    # ── 訓練詳細數據 ──────────────────────────────────────────
    if data.startswith("detail:"):
        act_id = data.split(":", 1)[1]
        log = fb.get_training_log(act_id)
        if log:
            import flex_builder as fb_flex
            detail_flex = fb_flex.build_detail_bubble(log)
            ln.reply_flex(reply_token, detail_flex)
        else:
            ln.reply(reply_token, "找不到訓練紀錄，可能尚未同步。")
        return

    # ── 深度分析（第二層）：內容在推播當下已生成好存 Firestore，這裡只讀取顯示 ──
    if data.startswith("deep:"):
        act_id = data.split(":", 1)[1]
        log = fb.get_training_log(act_id)
        if log and log.get("deep_analysis"):
            import flex_builder as fb_flex
            deep_flex = fb_flex.build_deep_analysis_bubble(log)
            ln.reply_flex(reply_token, deep_flex)
        elif log:
            ln.reply(reply_token, "深度分析尚未生成完成，稍後再試一次。")
        else:
            ln.reply(reply_token, "找不到訓練紀錄，可能尚未同步。")
        return

    # ── 備賽清單點擊勾稽 ─────────────────────────────────────
    if data.startswith("checklist_done:"):
        parts = data.split(":", 2)
        if len(parts) == 3:
            _, race_id, item_text = parts
            ok = fb.update_race_checklist(race_id, item_text, done=True)
            if ok:
                updated = fb.get_race(race_id)
                flex = {"type": "flex", "altText": f"已完成：{item_text}",
                        "contents": rf.build_race_bubble(updated)}
                ln.reply_flex(reply_token, flex)
            else:
                ln.reply(reply_token, f"更新失敗，找不到「{item_text}」。")
        return

    # ── 登錄賽事：日期選擇（datetimepicker）───────────────────
    if data == "wizard_date":
        date_val = postback.get("params", {}).get("date", "")
        state = _RACE_PENDING.get(user_id)
        if not state:
            return
        state["data"]["date"] = date_val
        state["step"] = "distance"
        _RACE_PENDING[user_id] = state
        flex = rf.build_registration_form(
            state["data"], "distance",
            quick_replies=["全馬", "半馬", "21k", "10k", "5k", "取消"]
        )
        ln.reply_flex(reply_token, flex)
        return

    # ── 登錄賽事：確認登錄 ────────────────────────────────────
    if data == "wizard_confirm":
        state = _RACE_PENDING.get(user_id)
        if not state:
            return
        d = state["data"]
        race = {
            "name":        d.get("name", ""),
            "date":        d.get("date", ""),
            "distance_km": d.get("distance_km", 0),
            "location":    d.get("location", ""),
        }
        _RACE_PENDING.pop(user_id, None)
        race_id = fb.save_race(race)
        race["race_id"] = race_id
        flex = {"type": "flex", "altText": f"賽事已登錄：{race['name']}",
                "contents": rf.build_race_bubble(race)}
        ln.reply_flex(reply_token, flex)
        return


def _send_coach_card(reply_token: str = None, title: str = "今日教練", retries: int = 0):
    """組今日教練合併卡並推播（課表×天氣×身體數據）。
    流程：抓天氣 forecast_bundle → /api/coach（帶 weather_text）→ coach_flex.build(weather)。
    reply_token 有值時先 reply ack（指令路徑）；cron 不帶。
    「今天」「教練」「跑前」共用此函式（跑前只換卡片標題）。

    retries：/api/coach 逾時/失敗時的額外重試次數。**只有不受 Vercel 60s 函式時限
    綁住的呼叫端（daily_reminder.py 走 GitHub Actions，自己的 job timeout 是 3 分鐘）
    才可以傳 >0**——LINE webhook 指令（今天/教練/跑前）走 training-line 自己的
    Vercel 函式，本身已卡在 60s 天花板，重試只會讓函式被殺掉、連這則「暫時離線」
    訊息都送不出去，反而比現在的單次嘗試更差，保持預設 0。
    2026-07-10：/api/coach 串了 intervals+Firebase+Garmin+Claude 四個外部服務，
    隔夜近 8 小時無人呼叫後的第一次冷啟動疊加，偶爾會撞到 50s 逾時（06:00 每日
    提醒實測踩過一次）。"""
    import coach_flex
    import weather_client as wc
    import time

    coach_api = os.environ.get("WELLNESS_COACH_API", "")
    coach_token = os.environ.get("WELLNESS_COACH_TOKEN", "")
    if reply_token:
        ln.reply(reply_token, "教練分析中⋯")
    if not coach_api or not coach_token:
        ln.send("教練服務尚未設定（缺 WELLNESS_COACH_API / TOKEN）。")
        return
    bundle = wc.forecast_bundle()  # {weather_text, today}；失敗回空，不阻斷
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(
                f"{coach_api}/api/coach",
                params={"weather_text": bundle.get("weather_text", "")},
                headers={"X-Access-Token": coach_token},
                timeout=50,  # 容納冷啟動，守 Vercel 60s
            )
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                ln.send(f"教練暫時拿不到資料：{data['error']}")
            else:
                ln.send_flex(coach_flex.build(data, weather=bundle.get("today"), title=title))
            return
        except Exception as e:
            last_err = e
            print(f"[webhook] 教練卡失敗（第 {attempt + 1} 次）：{e}")
            if attempt < retries:
                time.sleep(5)  # 給冷啟動一點喘息時間再試
    print(f"[webhook] 教練卡最終失敗：{last_err}")
    ln.send("教練暫時離線，稍後再試 🙏")


def _submenu_flex(title: str, rows: list) -> dict:
    """Rich menu 二層子選單卡（rows: [(顯示文字, 觸發指令)]）"""
    buttons = [{
        "type": "button", "height": "sm",
        "style": "primary" if i == 0 else "secondary",
        "color": t.WOOD if i == 0 else t.TINT_NEUTRAL,
        "action": {"type": "message", "label": label, "text": text},
    } for i, (label, text) in enumerate(rows)]
    return {
        "type": "flex", "altText": f"{title}選單",
        "contents": {
            "type": "bubble", "size": "kilo",
            "body": {"type": "box", "layout": "vertical", "spacing": "sm",
                     "paddingAll": "16px",
                     "contents": [
                         {"type": "text", "text": title, "size": "sm",
                          "color": t.TEXT_MUTED, "weight": "bold"},
                         *buttons,
                     ]},
        },
    }


def _handle_location(msg: dict, event: dict):
    """收到 LINE 位置訊息 → 用該座標做就地跑前評估（天氣＋最近空品測站＋身體狀態）"""
    source = event.get("source", {})
    if source.get("type") != "user":
        return  # 群組不回應位置訊息
    lat = msg.get("latitude")
    lon = msg.get("longitude")
    address = msg.get("address") or ""
    if lat is None or lon is None:
        return
    print(f"[webhook] 位置訊息：{lat},{lon} {address}")
    ln.reply(event.get("replyToken", ""), "收到位置，就地評估中⋯")
    try:
        import coach_agent
        import coach_flex
        prompt = (f"我現在人在這裡：{address}（緯度 {lat}、經度 {lon}）。"
                  f"幫我做跑前評估：查我的身體狀態，天氣和空氣品質用這個座標查"
                  f"（get_weather 帶 lat/lon），最後告訴我現在適不適合跑、該怎麼跑。")
        ln.send_flex(coach_flex.build_reply(coach_agent.run_coach(prompt)))  # serverless 同步跑（reply 已先送出）
    except Exception as e:
        print(f"[webhook] 位置評估失敗：{e}")
        ln.send(f"就地評估暫時失敗：{e}")


def _handle_message(event: dict):
    msg = event.get("message", {})
    if msg.get("type") == "location":
        _handle_location(msg, event)
        return
    if msg.get("type") != "text":
        return

    text = msg.get("text", "").strip()
    reply_token = event.get("replyToken", "")
    source = event.get("source", {})
    source_type = source.get("type")

    import re

    # ── 指令處理 ─────────────────────────────────────────────
    cmd = text.strip()

    # ── 登錄賽事：對話式輸入流程 ──────────────────────────────
    user_id = source.get("userId") or source.get("groupId") or "default"

    # ── 登錄賽事：步驟式對話 ──────────────────────────────────
    state = _RACE_PENDING.get(user_id)

    if cmd in ("取消", "cancel") and state:
        _RACE_PENDING.pop(user_id, None)
        ln.reply(reply_token, "已取消登錄。")
        return

    if state:
        step = state.get("step")
        data = state.get("data", {})

        if step == "name":
            data["name"] = cmd
            _RACE_PENDING[user_id] = {"step": "date", "data": data}
            # 顯示表單，日期欄 active（有 datetimepicker 按鈕）
            flex = rf.build_registration_form(data, "date", quick_replies=["取消"])
            ln.reply_flex(reply_token, flex)
            return

        if step == "distance":
            dist_map = {"全馬": 42.195, "半馬": 21.0975,
                        "5k": 5.0, "10k": 10.0, "21k": 21.0975, "42k": 42.195}
            if cmd in dist_map:
                data["distance_km"] = dist_map[cmd]
            else:
                import re as _re
                m = _re.search(r"(\d+(?:\.\d+)?)\s*k", cmd, _re.IGNORECASE)
                data["distance_km"] = float(m.group(1)) if m else 0.0
            _RACE_PENDING[user_id] = {"step": "location", "data": data}
            flex = rf.build_registration_form(data, "location",
                                              quick_replies=["跳過", "取消"])
            ln.reply_flex(reply_token, flex)
            return

        if step == "location":
            data["location"] = "" if cmd == "跳過" else cmd
            _RACE_PENDING[user_id] = {"step": "confirm", "data": data}
            # 顯示完整表單 + 確認按鈕
            flex = rf.build_registration_form(data, "location")
            ln.reply_flex(reply_token, flex)
            return

    if cmd in ("登錄賽事", "新增賽事", "賽事登錄"):
        _RACE_PENDING[user_id] = {"step": "name", "data": {}}
        flex = rf.build_registration_form({}, "name", quick_replies=["取消"])
        ln.reply_flex(reply_token, flex)
        return

    if cmd in ("賽事", "我的賽事", "賽事清單", "race"):
        races = fb.get_upcoming_races()
        if not races:
            ln.reply(reply_token, "目前沒有登錄賽事，傳「登錄賽事」開始新增。")
            return
        flex = rf.build_races_carousel(races)
        ln.reply_flex(reply_token, flex)
        return

    # 完成 <賽事關鍵字> <項目>（例：完成 黃金海岸 報名）
    if cmd.startswith("完成 ") or cmd.startswith("勾稽 "):
        parts = cmd.split(" ", 2)
        if len(parts) == 3:
            _, race_kw, item_kw = parts
            races = fb.get_upcoming_races()
            matched = [r for r in races if race_kw in r.get("name", "")]
            if not matched:
                ln.reply(reply_token, f"找不到包含「{race_kw}」的賽事。")
                return
            race = matched[0]
            ok = fb.update_race_checklist(race["race_id"], item_kw, done=True)
            if ok:
                updated = fb.get_race(race["race_id"])
                flex = {"type": "flex", "altText": f"已更新：{race['name']}",
                        "contents": rf.build_race_bubble(updated)}
                ln.reply_flex(reply_token, flex)
            else:
                ln.reply(reply_token, f"找不到「{item_kw}」這個項目，請確認名稱。")
            return

    # ── 一般指令 ──────────────────────────────────────────────

    if cmd in ("課表", "本週課表", "schedule"):
        print(f"[webhook] 指令：課表查詢")
        ln.reply(reply_token, "載入課表中⋯")
        def _push_schedule():
            try:
                schedule = fb.get_latest_schedule()
                if schedule:
                    flex = _build_schedule_flex(schedule)
                    ln.send_flex(flex)
                else:
                    ln.send("目前沒有課表資料，請先轉貼教練課表。")
            except Exception as e:
                print(f"[webhook] 課表查詢失敗：{e}")
                ln.send(f"課表查詢失敗：{e}")
        _push_schedule()  # serverless 無背景執行緒：同步跑（「載入課表中⋯」已先 reply 送出）
        return

    if cmd in ("今天", "今日", "今日課表", "today"):
        print("[webhook] 指令：今日（合併教練卡）")
        _send_coach_card(reply_token)
        return

    if cmd in ("數據", "本週活動", "活動", "stats"):
        print(f"[webhook] 指令：本週活動")
        try:
            import weekly_activity_flex as waf
            flex = waf.build_weekly_activity_flex()
            if not flex:
                ln.reply(reply_token, "本週尚無活動紀錄。")
                return
            ln.reply_flex(reply_token, flex)
        except Exception as e:
            print(f"[webhook] 本週活動失敗：{e}")
            ln.reply(reply_token, f"查詢失敗：{e}")
        return

    if cmd in ("週報", "本週", "report"):
        print(f"[webhook] 指令：週報")
        try:
            import weekly_report as wr
            wr.run()
        except Exception as e:
            ln.reply(reply_token, f"週報失敗：{e}")
        return

    if cmd in ("教練", "今天教練", "coach"):
        print("[webhook] 指令：教練（合併卡）")
        _send_coach_card(reply_token)
        return

    if cmd in ("課表選單", "賽事選單"):
        title, rows = (("課表", [("今日課表", "今天"), ("本週課表", "課表"),
                                 ("本週數據", "數據"), ("排進錶", "把這週課表排進錶"),
                                 ("換角度分析", "換個角度分析這週課表")])
                       if cmd == "課表選單" else
                       ("賽事", [("我的賽事", "賽事"), ("登錄賽事", "登錄賽事"), ("週報", "週報")]))
        ln.reply_flex(reply_token, _submenu_flex(title, rows))
        return

    if cmd in ("跑前", "跑前評估", "prerun"):
        print("[webhook] 指令：跑前評估（合併卡）")
        _send_coach_card(reply_token, title="跑前評估")
        ln.send_location_quick_reply(
            "要行前規劃的話，直接回我「地點＋距離」，例如：河濱 10k、公園 6k。"
            "或按下面的按鈕傳你的位置，我用你所在地的天氣和空氣品質就地評估。")
        return

    # ── 課表偵測（原有邏輯）──────────────────────────────────
    is_schedule = bool(
        re.search(r"\d{4}\s+\d{2}/\d{2}-\d{2}/\d{2}", text) and
        ("D1" in text or "D2" in text or os.getenv("ATHLETE_NAME", "小明") in text or "@AII" in text or "@All" in text)
    )

    if not is_schedule:
        # 非指令、非課表的自由文字 → 對話教練（phase 2，Claude tool-use）。
        # 只在 1-on-1 私訊回應；群組（課表來源）不插話，避免每句話都觸發。
        if source_type == "user":
            try:
                ln.reply(reply_token, "教練思考中⋯")
                import coach_agent
                import coach_flex
                ln.send_flex(coach_flex.build_reply(coach_agent.run_coach(text)))  # serverless 無背景執行緒：同步跑（reply 已先送出）
            except Exception as e:
                print(f"[webhook] coach 失敗：{e}")
                ln.send(f"教練暫時無法回應：{e}")
        return

    print(f"[webhook] 偵測到課表，來源：{source_type}")
    print(f"[webhook] 課表 raw（前300字）：{repr(text[:300])}")

    parsed = sp.parse_schedule(text)
    week_range = parsed.get("week_range", "（未知週期）")
    days_found = list(parsed.get("days", {}).keys())
    print(f"[webhook] 解析週期：{week_range}，找到天數：{days_found}")

    week_key = fb.save_schedule(parsed)
    print(f"[webhook] 已存入 Firebase：{week_key}")

    # 單週增量落地 coach_history（供 coach_logic_learner.py 持續學習用；
    # 不影響推播主流程，失敗不擋課表卡片送出）
    try:
        import data_vault
        data_vault.land_schedule_week(parsed, week_key)
    except Exception as e:
        print(f"[webhook] coach_history 增量落地失敗：{e}")

    # 課表 AI 分析（背景執行緒，不阻塞 webhook 回應）
    def _run_schedule_ai(p, wk):
        try:
            import ai_analyzer as ai
            ai_result = ai.analyze_schedule(p)
            if ai_result:
                fb.update_schedule_ai_analysis(wk, ai_result)
                print(f"[webhook] 課表 AI 分析完成：{ai_result.get('goal', '')[:30]}...")
        except Exception as e:
            print(f"[webhook] 課表 AI 分析失敗：{e}")

    # 先秒回課表 Flex（reply token 單次有效，盡早用），再同步跑 AI 分析
    flex = _build_schedule_flex(parsed)
    ln.reply_flex(reply_token, flex)
    _run_schedule_ai(parsed, week_key)  # serverless 無背景執行緒：回應後同步寫入 Firestore


def _weather_accent(code: int) -> tuple:
    """WMO 天氣代碼 → (header 背景色, emoji, 天氣描述)。色階收斂到 mindflows 色系家族。"""
    if code == 0:
        return t.SKY_DEEP, "☀️", "晴天"
    elif code == 1:
        return t.SKY_DEEP, "🌤️", "晴時多雲"
    elif code == 2:
        return t.INK2, "⛅", "多雲"
    elif code == 3:
        return t.INK2, "☁️", "陰天"
    elif code in (45, 48):
        return t.INK2, "🌫️", "霧"
    elif code in (51, 53, 55):
        return t.RAIN_DEEP, "🌦️", "毛毛雨"
    elif code in (61, 63):
        return t.RAIN_DEEP, "🌧️", "小雨"
    elif code in (65, 80, 81, 82):
        return t.RAIN_DEEP, "🌧️", "中大雨"
    elif code in (95, 96, 99):
        return t.WOOD, "⛈️", "雷雨"
    else:
        return t.INK2, "🌡️", ""


def _fetch_day_weather(date_str: str, day_num: int) -> dict:
    """抓單日天氣預報（date_str: YYYY-MM-DD），回傳詳細天氣資訊"""
    import weather_client as _wc
    if day_num == 3:
        lat = float(os.getenv("D4_LAT", "25.0579"))
        lon = float(os.getenv("D4_LON", "121.5673"))
    else:
        lat, lon = None, None
    return _wc.get_daily_forecast(date_str, lat=lat, lon=lon)


def _fetch_day_weather_legacy(date_str: str, day_num: int) -> dict:
    """（備用）直接呼叫 Open-Meteo，已改用 weather_client.get_daily_forecast"""
    import requests as req
    if day_num == 3:
        lat = float(os.getenv("D4_LAT", "25.0579"))
        lon = float(os.getenv("D4_LON", "121.5673"))
    else:
        lat, lon = 25.0478, 121.5319

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        resp = req.get(url, params={
            "latitude": lat, "longitude": lon,
            "daily": ",".join([
                "weathercode",
                "temperature_2m_max", "temperature_2m_min",
                "apparent_temperature_max", "apparent_temperature_min",
                "precipitation_sum", "precipitation_probability_max",
            ]),
            "hourly": "relativehumidity_2m",
            "timezone": "Asia/Taipei",
            "start_date": date_str, "end_date": date_str,
        }, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        daily  = data.get("daily", {})
        hourly = data.get("hourly", {})

        def dv(key):
            v = daily.get(key, [None])
            return v[0] if v else None

        # 取下午 1-3 點的平均濕度（index 13-15）
        humidity_vals = (hourly.get("relativehumidity_2m") or [])
        humidity_afternoon = [humidity_vals[i] for i in range(13, 16) if i < len(humidity_vals) and humidity_vals[i] is not None]
        humidity = round(sum(humidity_afternoon) / len(humidity_afternoon)) if humidity_afternoon else None

        t_max    = round(dv("temperature_2m_max"))    if dv("temperature_2m_max")    is not None else None
        t_min    = round(dv("temperature_2m_min"))    if dv("temperature_2m_min")    is not None else None
        at_max   = round(dv("apparent_temperature_max"))  if dv("apparent_temperature_max")  is not None else None
        at_min   = round(dv("apparent_temperature_min"))  if dv("apparent_temperature_min")  is not None else None
        precip   = round(dv("precipitation_sum"), 1)  if dv("precipitation_sum")    is not None else None
        rain_pct = int(dv("precipitation_probability_max")) if dv("precipitation_probability_max") is not None else None
        code     = int(dv("weathercode")) if dv("weathercode") is not None else None

        # 舒適度
        comfort = _comfort_level(t_max, humidity)

        return {
            "code": code,
            "t_max": t_max, "t_min": t_min,
            "at_max": at_max, "at_min": at_min,
            "humidity": humidity,
            "precip": precip,
            "rain_pct": rain_pct,
            "comfort": comfort,
        }
    except Exception as e:
        print(f"[weather] {date_str} 預報失敗：{e}")
        return {}


def _comfort_level(t_max: int, humidity: int) -> str:
    """依氣溫 + 濕度判斷體感舒適度"""
    if t_max is None:
        return ""
    if t_max >= 35:
        return "高溫危險" if (humidity or 0) >= 70 else "酷熱"
    if t_max >= 32:
        return "悶熱" if (humidity or 0) >= 70 else "炎熱"
    if t_max >= 28:
        return "偏熱" if (humidity or 0) >= 75 else "溫熱"
    if t_max >= 22:
        return "舒適"
    if t_max >= 16:
        return "涼爽"
    if t_max >= 10:
        return "偏冷"
    return "寒冷"


def _build_schedule_flex(parsed: dict) -> dict:
    """將解析後課表建成 Carousel，D1-D7 每天一張 bubble，含天氣預報"""
    import re
    from datetime import date as date_cls, timedelta

    week_range = parsed.get("week_range", "")
    days = parsed.get("days", {})
    WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]

    # 計算 D1 的實際日期
    m = re.search(r"(\d{4})\s+(\d{2})/(\d{2})", week_range)
    base_date = None
    if m:
        try:
            base_date = date_cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass

    # D1-D5 各一張，D6+D7 合併為週末一張
    weekday_keys = [f"D{i}" for i in range(1, 6)]
    bubbles = []

    # 預先並行抓天氣（只抓今天和未來日期，過去日期 CWA 無預報資料）
    from concurrent.futures import ThreadPoolExecutor, as_completed
    _wx_cache = {}
    today_cls = date_cls.today()
    if base_date:
        def _fetch(day_num):
            day_date = base_date + timedelta(days=day_num)
            if day_date < today_cls:  # 過去日期跳過
                return day_num, {}
            return day_num, _fetch_day_weather(day_date.strftime("%Y-%m-%d"), day_num)
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = [pool.submit(_fetch, i) for i in range(7)]
            for f in as_completed(futs):
                try:
                    dn, wx = f.result()
                    _wx_cache[dn] = wx
                except Exception:
                    pass

    def make_bubble(key, day_num, label, date_str_override=None):
        info = days.get(key, {})
        is_rest = info.get("is_rest", False) or not info.get("is_for_me", False)
        workout = info.get("my_workout", "")
        if not info.get("is_for_me", False):
            is_rest = True

        # 天氣（從預先抓好的快取讀取）
        wx = {}
        day_date_str = ""
        if base_date and day_num is not None:
            day_date = base_date + timedelta(days=day_num)
            day_date_str = date_str_override or day_date.strftime("%Y-%m-%d")
            wx = _wx_cache.get(day_num, {})

        code     = wx.get("code")
        t_max    = wx.get("t_max")
        t_min    = wx.get("t_min")
        at_max   = wx.get("at_max")
        at_min   = wx.get("at_min")
        humidity = wx.get("humidity")
        precip   = wx.get("precip")
        rain_pct = wx.get("rain_pct")
        comfort  = wx.get("comfort", "")

        # Header 配色
        if is_rest:
            accent      = t.INK2
            wx_emoji    = "😴"
            wx_desc     = "休息日"
        elif code is not None:
            accent, wx_emoji, wx_desc = _weather_accent(code)
        else:
            options = [t.WOOD, t.SKY_DEEP, t.GREEN_DEEP, t.AMBER_DEEP, t.RAIN_DEEP]
            accent = options[(day_num or 0) % len(options)]
            wx_emoji, wx_desc = "🏃", "訓練日"

        temp_range = f"{t_min}–{t_max}°C" if t_max and t_min else (f"{t_max}°C" if t_max else "")

        # ── 天氣 bento grid（3欄）──────────────────────────
        def wx_cell(emoji_t, label_t, value_t, val_color=t.TEXT_MAIN):
            return {
                "type": "box", "layout": "vertical",
                "backgroundColor": t.BG_CARD,
                "cornerRadius": "10px",
                "paddingTop": "10px", "paddingBottom": "10px",
                "paddingStart": "6px", "paddingEnd": "6px",
                "alignItems": "center", "flex": 1,
                "contents": [
                    {"type": "text", "text": emoji_t, "size": "lg", "align": "center"},
                    {"type": "text", "text": value_t, "size": "xs",
                     "weight": "bold", "color": val_color, "align": "center", "wrap": True},
                    {"type": "text", "text": label_t, "size": "xxs",
                     "color": t.TEXT_MUTED, "align": "center"}
                ]
            }

        wx_bento_rows = []
        row1_cells = []
        row2_cells = []
        if t_max and t_min:
            row1_cells.append(wx_cell("🌡️", "氣溫", f"{t_min}–{t_max}°C"))
        if at_max and at_min:
            row1_cells.append(wx_cell("🤔", "體感", f"{at_min}–{at_max}°C", t.AMBER_DEEP))
        if humidity is not None:
            row1_cells.append(wx_cell("💧", "濕度", f"{humidity}%"))
        if comfort:
            c_color = t.GREEN if comfort in ("舒適","涼爽") else t.RED if "熱" in comfort or "危" in comfort else t.TEXT_MUTED
            row2_cells.append(wx_cell("😊", "舒適度", comfort, c_color))
        if precip is not None:
            row2_cells.append(wx_cell("🌧️", "雨量", f"{precip}mm"))
        if rain_pct is not None:
            p_color = t.SKY_DEEP if rain_pct >= 50 else t.TEXT_MUTED
            row2_cells.append(wx_cell("☂️", "降雨率", f"{rain_pct}%", p_color))

        if row1_cells:
            wx_bento_rows.append({
                "type": "box", "layout": "horizontal",
                "spacing": "sm", "contents": row1_cells
            })
        if row2_cells:
            wx_bento_rows.append({
                "type": "box", "layout": "horizontal",
                "spacing": "sm", "contents": row2_cells
            })

        wx_section = []
        if wx_bento_rows:
            wx_section = [
                {"type": "separator", "margin": "lg", "color": t.BORDER},
                {"type": "text", "text": "天氣預報",
                 "size": "xxs", "color": t.TEXT_MUTED, "weight": "bold", "margin": "md"},
                {
                    "type": "box", "layout": "vertical",
                    "backgroundColor": t.BG_BODY, "cornerRadius": "12px",
                    "paddingAll": "10px", "spacing": "sm",
                    "contents": wx_bento_rows
                }
            ]

        # ── 課表卡（左側 accent bar）────────────────────────
        if is_rest:
            bar_color   = t.BORDER
            w_color     = t.TEXT_MUTED
            w_weight    = "regular"
            w_size      = "sm"
            workout_display = "好好休息，明天繼續加油"
            footer_text = "休息也是訓練的一部分 🌙"
            label_color = t.TEXT_MUTED
            label_text  = "休息日"
        else:
            bar_color   = t.AMBER   # 琥珀色 accent
            w_color     = t.TEXT_MAIN
            w_weight    = "bold"
            w_size      = "md"
            workout_display = workout or "查看原始課表"
            footer_text = "完成後自動推播訓練紀錄 💪"
            label_color = t.AMBER
            label_text  = "今日課表"

        workout_card = {
            "type": "box", "layout": "horizontal",
            "backgroundColor": t.BG_CARD, "cornerRadius": "12px",
            "paddingAll": "0px", "spacing": "none",
            "contents": [
                # 左側色條
                {
                    "type": "box", "layout": "vertical",
                    "backgroundColor": bar_color,
                    "width": "4px", "cornerRadius": "12px",
                    "contents": [{"type": "filler"}]
                },
                # 課表文字
                {
                    "type": "box", "layout": "vertical",
                    "paddingTop": "14px", "paddingBottom": "14px",
                    "paddingStart": "12px", "paddingEnd": "12px",
                    "flex": 1,
                    "contents": [
                        {"type": "text", "text": workout_display,
                         "size": w_size, "color": w_color,
                         "wrap": True, "weight": w_weight}
                    ]
                }
            ]
        }

        # ── Header 週次＋天氣條 ──────────────────────────────
        weekday_label = f"週{WEEKDAY_ZH[day_num]}" if day_num is not None and day_num <= 6 else "週末"

        # Header 天氣數據列（圖示 + 氣溫 / 濕度 / 降雨機率）
        header_wx_items = []
        if temp_range:
            header_wx_items.append(f"{wx_emoji} {temp_range}")
        if humidity is not None:
            header_wx_items.append(f"💧 {humidity}%")
        if rain_pct is not None:
            header_wx_items.append(f"☂️ {rain_pct}%")

        # 天氣數據 pill（白底半透明 3 格）
        def wx_stat_box(text_val):
            return {
                "type": "box", "layout": "horizontal",
                "backgroundColor": "#FFFFFF26",
                "cornerRadius": "8px",
                "paddingTop": "6px", "paddingBottom": "6px",
                "paddingStart": "8px", "paddingEnd": "8px",
                "flex": 1, "alignItems": "center",
                "contents": [
                    {"type": "text", "text": text_val,
                     "size": "xxs", "color": "#FFFFFF",
                     "weight": "bold", "align": "center", "wrap": True}
                ]
            }

        wx_stats_row_contents = []
        for item in header_wx_items:
            if wx_stats_row_contents:
                wx_stats_row_contents.append({"type": "box", "layout": "vertical", "width": "6px", "contents": []})
            wx_stats_row_contents.append(wx_stat_box(item))

        header_contents = [
            # 週期 + 日期
            {
                "type": "box", "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": week_range,
                     "size": "xxs", "color": "#FFFFFFB3", "flex": 1},
                    {"type": "text", "text": day_date_str,
                     "size": "xxs", "color": "#FFFFFFB3",
                     "align": "end", "flex": 0}
                ]
            },
            # 大標：D2 週二
            {
                "type": "box", "layout": "horizontal",
                "margin": "sm", "alignItems": "flex-end",
                "contents": [
                    {"type": "text", "text": label,
                     "size": "5xl", "weight": "bold",
                     "color": "#FFFFFF", "flex": 0},
                    {"type": "text", "text": f"  {weekday_label}",
                     "size": "xl", "weight": "bold",
                     "color": "#FFFFFFCC",
                     "gravity": "bottom", "flex": 0}
                ]
            },
        ]

        if wx_stats_row_contents:
            # 天氣數據 3 格 row
            header_contents.append({
                "type": "box", "layout": "horizontal",
                "margin": "md", "spacing": "none",
                "contents": wx_stats_row_contents
            })
        else:
            # 無天氣資料：顯示天氣描述純文字
            header_contents.append({
                "type": "text", "text": f"{wx_emoji} {wx_desc}",
                "size": "sm", "color": "#FFFFFFCC",
                "margin": "md", "weight": "bold"
            })

        bubble = {
            "type": "bubble", "size": "mega",
            "header": {
                "type": "box", "layout": "vertical",
                "backgroundColor": accent,
                "paddingTop": "20px", "paddingBottom": "20px",
                "paddingStart": "18px", "paddingEnd": "18px",
                "contents": header_contents
            },
            "body": {
                "type": "box", "layout": "vertical",
                "backgroundColor": t.BG_BODY,
                "paddingAll": "16px", "spacing": "md",
                "contents": [
                    # 課表標籤
                    {"type": "text", "text": label_text,
                     "size": "xxs", "color": label_color, "weight": "bold"},
                    # 課表卡
                    workout_card,
                    # footer
                    {"type": "text", "text": footer_text,
                     "size": "xxs", "color": t.TEXT_MUTED, "wrap": True},
                    # 天氣 bento
                    *wx_section
                ]
            },
            "styles": {
                "header": {"backgroundColor": accent},
                "body":   {"backgroundColor": t.BG_BODY}
            }
        }
        return bubble

    # D1–D5
    for key in weekday_keys:
        day_num = int(key[1:]) - 1
        bubbles.append(make_bubble(key, day_num, key))

    # 週末：D6+D7 合併，取有課表的那天；若都有就都顯示
    d6_info = days.get("D6", {})
    d7_info = days.get("D7", {})
    weekend_raw = [k for k in days if "週末" in k]

    # 找週末課表：優先 週末有氧... key，其次 D6/D7
    weekend_workout = ""
    for wk in weekend_raw:
        w = days[wk].get("my_workout", "")
        if w and w != "休息":
            weekend_workout = w
            break
    if not weekend_workout:
        for dk in ("D6", "D7"):
            info = days.get(dk, {})
            if info.get("is_for_me") and not info.get("is_rest"):
                weekend_workout = info.get("my_workout", "")
                break

    # 週末 bubble：用 D6 的天氣（週六），label = 週末
    weekend_day_num = 5  # 週六
    weekend_info = {"is_for_me": bool(weekend_workout), "is_rest": not weekend_workout, "my_workout": weekend_workout}
    days["_weekend"] = weekend_info
    wb = make_bubble("_weekend", weekend_day_num, "週末")
    # 修正 header label
    wb["header"]["contents"][1]["contents"][0]["text"] = "週末"
    bubbles.append(wb)

    # AI 分析卡（若有）
    ai = parsed.get("ai_analysis")
    if ai and (ai.get("goal") or ai.get("notes")):
        ai_bubble = {
            "type": "bubble",
            "header": {
                "type": "box", "layout": "vertical",
                "backgroundColor": t.WOOD, "paddingAll": "16px",
                "contents": [
                    {"type": "text", "text": "🤖 AI 課表解析",
                     "color": "#FFFFFF", "size": "sm", "weight": "bold"},
                    {"type": "text", "text": week_range,
                     "color": "#FFFFFFB3", "size": "xxs", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical",
                "backgroundColor": t.BG_BODY, "paddingAll": "16px", "spacing": "md",
                "contents": [
                    *([{
                        "type": "box", "layout": "vertical", "spacing": "xs",
                        "contents": [
                            {"type": "text", "text": "本週目標",
                             "size": "xxs", "color": t.SKY_DEEP, "weight": "bold"},
                            {"type": "text", "text": ai.get("goal", ""),
                             "size": "xs", "color": t.TEXT_MAIN, "wrap": True}
                        ]
                    }] if ai.get("goal") else []),
                    *([{"type": "separator", "color": t.BORDER}] if ai.get("goal") and ai.get("notes") else []),
                    *([{
                        "type": "box", "layout": "vertical", "spacing": "xs",
                        "contents": [
                            {"type": "text", "text": "注意事項",
                             "size": "xxs", "color": t.AMBER, "weight": "bold"},
                            {"type": "text", "text": ai.get("notes", ""),
                             "size": "xs", "color": t.TEXT_MAIN, "wrap": True}
                        ]
                    }] if ai.get("notes") else [])
                ]
            },
            "styles": {
                "header": {"backgroundColor": t.WOOD},
                "body": {"backgroundColor": t.BG_BODY}
            }
        }
        bubbles.append(ai_bubble)

    return {
        "type": "flex",
        "altText": f"本週課表 {week_range}",
        "contents": {"type": "carousel", "contents": bubbles}
    }


@app.route("/coach-test")
def coach_test():
    """phase 2 對話教練測試端點：/coach-test?q=你的問題（暫時 scaffold，驗證後接 LINE webhook）"""
    q = request.args.get("q", "")
    hdr = {"Content-Type": "text/plain; charset=utf-8"}
    if not q:
        return "用 ?q=你的問題 測試對話教練", 200, hdr
    try:
        import coach_agent
        import json as _json
        return _json.dumps(coach_agent.run_coach(q), ensure_ascii=False, indent=2), 200, hdr
    except Exception as e:
        return f"coach error: {e}", 200, hdr


@app.route("/poll", methods=["GET", "POST"])
def poll():
    """每 30 分鐘由 cron 呼叫，偵測新訓練並推播"""
    try:
        import poller
        poller.run()
        return "OK", 200
    except Exception as e:
        print(f"[poll] 失敗：{e}")
        return f"ERROR: {e}", 500


@app.route("/weekly-report", methods=["GET", "POST"])
def weekly_report():
    """每週日 21:00 由 cron 呼叫，推播本週訓練報告"""
    try:
        import weekly_report as wr
        wr.run()
        return "OK", 200
    except Exception as e:
        print(f"[weekly-report] 失敗：{e}")
        return f"ERROR: {e}", 500


@app.route("/daily-remind", methods=["GET", "POST"])
def daily_remind():
    """每日 9:00 由 Railway Cron 呼叫，推播今日課表提醒"""
    debug = request.args.get("debug") == "1"
    try:
        import importlib, daily_reminder as dr
        importlib.reload(dr)
        if debug:
            import firebase_client as fb
            from datetime import date
            schedule = fb.get_latest_schedule()
            week_range = schedule.get("week_range", "") if schedule else "no schedule"
            days = schedule.get("days", {}) if schedule else {}
            day_key = dr._find_today_key(week_range, days)
            info = days.get(day_key, {})
            return {
                "today": str(date.today()),
                "week_range": week_range,
                "day_key": day_key,
                "is_for_me": info.get("is_for_me"),
                "my_workout": info.get("my_workout"),
            }, 200
        import io, sys
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            dr.main()
        finally:
            sys.stdout = old_stdout
        logs = buf.getvalue()
        return f"OK\n---\n{logs}", 200
    except Exception as e:
        import traceback
        return f"ERROR: {e}\n{traceback.format_exc()}", 500


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


@app.route("/schedule.ics", methods=["GET"])
def schedule_ics():
    """課表日曆訂閱端點（iPhone 行事曆「加入訂閱行事曆」用）。

    認證：?token= 比對環境變數 ICS_TOKEN（constant-time）；
    ICS_TOKEN 未設或 token 不符一律 404，不洩漏端點存在。
    內容：本週課表（週末教練晚發，讀到什麼給什麼）＋下週（有才給）。
    """
    import ics_builder as icsb
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    expected = os.getenv("ICS_TOKEN", "")
    token = request.args.get("token", "")
    if not expected or not hmac.compare_digest(
        token.encode("utf-8"), expected.encode("utf-8")
    ):
        abort(404)

    # 與「課表」指令同一條讀取路徑（schedules collection，parsed_at DESC）
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    this_monday = today - timedelta(days=today.weekday())
    next_monday = this_monday + timedelta(days=7)

    current = None   # (days, base_date) 本週
    upcoming = None  # (days, base_date) 下週
    for doc in fb.get_recent_schedules(limit=6):
        base = icsb.parse_week_start(doc.get("week_range", ""))
        if base is None:
            continue
        if current is None and this_monday <= base < next_monday:
            current = (doc.get("days", {}), base)
        elif upcoming is None and next_monday <= base < next_monday + timedelta(days=7):
            upcoming = (doc.get("days", {}), base)

    ics = icsb.build_schedule_ics(
        current[0] if current else {},
        current[1] if current else None,
        next_days=upcoming[0] if upcoming else None,
        next_base_date=upcoming[1] if upcoming else None,
    )
    return app.response_class(ics, content_type="text/calendar; charset=utf-8")



@app.route("/version", methods=["GET"])
def version():
    import subprocess
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        commit = "unknown"
    return commit, 200


@app.route("/check-schedule", methods=["GET"])
def check_schedule():
    """確認最新課表的 ai_analysis 是否已存入 Firebase"""
    doc = fb.get_latest_schedule()
    if not doc:
        return "no schedule in Firebase", 200
    week = doc.get("week_range", "?")
    ai = doc.get("ai_analysis")
    keys = list(doc.keys())
    if not ai:
        return f"schedule found (week={week}) keys={keys} but no ai_analysis", 200
    return f"OK week={week} goal={ai.get('goal','')[:80]} notes={ai.get('notes','')[:40]}", 200


@app.route("/debug-remind", methods=["GET"])
def debug_remind():
    """回傳合併教練卡的輸入（今日課表 key + 天氣 bundle），不推播、不打 /api/coach。"""
    import json
    import daily_reminder as dr
    import weather_client as wc
    from datetime import date
    schedule = fb.get_latest_schedule()
    if not schedule:
        return "no schedule", 200
    week_range = schedule.get("week_range", "")
    days = schedule.get("days", {})
    day_key = dr._find_today_key(week_range, days)
    info = days.get(day_key, {}) if day_key else {}
    bundle = wc.forecast_bundle()
    result = {
        "today": str(date.today()),
        "week_range": week_range,
        "day_key": day_key,
        "today_workout": info.get("my_workout"),
        "is_rest": info.get("is_rest"),
        "weather_text": bundle.get("weather_text"),
        "weather_today": bundle.get("today"),
    }
    return json.dumps(result, ensure_ascii=False), 200


@app.route("/test-schedule-flex", methods=["GET"])
def test_schedule_flex():
    """回傳課表 Carousel JSON 結構（不推播），用來 debug"""
    import json
    try:
        schedule = fb.get_latest_schedule()
        if not schedule:
            return "no schedule", 200
        flex = _build_schedule_flex(schedule)
        bubble_count = len(flex.get("contents", {}).get("contents", []))
        last_bubble_type = flex["contents"]["contents"][-1].get("header", {}).get("contents", [{}])[0].get("text", "?")
        return f"OK bubbles={bubble_count} last_header={last_bubble_type}", 200
    except Exception as e:
        import traceback
        return f"ERROR: {e}\n{traceback.format_exc()}", 200


@app.route("/retry-ai", methods=["GET"])
def retry_ai():
    """手動重跑最新課表的 AI 分析"""
    import ai_analyzer as ai
    doc = fb.get_latest_schedule()
    if not doc:
        return "no schedule", 200
    week_key = doc.get("week_range", "").replace(" ", "_").replace("/", "-")
    ai_result = ai.analyze_schedule(doc)
    if not ai_result:
        return "AI failed (check ANTHROPIC_API_KEY or model)", 200
    fb.update_schedule_ai_analysis(week_key, ai_result)
    return f"OK goal={ai_result.get('goal','')[:60]}", 200


@app.route("/inject-schedule", methods=["POST"])
def inject_schedule():
    """手動注入課表文字（繞過 LINE），用於 LINE 貼文亂碼時的備援"""
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return "missing text", 400
    parsed = sp.parse_schedule(text)
    week_range = parsed.get("week_range", "（未知）")
    week_key = fb.save_schedule(parsed)
    try:
        import data_vault
        data_vault.land_schedule_week(parsed, week_key)
    except Exception as e:
        print(f"[inject] coach_history 增量落地失敗：{e}")

    def _run_ai(p, wk):
        try:
            import ai_analyzer as ai
            ai_result = ai.analyze_schedule(p)
            if ai_result:
                fb.update_schedule_ai_analysis(wk, ai_result)
        except Exception as e:
            print(f"[inject] AI 失敗：{e}")
    _run_ai(parsed, week_key)  # serverless 無背景執行緒：同步跑
    day_summary = {k: v.get("my_workout", "")[:40] for k, v in parsed["days"].items()}
    return {"ok": True, "week": week_range, "days": day_summary}, 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
