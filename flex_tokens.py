"""
LINE Flex 色彩系統 SoT，與 wellness-dashboard `templates/v2.html` 的 mindflows
色票同源（:root CSS 變數）。所有 Flex bubble 建構器（flex_builder / coach_flex /
race_flex / weekly_report / weekly_activity_flex / webhook_server 子選單）
一律 import 這裡的常數，不再各自定義 hex。

改色只改這一份，全部卡片跟著變（教訓見道籍 LINE-FLEX-SYSTEM 事件）。
"""
from __future__ import annotations  # dict | None 相容 Python 3.9（/usr/bin/python3）

# ── 與網頁同源的基礎色票 ─────────────────────────────────────────
BG        = "#FFFFFF"   # 頁面 / 卡片白底
INK       = "#111110"   # 主文字
INK2      = "#555250"   # 次要 / 靜音文字
LINE      = "#D8D4CE"   # 分隔線、淡邊框
WOOD      = "#5C4420"   # 主品牌強調色（深木棕，網頁 kicker/區塊標籤同色）
SKY       = "#5B9BD5"   # 次強調色（晴天藍，數字重點用）
SKY_SOFT  = "#C7DCF0"   # 淺藍（底色用，非白字承載）
PAPER     = "#FAF9F6"   # 卡片內底色 / 頁面底色（暖白）
AMBER     = "#C08A2D"   # 提醒 / 警示
GREEN     = "#6E9459"   # 成功 / 正向
RED       = "#BB5A4C"   # 危險 / 落後

# ── 白字承載用「加深版」（SKY / AMBER / GREEN 直接當純色 header 底時，
#    對白字對比不足，比照現有 weather 色表「加深版」做法，WCAG AA 驗過）──
SKY_DEEP   = "#2F6690"
AMBER_DEEP = "#96691F"
GREEN_DEEP = "#466336"
RED_DEEP   = "#8C4439"
RAIN_DEEP  = "#1F4463"   # 比 SKY_DEEP 更深的藍，天氣卡雨天 header 用，與晴天區分

# ── 語意別名（給 call site 用語意名稱而非硬記色票）──────────────
TEXT_MAIN   = INK
TEXT_MUTED  = INK2
BORDER      = LINE
BG_BODY     = PAPER
BG_CARD     = BG
ACCENT      = WOOD        # 主 header / 主按鈕
ACCENT_SOFT = SKY_SOFT
SUCCESS     = GREEN
WARNING     = AMBER
DANGER      = RED
WHITE       = "#FFFFFF"

# ── 淡色卡片底（狀態卡 / 分類標籤底色，各主色的極淺色階）────────
TINT_WOOD    = "#F5EFE6"
TINT_SKY     = "#EAF1F8"
TINT_GREEN   = "#EEF3EA"
TINT_AMBER   = "#F6EFE2"
TINT_NEUTRAL = "#F1F0EE"


def text_bubble(text: str, title: str | None = None) -> dict:
    """把純文字包成單一 Flex bubble（狀態訊息 / 錯誤訊息 / 對話教練回覆共用）。
    取代 line_notifier 舊有的 {"type": "text"} 訊息，讓所有回覆一律走 Flex 同色系。
    """
    body_contents = []
    if title:
        body_contents.append({
            "type": "text", "text": title, "size": "xs",
            "color": ACCENT, "weight": "bold",
        })
    body_contents.append({
        "type": "text", "text": text or " ", "size": "sm",
        "color": TEXT_MAIN, "wrap": True,
        "margin": "xs" if title else "none",
    })

    bubble = {
        "type": "bubble", "size": "mega",
        "body": {
            "type": "box", "layout": "vertical",
            "backgroundColor": BG_CARD,
            "paddingAll": "16px", "spacing": "sm",
            "contents": body_contents,
        },
    }
    alt = (text or title or "訊息").strip().replace("\n", " ")[:100] or "訊息"
    return {"type": "flex", "altText": alt, "contents": bubble}
