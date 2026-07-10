# 🏃 Training LINE Bot（Template）

跑步訓練 LINE 服務。Garmin 跑完後自動從 intervals.icu 拉取數據，推播 LINE Flex 訓練卡＋AI 教練分析；並提供對話教練、課表管理、跑前評估、生病前兆偵測、賽事目標追蹤。

一句話：**把「教練課表 × 訓練數據 × 天氣 × 身體狀態」全部收進 LINE 一個入口。**

這是 template repo：點右上角 **Use this template** 建立你自己的副本，填入你自己的金鑰即可運作。所有服務都有免費方案，唯一按用量計費的是 AI 分析（每月不到 $1 美元）。

---

## 🤖 最快的上手方式：交給你的 AI 助理

這個 repo 附有 [`AGENTS.md`](./AGENTS.md)（Claude Code、Codex、Cursor 等 AI 工具都會自動讀取）。建好你的副本之後，開你慣用的 AI coding 工具，跟它說：

> 讀 README.md 和 AGENTS.md，一步一步帶我完成部署。

它會帶你申請帳號、填金鑰、部署上線。遇到問題直接把錯誤訊息丟給它。

---

## 功能總覽

### 自動推播（不需手動操作）

| 時機 | 內容 |
|------|------|
| 跑完後約 5–15 分鐘 | 訓練 Flex 卡（配速/心率/步頻/課表勾稽）＋ AI 分析；可再點「深度分析」看第二層卡（歷史同類課表比較、訓練階段、身體訊號）|
| 每天 06:00 | 今日課表提醒（含天氣）＋ AI 執行建議 |
| 每週日 21:00 | 週訓練報告（跑量 / CTL/ATL/TSB / 賽事倒數 / AI 週評）|
| 身體異常時 | 生病前兆偵測（RHR 升＋HRV 降＋睡眠呼吸升 → 紅/黃燈才推播）|

### 對話教練（傳任何文字）

Claude tool-use 對話教練：問「明天怎麼跑」「這週課表怎麼調」「換個角度分析這週課表」，
會自動查課表、天氣（含熱壓力）、身體紅綠燈、路線庫，回結構化短卡。
明確說「排進錶」才會把課表寫入 intervals.icu 並自動同步 Garmin。

### 指令

| 指令 | 功能 |
|------|------|
| `今天` / `課表` | 今日課表 / 本週課表 Carousel(含天氣)|
| `數據` | 本週活動 Carousel |
| `跑前` | 跑前評估卡；可再傳 LINE 位置訊息做就地評估 |
| `賽事` / `登錄賽事` | 賽事清單（備賽清單點擊勾稽）/ 表單式登錄 |
| `週報` | 立即推播本週週報 |
| 轉貼教練課表 | 自動解析存入系統＋整週 AI 解析 |

另有 `/schedule.ics` 課表日曆訂閱（iPhone 行事曆可訂）、`scripts/_setup_richmenu.py` 部署選單。

---

## 技術架構

```
Garmin ──自動同步──▶ intervals.icu
                        │
   cron-job.org 每 5 分鐘 ─▶ GET /poll
                        ▼
        Vercel serverless（api/index.py → webhook_server.py Flask）
          ├── poller.py         偵測新活動 → AI 分析 → LINE 推播
          ├── POST /webhook     LINE Bot 訊息入口（指令、對話教練、課表解析）
          └── GET  /schedule.ics 課表日曆訂閱

GitHub Actions（排程）
  ├── daily_reminder.yml  每天 06:00 今日課表提醒
  └── weekly_report.yml   週日 21:00 週報

Firebase Firestore（資料庫）
```

### Garmin 資料的兩條路

| 路徑 | 內容 | 門檻 |
|------|------|------|
| **主路徑：intervals.icu**（必要）| 活動數據、配速、心率、負荷 | 在 intervals.icu 網站連結 Garmin 即可，零額外設定 |
| 進階：Garmin 直連（選配）| 每日壓力 / Body Battery / 睡眠呼吸 / 跑姿 dynamics | 需 garth token（`garth_refresh.py` 本機定時續期），沒有它系統照常運作 |

> 沒有 Garmin 也可以：intervals.icu 支援 Strava / Wahoo / Coros / Polar 等來源。

