# training-line 開發指南（給 AI 協作助理與開發者）

跑步訓練 LINE 服務。Garmin 跑完 → intervals.icu → 自動推播 LINE Flex 訓練卡＋AI 分析。
安裝部署流程見 [README.md](./README.md)；本檔是改 code 前必讀的架構與地雷。

## 給 AI 助理的第一句話

使用者可能是非工程背景。回報時講白話、先講結論；改 code 前先讀本檔「地雷區」。

---

## 部署架構

```
Vercel serverless（webhook 主機）
  入口：api/index.py（WSGI 包 webhook_server.app）+ vercel.json
  部署：push main 自動部署
  └── webhook_server.py   Flask 主伺服器
        ├── POST /webhook        LINE Bot 訊息入口
        ├── GET  /poll           觸發 poller（cron-job.org 每 5 分鐘呼叫）
        ├── GET  /daily-remind   手動觸發每日提醒
        ├── GET  /weekly-report  手動觸發週報
        ├── GET  /schedule.ics   課表日曆訂閱（?token= 比對 ICS_TOKEN，不符 404）
        └── GET  /health         健康檢查

排程觸發
  ├── cron-job.org（外部）每 5 分鐘 → GET /poll
  ├── .github/workflows/daily_reminder.yml  每天 06:00（TZ=Asia/Taipei）
  └── .github/workflows/weekly_report.yml   週日 21:00

Firebase Firestore
  ├── training_logs     每次訓練紀錄（含 deep_analysis 深度分析欄位）
  ├── schedules         每週教練課表（含 AI 解析）
  ├── races             賽事目標（含備賽清單）
  ├── weekly_reports    週報快照
  ├── daily_ai_advice   每日 AI 建議
  ├── garmin_wellness   每日壓力/Body Battery/睡眠呼吸/全天心率（doc id=YYYY-MM-DD）
  ├── icu_activities    intervals.icu 活動完整原始 dict（資料主權正本）
  ├── activity_streams  逐點 streams（gzip，>900KB 切塊）
  ├── icu_wellness      intervals.icu 每日 wellness 原始 dict
  └── _meta             推播狀態、教練邏輯學習輸出、garth token
```

## 地雷區（改 code 前必讀）

1. **serverless 禁用背景執行緒**：Vercel 回應後即凍結。重活必須在同一請求內同步做完（pattern：先 reply 回執 → 同步做 → push 結果）。
2. **核心模組必須平鋪在根目錄**：`vercel.json` 用 `includeFiles: "*.py"` 打包，搬進子資料夾線上直接壞。一次性腳本才放 `scripts/`。
3. **LINE reply vs push**：webhook 觸發的回應一律用 reply（免費）；push 有額度限制（200 則/月免費）。
4. **replyToken 30 秒過期**：長工作先 reply 再 push。
5. **Firestore 不接受巢狀陣列**：用 map 陣列（如 `{"m":分鐘,"hr":值}`），不可 `[[m,hr],...]`。
6. **Carousel 內所有 bubble 不可混用不同 size**（LINE 限制）。
7. **簡體字硬防線**：所有 LINE 出口經 `zh_tw.convert_payload`（OpenCC s2twp），不要繞過 `line_notifier.py` 直接打 LINE API。
8. **Flex 設計 SoT 是 `flex_tokens.py`**：改色只改這裡，全卡片跟著變。規則見 `.claude/rules/flex-design.md`。純文字一律經 `flex_tokens.text_bubble()` 包成 Flex。
9. **寫入一律走 intervals.icu、Garmin 只讀不寫**（課表上錶 = POST intervals /events，自動同步 Garmin）。

## 檔案結構

| 檔案 | 用途 |
|------|------|
| `webhook_server.py` | Flask 主伺服器：所有 LINE 事件處理 |
| `poller.py` | 輪詢 intervals.icu，偵測新活動推播 |
| `coach_agent.py` | 對話教練（Claude tool-use）：課表/路線/天氣/跑力七工具 |
| `ai_analyzer.py` | AI 分析（訓練/每日/課表用 Haiku；深度分析用 Sonnet）|
| `flex_builder.py` | 訓練 Flex 卡（第一層＋詳細數據＋深度分析第二層）|
| `flex_tokens.py` | Flex 設計系統 SoT（色票/字級/元件）|
| `schedule_parser.py` | 解析教練課表文字（`ATHLETE_NAME` 環境變數）|
| `schedule_match.py` / `schedule_history.py` | 課表勾稽 / 歷史同類課表比較（純函式）|
| `intervals_client.py` | intervals.icu REST API |
| `firebase_client.py` | Firestore 讀寫 |
| `line_notifier.py` | LINE Messaging API（所有出口）|
| `weather_client.py` | Open-Meteo 天氣（含 WBGT 熱壓力）|
| `daily_reminder.py` / `weekly_report.py` | 每日提醒 / 週報（GitHub Actions 跑）|
| `race_flex.py` / `weekly_activity_flex.py` / `coach_flex.py` | 賽事 / 本週活動 / 教練卡 Flex |
| `vdot.py` | Daniels VDOT 跑力與訓練配速（純函式）|
| `route_log.py` + `routes.json` | 路線庫（改成你自己的路線）|
| `ics_builder.py` | 課表 → iCalendar 純函式 |
| `data_vault.py` | 原始數據全量落地 Firestore（`--backfill` 回填）|
| `garmin_wellness_sync.py` / `garmin_dynamics.py` | Garmin 直連（選配，需 garth token）|
| `garth_refresh.py` | 本機專用：garth token 定期續期（不部署）|
| `illness_watch.py` | 生病前兆偵測（RHR/HRV/睡眠呼吸 z-score）|
| `coach_logic_learner.py` | 教練課表邏輯持續學習 |
| `zh_tw.py` | 簡轉繁硬防線 |
| `scripts/` | 一次性腳本（backfill、Rich Menu 部署、課表匯入）|

## 環境變數

必填：`INTERVALS_API_KEY` `INTERVALS_ATHLETE_ID` `LINE_CHANNEL_ACCESS_TOKEN` `LINE_CHANNEL_SECRET` `LINE_USER_ID` `FIREBASE_PROJECT_ID` `FIREBASE_CREDENTIALS_JSON`（或本機 `FIREBASE_CREDENTIALS_PATH`）
建議：`ANTHROPIC_API_KEY`（AI 分析與對話教練）
個人化：`ATHLETE_NAME`（課表中你的名字）`D4_LAT`/`D4_LON`（團練地點座標）`ICS_TOKEN`（日曆訂閱）
選配：`GARTH_TOKEN`（Garmin 直連）`WELLNESS_COACH_API`/`WELLNESS_COACH_TOKEN`（外部身體數據儀表板，沒有就不啟用）

## 測試

```bash
python3 -m pytest tests/ -q
```

改核心邏輯（parser、勾稽、vdot、flex 純函式）必須先跑測試綠再 commit。
