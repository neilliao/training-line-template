# 從零到上線：保母級部署教學

照著做，大約 1–2 小時可以上線。不需要寫任何程式。

> **🤖 建議做法**：如果你有 AI coding 工具（Claude Code、Codex、Cursor 任一），把這份文件丟給它，說「照 docs/SETUP.md 帶我一步一步做」，卡住就把畫面或錯誤訊息貼給它。沒有 AI 工具也可以，每一步都寫了去哪裡點什麼。

## 你需要準備的

- 一支會記錄跑步的錶或 App（Garmin / Strava / Coros / Wahoo / Polar 都可以）
- LINE 帳號、Google 帳號、GitHub 帳號
- 費用：全部服務都用免費方案；只有 AI 分析按用量計費（一個月不到 1 美元，可先不開）

## 完成後你會得到

一個你自己的 LINE Bot：跑完步約 5–15 分鐘自動推播訓練分析卡、每天早上提醒今日課表、每週日晚上給週報，還能用聊天的方式問它訓練問題。所有金鑰與資料都在你自己的帳號裡，不經過任何別人的伺服器。

---

## Step 0：建立你自己的 repo

1. 到本 repo 首頁，點右上角 **Use this template → Create a new repository**
2. Repository name 隨意（例如 `my-training-line`），建議選 **Private**
3. 點 **Create repository**

之後所有操作都在你自己的這個 repo 上做。

---

## Step 1：intervals.icu（訓練數據來源）

