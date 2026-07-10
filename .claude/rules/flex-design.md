---
description: LINE Flex Bubble 設計規則與配色系統
paths:
  - flex_tokens.py
  - flex_builder.py
  - coach_flex.py
  - race_flex.py
  - weekly_report.py
  - weekly_activity_flex.py
  - webhook_server.py
  - line_notifier.py
---

# Flex Bubble 設計規則

**設計系統 SoT：`flex_tokens.py`**（2026-07-09 全面改版），與 wellness-dashboard
`templates/v2.html` 的 mindflows 色票同源。改色只改 `flex_tokens.py` 這一份，
全部卡片跟著變——不要在個別檔案手刻 hex（教訓見道籍 LINE-FLEX-SYSTEM 事件）。

核心色票：`WOOD`（深木棕，主 header/強調）、`SKY`（晴天藍，次強調，直接當底色需用
`SKY_DEEP` 加深版）、`AMBER`（琥珀，警示/重點數字）、`GREEN`（成功）、`RED`（危險）、
`INK`/`INK2`（主文字/靜音文字）、`PAPER`（卡片底色）、`LINE`（分隔線/邊框）。
`*_DEEP` 系列（`SKY_DEEP`/`AMBER_DEEP`/`GREEN_DEEP`）是白字承載用加深版，純色
header 底一律用加深版，不要直接用基礎色票（對比不足，過往 weather 色表已踩過這雷）。

## 全訊息 Flex 化（2026-07-09 拍板）

**`line_notifier.py` 的 `send()`/`reply()`/`send_message_with_quick_reply()`/
`send_location_quick_reply()` 內部一律呼叫 `flex_tokens.text_bubble()` 把純文字包成
Flex bubble，不再送 `{"type": "text"}`。** 這代表整支 bot 的所有既有 call site
（狀態訊息、錯誤訊息、對話教練自由文字回覆等）自動統一走 Flex + mindflows 色系，
call site 不需個別修改。新增回覆邏輯時直接呼叫 `ln.send()`/`ln.reply()` 即可，
不需自己包 Flex。

## 運動類別配色（不再用彩虹配色）

`flex_builder.SPORT_THEME` 與 `weekly_activity_flex.SPORT_CONFIG` 收斂到同一組
mindflows 色系家族分類邏輯（兩處保持一致）：

| 分類 | 色票 | 運動 |
|------|------|------|
| 主線 | `WOOD` | Run / VirtualRun |
| 水域/輪類 | `SKY_DEEP` | Ride / Swim / RopeSkipping / JumpRope |
| 自然系 | `GREEN_DEEP` | Walk / Hike |
| 暖色系 | `AMBER_DEEP` | Yoga |
| 中性 | `INK2` | WeightTraining / Workout / 未分類 |

## 訓練推播 bubble（flex_builder.py）

- Header：運動類別配色（見上表）+ 加深版白字對比，日期/星期/標籤 → 地點+天氣 → 大距離數字
- Body：時間/配速 → 步頻/步幅/爬升 → 心率區間橫條 → 負荷/消耗 → 課表勾稽 → AI 分析
- 狀態卡淡色底統一用 `TINT_*` 系列（`TINT_WOOD`/`TINT_SKY`/`TINT_GREEN`/`TINT_AMBER`/`TINT_NEUTRAL`）
- Footer：「查看詳細數據」（`detail:`）+「深度分析」（`deep:`，僅 role=main/standalone）兩顆按鈕

## 深度分析 bubble（`flex_builder.build_deep_analysis_bubble`，第二層，2026-07-10 新增）

- 由 `deep:{act_id}` postback 觸發，讀 `training_logs.{id}.deep_analysis`（poller.py 推播當下
  已用 Sonnet 生成好，postback 只讀不現算），不是 AI 卡的變體，是獨立的第二層卡
- Header：`WOOD`（同訓練推播卡），`size: giga`（不進 Carousel，可用比 mega 大的尺寸）
- Body：五段固定對應 `TINT_*`（今日表現 `TINT_NEUTRAL`／歷史比較 `TINT_SKY`／訓練階段
  `TINT_AMBER`／身體訊號 `TINT_GREEN`／建議 `TINT_WOOD`），沒資料的段落不畫（不是畫空卡），
  沿用既有色票、不新增顏色

## 今日教練卡（coach_flex.py）

- Header：`WOOD`；`hrv_color`/`form_color` 等語意 token（good/ok/warn/none）經
  `_safe_color()` 轉為 `flex_tokens` 色票，不可直接灌字串（LINE 只收合法 hex）
- 「跑前重點」「今日天氣」小標籤：`SKY_DEEP`

## 課表 Carousel（webhook_server.py `_build_schedule_flex`）

- D1–D5 各一張，D6+D7 合併週末，最後一張 AI 課表解析卡
- Header：天氣配色（`_weather_accent()`，見下表）+ 大標籤 + 天氣數據列
- Body：`AMBER` accent bar 課表卡 + 天氣 Bento Grid（含休息日天氣）
- 所有標籤改為純文字（不使用 badge pill，避免渲染成黑點）
- D4（週四）用松山區座標（lat=25.0579, lon=121.5673）
- **天氣只抓今天與未來日期**（CWA 只有預報，過去日期跳過避免 timeout）
- **Carousel 內所有 bubble 不可混用不同 size**（LINE 限制，AI 卡不設 size）
- **「課表」指令：先 reply「載入課表中⋯」當回執，同一請求內同步抓天氣＋組卡再 push 結果**（serverless 不可用背景執行緒；避免 replyToken 30 秒 timeout）

天氣配色對照（收斂到 mindflows 色系家族，不再是任意 Tailwind 藍）：
| 天氣 | 顏色 |
|------|------|
| 晴天 / 晴時多雲 | `SKY_DEEP` |
| 多雲 / 陰天 / 霧 | `INK2` |
| 毛毛雨 / 小雨 / 中大雨 | `RAIN_DEEP` |
| 雷雨 | `WOOD` |

## 課表 AI 分析（ai_analyzer.py `analyze_schedule`）

- 教練貼課表後，先 reply 課表 carousel，同一請求內同步跑 AI 分析並存入 Firebase `schedules.ai_analysis`
- 包含：本週訓練目標、執行注意事項
- 顯示位置：本週課表 Carousel 最後一張卡、每日提醒（非休息日）、「今天」指令

## 賽事 bubble（race_flex.py）

- Header：`AMBER_DEEP`，賽事名/日期/距離/地點
- Body：倒數天數 + 備賽完成度（進度條）+ 備賽清單
- 未完成項目整個 row 可點擊（postback → 打勾 → 推播更新）

## 週報 bubble（weekly_report.py）

- Header：`WOOD`，跑量大數字 `AMBER` 靠右
- Body：Bento 3 欄主數據 → 每日跑步清單（左側色條）→ CTL/ATL/TSB → AI 週評

## 本週活動 Carousel（weekly_activity_flex.py）

- Card 1：週摘要（`WOOD`）—總跑量/次數/時間/均速
- Card 2+：各運動卡片—Header 含天氣 emoji + 氣溫，Body 為 stat cells
- 跑步卡片從 Firebase training_logs 讀取 schedule_status / schedule_workout，正確顯示課表勾稽

## Rich Menu 子選單（webhook_server.py `_submenu_flex`）

- 主按鈕 `WOOD`，次按鈕 `TINT_NEUTRAL`
