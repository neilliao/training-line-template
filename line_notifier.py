"""
LINE Messaging API 推播
推給自己（User ID）
"""
import os
import requests

import flex_tokens
from zh_tw import convert_payload

TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")
PUSH_URL  = "https://api.line.me/v2/bot/message/push"
REPLY_URL = "https://api.line.me/v2/bot/message/reply"


def send(message: str):
    """推播文字訊息給自己（包成 Flex bubble，同網頁色系，不再送純文字）"""
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": USER_ID,
        "messages": [flex_tokens.text_bubble(message)],
    }
    payload = convert_payload(payload)  # 簡體硬防線：送出前全轉台灣正體
    resp = requests.post(PUSH_URL, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def reply(reply_token: str, message: str, quick_replies: list = None):
    """用 replyToken 回覆文字（包成 Flex bubble；可附 Quick Reply 選項）"""
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    msg = flex_tokens.text_bubble(message)
    if quick_replies:
        msg["quickReply"] = {
            "items": [
                {
                    "type": "action",
                    "action": {"type": "message", "label": item, "text": item}
                }
                for item in quick_replies
            ]
        }
    payload = {"replyToken": reply_token, "messages": [msg]}
    payload = convert_payload(payload)  # 簡體硬防線：送出前全轉台灣正體
    resp = requests.post(REPLY_URL, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def reply_flex(reply_token: str, flex_message: dict):
    """用 replyToken 回覆 Flex Message（支援外層 quickReply）"""
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    # 若 flex_message 帶有 quickReply，提升到訊息層級
    msg = dict(flex_message)
    quick_reply = msg.pop("quickReply", None)
    if quick_reply:
        msg["quickReply"] = quick_reply
    payload = {"replyToken": reply_token, "messages": [msg]}
    payload = convert_payload(payload)  # 簡體硬防線：送出前全轉台灣正體
    resp = requests.post(REPLY_URL, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def send_message_with_quick_reply(message: str, quick_replies: list):
    """推播文字訊息（包成 Flex bubble）+ Quick Reply 選項給自己"""
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    msg = flex_tokens.text_bubble(message)
    msg["quickReply"] = {
        "items": [
            {"type": "action",
             "action": {"type": "message", "label": item[:20], "text": item}}
            for item in quick_replies
        ]
    }
    payload = {"to": USER_ID, "messages": [msg]}
    payload = convert_payload(payload)  # 簡體硬防線：送出前全轉台灣正體
    resp = requests.post(PUSH_URL, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def send_flex(flex_message: dict):
    """推播 Flex Message 給自己"""
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": USER_ID,
        "messages": [flex_message],
    }
    payload = convert_payload(payload)  # 簡體硬防線：送出前全轉台灣正體
    resp = requests.post(PUSH_URL, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def format_activity_message(summary: dict) -> str:
    """格式化單次訓練推播訊息"""
    sport = summary["sport"]
    sport_emoji = {
        "Run": "🏃",
        "Ride": "🚴",
        "Swim": "🏊",
        "Walk": "🚶",
        "Hike": "🥾",
        "Yoga": "🧘",
        "Workout": "🏋️",
        "WeightTraining": "🏋️",
        "Jump": "⬆️",
        "RopeSkipping": "⬆️",
    }.get(sport, "💪")

    # 有距離概念的運動
    has_distance = sport in ("Run", "Ride", "Swim", "Walk", "Hike")

    lines = [
        f"{sport_emoji} 訓練完成！{summary['date']}",
        f"━━━━━━━━━━━━━━━",
        f"📍 {summary['name']}",
        f"⏱ 時間：{summary['moving_time']}",
    ]

    if has_distance and summary.get("distance_km", 0) > 0:
        lines.insert(3, f"📏 距離：{summary['distance_km']} km")
        if summary.get("avg_pace") and summary["avg_pace"] != "N/A":
            lines.append(f"👟 均速：{summary['avg_pace']} /km")

    if summary.get("avg_hr"):
        lines.append(f"❤️ 心率：{summary['avg_hr']} bpm（最高 {summary['max_hr']}）")

    if summary.get("load"):
        lines.append(f"📊 訓練負荷：{summary['load']}")
    elif summary.get("trimp"):
        lines.append(f"📊 TRIMP：{round(summary['trimp'], 1)}")

    return "\n".join(lines)


def format_weekly_report(activities: list, wellness_today: dict = None) -> str:
    """格式化週訓練量報告"""
    total_km = sum(a.get("distance_km", 0) for a in activities if a.get("sport") == "Run")
    total_sessions = len(activities)
    total_time_s = sum(
        _parse_time(a.get("moving_time", "0:00:00")) for a in activities
    )
    h, remainder = divmod(total_time_s, 3600)
    m = remainder // 60

    lines = [
        f"📅 本週訓練報告",
        f"━━━━━━━━━━━━━━━",
        f"🏃 跑量：{round(total_km, 1)} km",
        f"🔢 次數：{total_sessions} 次",
        f"⏱ 總時間：{h}h {m}m",
    ]

    if wellness_today:
        ctl = wellness_today.get("ctl")
        atl = wellness_today.get("atl")
        tsb = wellness_today.get("tsb")
        if ctl and atl and tsb:
            tsb_emoji = "🟢" if tsb >= 0 else "🔴"
            lines += [
                f"━━━━━━━━━━━━━━━",
                f"📈 體能（CTL）：{round(ctl, 1)}",
                f"😓 疲勞（ATL）：{round(atl, 1)}",
                f"{tsb_emoji} 狀態（TSB）：{round(tsb, 1)}",
            ]

    return "\n".join(lines)


def _parse_time(time_str: str) -> int:
    parts = time_str.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 0


def send_location_quick_reply(message: str):
    """推播文字（包成 Flex bubble）＋「傳我的位置」Quick Reply（點了會開 LINE 原生位置選擇器）"""
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    msg = flex_tokens.text_bubble(message)
    msg["quickReply"] = {"items": [
        {"type": "action", "action": {"type": "location", "label": "📍 傳我的位置"}},
    ]}
    payload = {"to": USER_ID, "messages": [msg]}
    payload = convert_payload(payload)  # 簡體硬防線：送出前全轉台灣正體
    resp = requests.post(PUSH_URL, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()