1. 到 [intervals.icu](https://intervals.icu) 用 Google 帳號註冊
2. 首次登入會問資料來源：選你的錶（**Garmin** 就點 Garmin，跳去 Garmin 登入授權；Strava / Coros / Wahoo / Polar 同理）
3. 授權完成後，你過去的活動會自動匯入（可能要等幾分鐘）
4. 拿兩個值：
   - **Athlete ID**：看瀏覽器網址列，`https://intervals.icu/athlete/i123456/...` 裡的 `i123456`（記下來，含開頭的 i）
   - **API Key**：左下角 **Settings** → 拉到最底 **Developer Settings** → **API Key** 點「generate」→ 複製

✅ 檢查點：intervals.icu 的 Activities 頁看得到你最近的跑步。

---

## Step 2：LINE 官方帳號（你的 Bot 本體）

1. 到 [LINE Official Account Manager](https://manager.line.biz/) 用你的 LINE 帳號登入，**建立新的官方帳號**（名稱隨意，例如「跑步教練」）
2. 建好後進入該帳號 → 右上 **設定** → 左側 **Messaging API** → 點 **啟用 Messaging API**（會建立一個 Provider，名稱隨意）
3. 到 [LINE Developers Console](https://developers.line.biz/console/) → 選剛剛的 Provider → 進入你的 channel，拿三個值：
   - **Channel secret**：`Basic settings` 分頁往下捲
   - **你的 User ID**：`Basic settings` 分頁最底部 **Your user ID**（`U` 開頭一長串）
   - **Channel access token**：`Messaging API` 分頁最底部 → 點 **Issue**
4. 回到 LINE Official Account Manager → 設定 → **回應設定**：
   - 聊天：**關**
   - 自動回應訊息：**關**（不關的話 Bot 每句都會回罐頭訊息）
   - Webhook：**開**
5. 用手機掃 `Messaging API` 分頁的 QR code，把你自己的 Bot 加為好友

✅ 檢查點：三個值都存好了（channel secret / access token / 你的 user ID）。

---

## Step 3：Firebase（資料庫）

1. 到 [Firebase Console](https://console.firebase.google.com/) → **建立專案**（名稱隨意；Google Analytics 可以不開）
2. 左側 **Build → Firestore Database** → **建立資料庫** → 位置選 `asia-east1`（台灣）→ 模式選 **正式版**（production mode）即可
3. 拿憑證：左上齒輪 → **專案設定** → **服務帳戶** 分頁 → **產生新的私密金鑰** → 下載 JSON 檔（先放桌面，Step 5 會把整份內容貼進 Vercel）
4. 記下 **專案 ID**（專案設定 → 一般設定，例如 `my-training-abc12`）

✅ 檢查點：手上有一個 JSON 檔＋專案 ID。這個 JSON 等同資料庫鑰匙，**不要傳給任何人、不要放進 repo**。

---

## Step 4：Anthropic API（AI 分析，建議開）

沒有它系統照常推播，只是沒有 AI 評語和對話教練。

1. 到 [console.anthropic.com](https://console.anthropic.com/) 註冊 → **API Keys** → 建立一把，複製（`sk-ant-` 開頭）
2. Billing 儲值最低額度即可（跑步分析每次約 $0.001，一個月不到 $1）

---

## Step 5：部署 Vercel（讓 Bot 活起來）

1. 到 [vercel.com](https://vercel.com) 用 GitHub 帳號登入 → **Add New → Project** → Import 你 Step 0 建立的 repo
2. Framework Preset 顯示什麼都不用改（`vercel.json` 已設定好），先別按 Deploy，展開 **Environment Variables**，照下表填：

| 變數名稱 | 填什麼 |
|----------|--------|
| `INTERVALS_API_KEY` | Step 1 的 API Key |
| `INTERVALS_ATHLETE_ID` | Step 1 的 Athlete ID（含 `i`）|
| `LINE_CHANNEL_ACCESS_TOKEN` | Step 2 的 access token |
| `LINE_CHANNEL_SECRET` | Step 2 的 channel secret |
| `LINE_USER_ID` | Step 2 的 Your user ID（`U` 開頭）|
| `FIREBASE_PROJECT_ID` | Step 3 的專案 ID |
| `FIREBASE_CREDENTIALS_JSON` | Step 3 下載的 JSON 檔**整份內容**（用文字編輯器打開全選複製貼上）|
| `ANTHROPIC_API_KEY` | Step 4 的 key（沒開就跳過）|
| `ATHLETE_NAME` | 你在教練課表裡的名字（沒有教練課表就填你的名字）|

3. 點 **Deploy**，等一分鐘 → 完成後拿到你的網址（例如 `https://my-training-line.vercel.app`）
4. 瀏覽器開 `https://你的網址/health`，看到回應就是活的
5. 回 [LINE Developers Console](https://developers.line.biz/console/) → `Messaging API` 分頁 → **Webhook URL** 填 `https://你的網址/webhook` → 按 **Verify**（要顯示 Success）→ 打開 **Use webhook**

✅ 檢查點：用手機傳「今天」給你的 Bot，**會回你一張卡**（還沒課表所以內容是空的，正常）。

---

## Step 6：cron-job.org（每 5 分鐘檢查有沒有新跑步）

1. 到 [cron-job.org](https://cron-job.org) 註冊 → **Create cronjob**
2. URL 填 `https://你的網址/poll`
3. Execution schedule 選 **Every 5 minutes**
4. 存檔，確認狀態是 Enabled

✅ 檢查點：History 裡看得到每 5 分鐘一次的成功紀錄（200）。

---

## Step 7：GitHub Actions（每日提醒＋週報）

1. 你的 repo → **Settings → Secrets and variables → Actions → New repository secret**
2. 逐一新增（名稱要一模一樣，值同 Step 5）：

```
INTERVALS_API_KEY
INTERVALS_ATHLETE_ID
LINE_CHANNEL_ACCESS_TOKEN
LINE_CHANNEL_SECRET
LINE_USER_ID
FIREBASE_PROJECT_ID
FIREBASE_CREDENTIALS_JSON
ANTHROPIC_API_KEY
```

3. repo → **Actions** 分頁 → 如果顯示「Workflows aren't being run」就點啟用

> 排程是台北時間每天 06:00 提醒、週日 21:00 週報。不在台灣的話，改 `.github/workflows/` 兩個 yml 裡的 `cron`（注意 GitHub cron 用 UTC）。

✅ 檢查點：Actions 分頁 → 選 `daily reminder` → **Run workflow** 手動跑一次 → 手機收到今日課表提醒。

---

## Step 8：總驗收

| 測試 | 預期 |
|------|------|
| 傳「今天」 | 回今日課表卡（含天氣）|
| 貼一份課表（格式見 README）| 回整週課表 Carousel |
| 去跑一次步（或在 intervals.icu 手動加一筆活動）| 5–15 分鐘內收到訓練分析卡 |
| 傳「明天怎麼跑」 | 對話教練回結構化建議（需 ANTHROPIC_API_KEY）|

全過就上線完成 🎉

---

## Step 9：個人化（可以之後慢慢調）

- **課表**：把你教練的 LINE 課表直接轉貼給 Bot 就會解析；格式不同就叫你的 AI 助理改 `schedule_parser.py`（有測試保護）
- **路線庫**：`routes.json` 換成你自己的常跑路線（給對話教練做路線規劃用），格式照檔內範例
- **選單**：準備一張 2500×1686 的選單圖，改 `scripts/_setup_richmenu.py` 的圖片路徑後本機執行 `python3 scripts/_setup_richmenu.py`
- **Garmin 直連**（進階選配）：解鎖 Body Battery / 睡眠呼吸 / 跑姿數據，需要 garth token 與本機定時續期，見 `AGENTS.md`；不設定完全不影響主功能

---

## 疑難排解

| 症狀 | 原因與解法 |
|------|-----------|
| Webhook Verify 失敗 | 網址要以 `/webhook` 結尾；先開 `/health` 確認服務活著；Vercel 環境變數改過要 **Redeploy** 才生效 |
| 傳訊息 Bot 不回 | LINE OA Manager 回應設定：聊天關、自動回應關、Webhook 開；LINE Developers 的 Use webhook 要打開 |
| 跑完沒收到推播 | 檢查 cron-job.org 有沒有成功打 `/poll`（History 要 200）；intervals.icu 上要先看得到那筆活動；`LINE_USER_ID` 是否填對 |
| 每日提醒沒來 | Actions 分頁看 workflow 有沒有跑、有沒有紅字；Secrets 名稱打錯是最常見原因 |
| 回應顯示「AI 分析暫時無法使用」 | `ANTHROPIC_API_KEY` 沒填或額度用完；不影響其他功能 |
| 推播突然變少 | LINE 免費方案每月 200 則 push（reply 不算）；正常單人使用夠用，多人共用一個 Bot 才會爆 |
| 改了環境變數沒生效 | Vercel 改完要 Redeploy；GitHub Secrets 改完下次排程才生效 |

還是卡住？把錯誤畫面丟給你的 AI 助理，或開 [Issue](../../issues)。