### 使用的服務

| 服務 | 用途 | 費用 |
|------|------|------|
| [intervals.icu](https://intervals.icu) | 訓練數據來源 | 免費 |
| [LINE Messaging API](https://developers.line.biz/) | 推播與 Bot | 免費（200 則/月）|
| [Firebase Firestore](https://firebase.google.com/) | 資料庫 | 免費方案 |
| [Vercel](https://vercel.com) | Webhook 伺服器（serverless）| 免費方案 |
| [cron-job.org](https://cron-job.org) | 每 5 分鐘觸發 /poll | 免費 |
| [Open-Meteo](https://open-meteo.com/) | 天氣資料 | 免費 |
| [Anthropic API](https://console.anthropic.com/) | AI 分析與對話教練 | 按用量（每次分析約 $0.001 內）|

---

## 安裝教學

### 事前準備：申請你自己的帳號與金鑰

1. **intervals.icu**：註冊並連結你的 Garmin / Strava / Wahoo。Settings → API 取得 `API Key`；`Athlete ID` 在個人頁網址（`i` 開頭那串）
2. **LINE Messaging API**：在 [LINE Official Account Manager](https://manager.line.biz/) 建立你自己的官方帳號，啟用 Messaging API，取得 Channel Secret 與 Channel Access Token
3. **Firebase**：建立新專案、啟用 Firestore（Native mode）、產生服務帳號私鑰
4. **Anthropic API**（建議）：AI 分析與對話教練用
5. **Vercel** 與 **cron-job.org**：部署與排程用

### 步驟一：建立你的副本

點此 repo 右上角 **Use this template → Create a new repository**（建議 Private）。

```bash
git clone https://github.com/<你的帳號>/<你的repo>.git
cd <你的repo>
pip install -r requirements.txt
cp .env.example .env   # 填入你自己的金鑰
```

### 步驟二：部署 Vercel

1. [Vercel](https://vercel.com) → New Project → 選你的 repo（`vercel.json` 已設定好，零調整）
2. Environment Variables 填入 `.env` 同組變數（`FIREBASE_CREDENTIALS_JSON` 填整份 JSON 字串）
3. 部署後取得網址，回 LINE Developers → Webhook URL 填 `https://你的domain/webhook`
4. [cron-job.org](https://cron-job.org) 建一個每 5 分鐘 GET `https://你的domain/poll` 的 job

之後每次 push main，Vercel 自動重新部署。

### 步驟三：GitHub Actions（每日提醒與週報）

Repo → Settings → Secrets and variables → Actions 新增：

```
INTERVALS_API_KEY / INTERVALS_ATHLETE_ID
LINE_CHANNEL_ACCESS_TOKEN / LINE_CHANNEL_SECRET / LINE_USER_ID
FIREBASE_PROJECT_ID / FIREBASE_CREDENTIALS_JSON
ANTHROPIC_API_KEY
```

> 時區注意：Actions runner 是 UTC，workflow 已設 `TZ: Asia/Taipei`。非台灣使用者請改 workflow 的 `TZ` 與 cron 時間。

### 步驟四：個人化

| 設定 | 位置 | 說明 |
|------|------|------|
| `ATHLETE_NAME` | 環境變數 | 你在教練課表中的名字（課表解析用）|
| `D4_LAT` / `D4_LON` | 環境變數 | 團練日訓練地點座標（天氣用）|
| `routes.json` | 檔案 | 換成你自己的常跑路線（對話教練路線規劃用）|
| Rich Menu | `scripts/_setup_richmenu.py` | 圖片路徑改成你的再執行 |

---

## 課表轉貼格式

將教練的 LINE 課表文字**直接轉貼**給 Bot，系統會自動解析：

```
2026 04/13-04/19

D1 （全員）40-60min FR'
D2 小明 10-12k P'530-540/km
D3 休息
...
```

課表格式不同？改 `schedule_parser.py`（有完整測試 `tests/test_schedule_parser.py` 保護），或叫你的 AI 助理照你教練的格式調整。

---

## 開發

```bash
python3 -m pytest tests/ -q     # 跑測試
```

架構、資料模型、改 code 的地雷區都在 [`AGENTS.md`](./AGENTS.md)。

## License

MIT
