"""
建立 LINE Rich Menu（固定選單）
執行一次即可，之後不需要再跑
"""
# 腳本已移入 scripts/，把專案根目錄加回 import path 才能匯入根目錄模組
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import os, json, requests
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

IMAGE_PATH = "./richmenu.jpg"  # 換成你的選單圖（2500 x 1686）

# ── 1. 建立 Rich Menu ──────────────────────────────────────
# 圖片尺寸：2500 x 1686，四等分
W, H = 2500, 1686
HW, HH = W // 2, H // 2  # 1250, 843

rich_menu = {
    "size": {"width": W, "height": H},
    "selected": True,
    "name": "training-menu",
    "chatBarText": "訓練選單",
    "areas": [
        {
            "bounds": {"x": 0,  "y": 0,  "width": HW, "height": HH},
            "action": {"type": "message", "text": "今天"}
        },
        {
            "bounds": {"x": HW, "y": 0,  "width": HW, "height": HH},
            "action": {"type": "message", "text": "課表"}
        },
        {
            "bounds": {"x": 0,  "y": HH, "width": HW, "height": HH},
            "action": {"type": "message", "text": "賽事"}
        },
        {
            "bounds": {"x": HW, "y": HH, "width": HW, "height": HH},
            "action": {"type": "message", "text": "登錄賽事"}
        },
    ]
}

r = requests.post(
    "https://api.line.me/v2/bot/richmenu",
    headers={**HEADERS, "Content-Type": "application/json"},
    data=json.dumps(rich_menu)
)
print(f"建立 Rich Menu：{r.status_code} {r.text}")
rich_menu_id = r.json().get("richMenuId")
if not rich_menu_id:
    raise SystemExit("建立失敗，停止")

# ── 2. 上傳圖片 ────────────────────────────────────────────
with open(IMAGE_PATH, "rb") as f:
    r2 = requests.post(
        f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
        headers={**HEADERS, "Content-Type": "image/jpeg"},
        data=f.read()
    )
print(f"上傳圖片：{r2.status_code} {r2.text}")

# ── 3. 設為預設選單 ────────────────────────────────────────
r3 = requests.post(
    f"https://api.line.me/v2/bot/user/all/richmenu/{rich_menu_id}",
    headers=HEADERS
)
print(f"設為預設：{r3.status_code} {r3.text}")
print(f"\n完成！Rich Menu ID: {rich_menu_id}")
