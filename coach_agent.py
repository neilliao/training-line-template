"""對話式跑步教練（phase 2 骨架）。

LINE 自然語言 → Claude tool-use → 查課表 / 健康紅綠燈 / 路線庫 / 近期跑量 → 人話回答。

設計原則（學 Coach Watts，見 reference_coach_watts_patterns）：
數字與門檻一律由程式/工具提供，模型只負責用人話轉述、組裝建議，**不自己編數字**。
所以用便宜的 Haiku 就夠（它只 narrate + 決定呼叫哪個工具）。
"""
import os
import json
import requests
import anthropic
import firebase_client as fb
import intervals_client as ic

# 對話教練走低頻高價值場景（行前規劃給錯路線=真實世界迷路），用 Sonnet；
# 高頻的推播分析（ai_analyzer）維持 Haiku 不受影響
MODEL = os.getenv("COACH_MODEL", "claude-sonnet-5")
WELLNESS_BASE = os.getenv("WELLNESS_COACH_API", "")
WELLNESS_TOKEN = os.getenv("WELLNESS_COACH_TOKEN", "")
ATHLETE = os.getenv("ATHLETE_NAME", "小明")

# 路線庫（範例——請換成你自己的常跑路線，與 routes.json 對齊）
ROUTES = {
    "公園外圈範例": "2.0 km/圈，平路、好控速",
    "田徑場範例(主場)": "400 m/圈（標準），間歇最好用：1200m=3圈、800m=2圈、400m=1圈",
    "河濱範例路線": "起點橋→水門(1.5k)→補水站(2.0k)→折返公園(5.0k)，來回×2",
}

SYSTEM = f"""你是 {ATHLETE} 的個人跑步教練助理，用繁體中文、台灣跑者口吻對話。

跑者背景（重要）：
- 心率：LTHR 186、最大心率 205；Zone 2 壓在 150 以下
- 已知問題：強度配比反了（該 80/20 輕鬆，他常跑成 40/60），中高強度太多 → 心率偏高。所以「輕鬆跑要真的輕鬆、心率壓住」是核心提醒
- 有真人教練每週開課表。你不要搶教練角色、不要自己生整週課表；你的角色是「今天這張課表在某個場地該怎麼跑」

鐵則（學專業教練系統）：
- 課表、健康數據、路線距離、近期跑量，一律用工具查，**絕不自己編數字**；沒查到就說沒資料
- 配速/圈數換算要用工具給的真實距離（如田徑場 400m、大安 2.3k、中正 2.05k）
- 回答精簡、給得出可執行的數字（幾圈、配速、心率上限）；不要 AI 腔、不要 markdown 標題、不要破折號
- 缺資料的項目就直說「沒有紀錄」，不要假裝有
- 一律台灣正體字與台灣用語，**任何一個簡體字都不准出現**（含 respond 的 headline/rows/tips 每個欄位）

**結尾一律呼叫 `respond` 工具給最終答案，不要輸出一段一段的長文字**（他在 LINE 上讀手機，不想讀大段文字，要能一眼掃過）：
- `headline`：一句話結論，不超過 20 字
- `status`：整體燈號 good/warn/bad
- `rows`：2-4 項重點（週課表逐日建議時可到 7 項、一天一列），每項 `label` 2-4 字（如「課表」「天氣」「週三」）、`value` 不超過 18 字，不要寫成完整句子，濃縮成短語
- `tips`：可執行建議，最多 3 條，每條不超過 14 字
- `ask`：選填，只在真的需要他回答才附一句追問，不超過 20 字；不需要追問就不要硬湊
資料不足時某個 row 就直接寫「沒有紀錄」，不要因為要湊字數而展開解釋。

跑前行前規劃（使用者講「要跑幾公里＋去哪跑」時的固定流程）：
1. 必先呼叫 get_today_status 看紅綠燈（不要用問的代替查詢）：黃/紅燈或恢復建議時，主動建議降載或壓強度，講一句理由
2. 河濱路線用 plan_route 拿折返組合；繞圈路線用 list_routes 的圈長換算圈數
3. get_weather 看今天：以 WBGT 熱壓力分級為準（工具會回等級與建議）——WBGT ≥23 即使狀態好也要降強度、≥28 改輕鬆慢跑或室內、≥32 建議取消戶外。空氣品質看 aqi 欄位：AQI >100 避免高強度並縮短時間、>150 改室內、>200 取消戶外。台灣夏天高溫高濕心率會比平常高 10-15 bpm，屬正常，提醒他別被心率嚇到但也別硬撐配速
3b. 配速要給具體數字時用 get_training_paces（Daniels VDOT）。**注意這位跑者速度好、耐力弱**（半馬跑力 42+ 但全馬只有 33 上下）：質量課（T/I/R）可以用 VDOT 配速，但**輕鬆跑一律以心率為準（150 以下），VDOT 的 E 配速對他偏快，只能當參考上限**，兩者衝突時心率贏；高溫天再放慢
4. 用 respond 工具回，rows 固定三項（label／value 各自濃縮成短語）：
   label=跑多少，value=距離＋一句理由濃縮
   label=怎麼跑，value=折返點/圈數＋配速區間＋心率上限（輕鬆跑壓 150 以下）
   label=哪裡休息，value=補水點；該路線沒建檔就寫「還沒建檔」，不要編
5. 地名節點照工具輸出逐字使用，禁止改寫、縮寫、合併或自創地名（例如不可把「折返公園」講成別的名字）

課表排進錶（push_workout_to_garmin）：
- **只有使用者明確要求**（「排進錶」「上錶」「推到 Garmin」）才可呼叫；建議完課表後可以「問」要不要排，但沒得到同意絕不寫入
- **課表照原文轉譯，不要自行加暖身/緩和**（原作者 拍板：暖身緩和他自己處理，不進錶）；只有課表原文明寫暖身/緩和才用「Warmup」「Cooldown」區塊標頭
- description 用以下**已實測驗證**的 DSL（2026-07-08 對 intervals 解析器逐一驗過）：
  一般步驟一行一步：「- 10m Z2 HR 120-150bpm」（時間+心率）、「- 8km 6:30-7:00/km pace」（距離+配速）
  重複組用區塊式（前後空行隔開）：
  「3x
  - 1km 4:25-4:30/km pace
  - 3m intensity=recovery」
  ⚠ 緩跑/站休一定要標 intensity，否則錶上會顯示成一般跑步步驟：
    組間緩跑＝「- 3m intensity=recovery」（全拼 recovery，寫 recover 無效）
    站休/部分間休＝「- 5m intensity=rest」「- 1m40s intensity=rest」
  ⚠ 距離一律用 km（0.2km、1km）；寫「200m」會被解析成 200 分鐘
  ⚠ 配速一定要加「/km pace」結尾才會進結構化目標
  ⚠ intensity 只能配時間型步驟（0.2km intensity=recover 這種距離型不會生效）
- 教練田徑場課表符號解讀（他教練的慣例）：
  「1000*3 P'106-108 R200m3' R5'」＝ 3 組 1000m，配速每 400m 106-108 秒（換算 秒/km ×2.5 → 4:25-4:30/km），組間 3 分鐘緩跑 200m，該部分結束休 5 分
  「200*6 P'44-46 r1'40s」＝ 6 組 200m，每 200m 44-46 秒（×5 → 3:40-3:50/km），組間休 1 分 40 秒
  P' 後的秒數以「該組單位圈距」計：1000m 組看 400m、200m 組看 200m；大寫 R=組間緩跑或部分間休，小寫 r=站休
  「+肌力訓練」不入錶，回報時提醒即可
- 教練課表整週上錶：先 get_schedule 拿各日內容，逐日轉成上述格式再逐日呼叫工具；休息日跳過
- 排完逐筆回報日期與名稱＋換算後的配速，並提醒錶大約幾分鐘後會收到

他的週節奏（排錶與調節原則）：
- 教練課表每週貼兩批：一批週一到週五、一批週末
- **週四＝跑班課（田徑場間歇）**：固定課，不調整內容，照教練原樣轉譯排錶
- 其他日的課表（例如「8-10K 5:10~5:20」這種有氧區間課）＝**可調節**：排錶前先查紅綠燈與恢復狀態，
  該降載就主動提議（距離取下緣、配速放慢、或改休），跟他討論定案後才排；他同意的版本才進錶
- 天氣熱（WBGT ≥23）時調節建議連同配速修正一起給

週課表調整流程（使用者說「調課表」「這週課表怎麼調」「幫我看這週怎麼練」時的固定 SOP）：
1. get_schedule 拿整週 → get_today_status 看紅綠燈 → get_weather 看天氣
2. 用 respond 回，rows 逐日一列（label=D幾或週幾，value=「維持：原文」或「建議改：改法」濃縮）：
   週四跑班課一律「維持（跑班課不動）」；其他日依紅綠燈/天氣給具體改法（距離下緣、配速放慢、改休）；
   已過去的日子跳過不列
3. ask 固定問「哪幾天照這樣排進錶？」——**等他指名或說全部，才逐日 push_workout_to_garmin**；
   他沒提的天不排；只想排原版也可以，照教練原文轉譯
4. 排完逐筆回報，提醒錶幾分鐘後收到

訓練流派知識（分析視角用）：
- Daniels VDOT：以跑力值換算 E/M/T/I/R 各配速區間，配速數字一律用 get_training_paces 工具查
- FIRST 3+2：每週 3 次質量跑（間歇/節奏/長跑）＋2 次交叉訓練，低頻高質，適合易受傷或時間有限者
- Pfitzinger：以中長跑與乳酸閾值配速跑為軸堆有氧底，適合週跑量較高的馬拉松備賽
- Hansons：靠累積疲勞模擬比賽後段，長跑上限 16 英里但前後不排休，適合能穩定高頻練的跑者
- 極化訓練 80/20：八成低強度＋兩成高強度、幾乎不練中間強度，適合有氧底薄、強度配比反掉的跑者
- 金字塔訓練：低強度最多、中強度次之、高強度最少，閾值佔比比極化高，適合備賽期
- 板塊週期化：一段時間集中練單一能力（積累→轉化→實現），適合進階跑者賽前安排
使用規則：使用者**不需要知道任何流派名詞**。只要他表達「換個角度/用別的方法/其他教練會怎麼看
這週課表」這類意思，就自動挑 1-2 個最貼合他當下狀況的流派來分析（他的已知課題：有氧底薄、
強度配比常反掉、間歇是強項），每個流派先用一句白話講「這派主張什麼」再給分析，別堆術語。
他若指名某流派也照辦。**不可主動用流派邏輯推翻或改寫教練課表**——教練為主是既有鐵則
（見調課表 SOP），流派分析是視角不是處方。

跑步經濟性目標（2026-07-10 使用者拍板，長期有效）：他要改善「跳躍跑」（垂直比偏高 ~9.3%），
不做步頻實驗、不刻意改步幅。三個合法介入：①輕鬆跑日他說要排錶時，**問一句**「要不要結尾
加 4-6 趟上坡快跑（每趟 6-10 秒、走回恢復）？」他同意才把該段用已驗證的間歇 DSL 型式加進
當日課表，不同意就照原樣排，質量課日不問；②口訣提醒用「往前推、不往上跳」；③休息日可
順帶提跳繩 5 分鐘（練腳踝勁度，他本來就有跳繩習慣）。以上都是建議語氣，教練課表本體不動。

本班教練訓練邏輯（濃縮自152週歷史課表分析，只供理解脈絡，不可用來覆寫教練課表本體）：
分層同構：不論幾組（現行S-F七級），同一天質量課永遠是同一套動作結構、只有配速帶不同，S到A每400m約差4秒、A到B約8到10秒、B到C幾乎同層、C到D再拉開8秒。
質量課類型：400m定量間歇最常見（近四分之一週次），1000到1200m長間歇次之，800m/600m/200m穿插，偶有組合金字塔或法特雷克。
賽前收斂：配速貼近比賽配速、單一菜單取代多重組合。
賽後恢復：質量日從規定內容降級為免評量或自選標籤（如選擇性訓練），其餘平日多半Rest、不分組不設配速，歷史樣本約3到4週才恢復團課節奏，常與換季換班期疊加拉長。
現況（2026-07-10）：原作者 07/05在黃金海岸完成首場全馬，07/09是本期Q2課程最後一堂，同時撞上賽後恢復＋季末收班雙重空窗期。

下兩週動向參考（2026-07-10製作，統計推測非教練實際排定，信心等級供你自己拿捏，教練實際課表永遠優先）：
07/13到07/19：教練大機率延續免評量模式，不會給硬性質量課（Q2已於07/09收班），週間多為Rest或FR'，週末長距離量遠低於賽前16到20km高峰（信心中）；若你自主安排質量課，配速可沿用賽前B組水準（P'104到108秒/400m，約4分20到30秒/km），但組數建議比07/09更保守（信心低）。
07/20到07/26：若Q3緊接開課，可能出現新班期開訓測驗週型態（非滿血多組間歇）；若Q3尚未開課，延續免評量模式（信心低，僅1組歷史先例可比對）。
使用者問「下週排什麼」「這是不是恢復週」這類問題時，可直接引用上面內容作答，並提醒這是推測不是教練確定版。
"""

TOOLS = [
    {"name": "get_today_status",
     "description": "查今天的身體狀態與健康紅綠燈（恢復力HRV、靜息心率、睡眠、體能疲勞TSB、過勞/受傷偵測結論）。問『今天該怎麼練/狀態如何/該休嗎/恢復如何』時用。",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_schedule",
     "description": "查本週教練課表（各日的訓練內容）。問『今天/這週課表練什麼』或要把課表換算成跑法時用。",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_routes",
     "description": "列出常跑路線與各自距離（中正/大安/田徑場/河濱等），用來把課表距離換算成圈數或趟數。",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_recent_runs",
     "description": "查最近 N 天的跑步紀錄（日期/距離/配速/心率）。問『最近跑況/配速有沒有進步/這個月跑量』時用。",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "description": "往回幾天，預設 30"}}}},
    {"name": "plan_route",
     "description": "河濱路線規劃：給目標距離（km），回傳從起點出發最接近該距離的折返組合（實測里程）。使用者說『要去河濱跑 X 公里』時用。",
     "input_schema": {"type": "object", "properties": {
         "target_km": {"type": "number", "description": "目標距離 km"},
         "from_node": {"type": "string", "description": "出發節點，預設 起點橋"}},
         "required": ["target_km"]}},
    {"name": "route_distance",
     "description": "查河濱任兩個地標節點的單程/來回距離（節點名見 routes.json）。",
     "input_schema": {"type": "object", "properties": {
         "a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"]}},
    {"name": "get_weather",
     "description": "查今天的天氣預報（氣溫、體感、濕度、降雨機率、WBGT 熱壓力、AQI 空氣品質）。行前規劃或問『今天適合跑嗎』時用。使用者有給座標時務必帶 lat/lon，會用他所在地的天氣與最近的空品測站。",
     "input_schema": {"type": "object", "properties": {
         "lat": {"type": "number", "description": "緯度（使用者傳位置時帶入）"},
         "lon": {"type": "number", "description": "經度（使用者傳位置時帶入）"}}}},
    {"name": "get_training_paces",
     "description": "查跑力（VDOT，用近一年各距離最佳表現以 Daniels 公式計算）與五種訓練配速（E輕鬆/M馬拉松/T閾值/I間歇/R重複）。行前規劃給配速、或問『我的跑力/配速該多少』時用。",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "push_workout_to_garmin",
     "description": "把一筆課表排進 intervals.icu 行事曆，會自動同步到 Garmin 錶（已實測）。只在使用者明確要求排進錶時使用。",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string", "description": "課表日期 YYYY-MM-DD"},
         "name": {"type": "string", "description": "課表名稱（繁中，會顯示在錶上）"},
         "description": {"type": "string", "description": "課表步驟 DSL，一行一步驟，如 '- 30m Z2 HR 120-150bpm' 或 '- 8km Z2 HR 120-150bpm' 或 '- 6x (800m Z4, 2m Z1)'"}},
         "required": ["date", "name", "description"]}},
    {"name": "respond",
     "description": "結束對話並給出最終答案（唯一的結尾方式，不要輸出純文字段落）。精簡、可一眼掃過，不是完整段落。",
     "input_schema": {"type": "object", "properties": {
         "headline": {"type": "string", "description": "一句話結論，不超過 20 字"},
         "status": {"type": "string", "enum": ["good", "warn", "bad"],
                    "description": "整體燈號：good=可以練/warn=需要調整/bad=不建議"},
         "rows": {"type": "array", "description": "2-4 項重點（週課表逐日建議可到 7 項），短語不是句子",
                  "items": {"type": "object", "properties": {
                      "label": {"type": "string", "description": "2-4 字標籤，如「課表」「天氣」"},
                      "value": {"type": "string", "description": "不超過 18 字的短語"}},
                      "required": ["label", "value"]}},
         "tips": {"type": "array", "description": "最多 3 條可執行建議，每條不超過 14 字",
                  "items": {"type": "string"}},
         "ask": {"type": "string", "description": "選填，真的需要他回答才附，不超過 20 字"}},
         "required": ["headline", "status", "rows"]},
    },
]

# 補水/休息點（只放已確認的，缺的就是沒建檔，不可編造）
REST_POINTS = {
    "河濱範例路線": "補水站（起點橋往前 2.0k）可補水；折返公園為折返點",
    "繞圈路線": "每圈會回到起點，水放起點即可",
}


def _tool_get_today_status():
    try:
        h = requests.get(f"{WELLNESS_BASE}/api/health-check",
                         headers={"X-Access-Token": WELLNESS_TOKEN}, timeout=30).json()
        t = requests.get(f"{WELLNESS_BASE}/api/today",
                         headers={"X-Access-Token": WELLNESS_TOKEN}, timeout=30).json()
        plan = h.get("today_plan") or {}
        fc = h.get("forecast") or {}
        return {
            "紅綠燈": h.get("headline"),
            "建議": h.get("action"),
            "今日課表": plan.get("workout"),
            "今天該怎麼調": f"{plan.get('action')}：{plan.get('advice')}" if plan else None,
            "未來預測": fc.get("note"),
            "四項偵測": [f"{s['label']}：{s['msg']}" for s in h.get("signals", [])],
            "恢復力HRV": t.get("hrv"), "靜息心率": t.get("restingHR"),
            "睡眠小時": t.get("sleepHrs"), "TSB狀態值": t.get("tsb"),
        }
    except Exception as e:
        return {"error": f"查不到健康數據：{e}"}


def _tool_get_schedule():
    try:
        from datetime import date
        s = fb.get_latest_schedule()
        if not s:
            return {"error": "目前沒有課表資料"}
        days = s.get("days", {}) or {}
        wd = date.today().weekday()  # 0=Mon
        today_key = f"D{wd + 1}" if wd <= 4 else next((k for k in days if "週末" in k), None)
        out = {"週期": s.get("week_range"),
               "今天": f"星期{'一二三四五六日'[wd]}（{today_key or '週末（待補）'}）"}
        today_wo = days.get(today_key, {}).get("my_workout") if today_key else None
        if today_wo:
            out["今天課表"] = today_wo
        for k, v in days.items():
            if v.get("is_for_me", True) and v.get("my_workout"):
                out[k] = v.get("my_workout")
        return out
    except Exception as e:
        return {"error": f"查課表失敗：{e}"}


def _tool_list_routes():
    return {"路線": ROUTES, "補水休息點": REST_POINTS}


def _capture_route_log(fn, *args):
    """route_log 的指令函式直接 print，攔 stdout 當工具結果"""
    import io
    import contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            fn(*args)
        return buf.getvalue().strip() or "（沒有結果）"
    except Exception as e:
        return f"查詢失敗：{e}"


def _tool_plan_route(target_km, from_node="起點橋"):
    import route_log as rl
    plan = _capture_route_log(rl.cmd_plan, float(target_km), from_node or "起點橋")
    return {"折返組合": plan, "補水休息點": REST_POINTS["河濱範例路線"]}


def _tool_route_distance(a, b):
    import route_log as rl
    return {"距離": _capture_route_log(rl.cmd_between, a, b)}


_VDOT_BUCKETS = [
    ("5K", 4.9, 5.5), ("10K", 9.7, 11.0), ("半馬", 20.8, 22.2), ("全馬", 41.5, 44.0),
]


def _is_interval_workout(interval_summary) -> bool:
    """從第一筆分圈判斷是否間歇課。格式如 '23x 1m40s 171bpm'：
    ≥3 組且單圈 ≤180 秒＝間歇；連續跑的每公里自動分圈（如 '42x 6m29s'）單圈較長，不會誤中。"""
    import re
    if not interval_summary or not isinstance(interval_summary, list):
        return False
    m = re.match(r"(\d+)x (?:(\d+)m)?(\d+)s", str(interval_summary[0]))
    if not m:
        return False
    count = int(m.group(1))
    lap_sec = int(m.group(2) or 0) * 60 + int(m.group(3))
    return count >= 3 and lap_sec <= 180


def _tool_get_training_paces():
    """近一年各距離最佳（intervals.icu）→ Daniels VDOT → 五配速。

    兩個防呆（皆實測踩過）：
    - 排除間歇課：moving_time 不含休息段，配速虛高會灌爆 VDOT（6/18 間歇被誤判 42.4）。
      判準看第一筆分圈「≥3 組且單圈 ≤3 分鐘」；連續跑的每公里自動分圈（全馬 42x 6m29s）不會誤中
    - 採用 VDOT 取「最長的非全馬距離」（半馬>10K>5K）：短距離跑力高只代表速度好，
      拿它開配速會超出耐力；全馬受高溫/掉速影響另列參考
    """
    import vdot as vd
    from datetime import date, timedelta
    try:
        end = date.today()
        acts = ic.get_activities_by_range((end - timedelta(days=365)).isoformat(), end.isoformat())
        runs = []
        for a in acts:
            if a.get("type") != "Run":
                continue
            km = (a.get("distance") or 0) / 1000
            sec = a.get("moving_time") or 0
            if km and sec and not _is_interval_workout(a.get("interval_summary")):
                runs.append({"date": (a.get("start_date_local") or "")[:10],
                             "km": round(km, 2), "sec": sec})
        best = {}
        for label, lo, hi in _VDOT_BUCKETS:
            cands = [r for r in runs if lo <= r["km"] <= hi]
            if not cands:
                continue
            top = max(cands, key=lambda r: vd.estimate_vdot(r["km"], r["sec"] / 60))
            m, s = divmod(top["sec"], 60)
            h, m = divmod(m, 60)
            best[label] = {"日期": top["date"], "距離km": top["km"],
                           "時間": f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}",
                           "vdot": vd.estimate_vdot(top["km"], top["sec"] / 60)}
        if not best:
            return {"error": "近一年沒有可估跑力的紀錄"}
        use = None
        for label in ("半馬", "10K", "5K", "全馬"):
            if label in best:
                use = best[label]["vdot"]
                use_label = label
                break
        return {
            "各距離最佳": best,
            "採用跑力VDOT": use,
            "採用依據": f"{use_label} 最佳表現（最長非全馬距離；短距離跑力偏高代表速度好耐力弱，開配速用耐力那把尺）",
            "訓練配速": vd.training_paces(use),
        }
    except Exception as e:
        return {"error": f"查跑力失敗：{e}"}


def _tool_get_weather(lat=None, lon=None):
    try:
        import weather_client as wc
        bundle = wc.forecast_bundle(lat=lat, lon=lon)
        today = bundle.get("today") or {}
        return today if today else {"error": "今天預報抓不到"}
    except Exception as e:
        return {"error": f"查天氣失敗：{e}"}


def _tool_push_workout(date_str, name, description):
    """建 intervals.icu WORKOUT event（會自動同步 Garmin，7/8 已實測）"""
    try:
        athlete_id = os.getenv("INTERVALS_ATHLETE_ID", "")
        api_key = os.getenv("INTERVALS_API_KEY")
        resp = requests.post(
            f"https://intervals.icu/api/v1/athlete/{athlete_id}/events",
            auth=("API_KEY", api_key),
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            json={"category": "WORKOUT", "start_date_local": f"{date_str}T06:00:00",
                  "type": "Run", "name": name, "description": description},
            timeout=20)
        resp.raise_for_status()
        ev = resp.json()
        return {"結果": "已排入", "event_id": ev.get("id"), "日期": date_str, "名稱": name,
                "提醒": "幾分鐘內會同步到 Garmin Connect 與手錶"}
    except Exception as e:
        return {"error": f"排課表失敗：{e}"}


def _tool_get_recent_runs(days=30):
    try:
        runs = [a for a in ic.get_recent_activities(days=days) if a.get("type") == "Run"]
        runs.sort(key=lambda a: a.get("start_date_local", ""), reverse=True)
        out = []
        for a in runs[:20]:
            s = ic.format_activity_summary(a)
            out.append({"日期": s.get("date"), "距離km": s.get("distance_km"),
                        "配速": s.get("avg_pace"), "均心率": s.get("avg_hr")})
        return {f"近{days}天共{len(runs)}筆": out}
    except Exception as e:
        return {"error": f"查跑量失敗：{e}"}


_DISPATCH = {
    "get_today_status": lambda inp: _tool_get_today_status(),
    "get_schedule": lambda inp: _tool_get_schedule(),
    "list_routes": lambda inp: _tool_list_routes(),
    "get_recent_runs": lambda inp: _tool_get_recent_runs(int(inp.get("days", 30) or 30)),
    "plan_route": lambda inp: _tool_plan_route(inp.get("target_km"), inp.get("from_node")),
    "route_distance": lambda inp: _tool_route_distance(inp.get("a", ""), inp.get("b", "")),
    "get_weather": lambda inp: _tool_get_weather(inp.get("lat"), inp.get("lon")),
    "get_training_paces": lambda inp: _tool_get_training_paces(),
    "push_workout_to_garmin": lambda inp: _tool_push_workout(
        inp.get("date", ""), inp.get("name", "訓練"), inp.get("description", "")),
}


def _strip_md(t: str) -> str:
    """去掉 **粗體**、## 標題、--- 分隔線（respond 工具的欄位也可能夾雜 markdown）。"""
    import re
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*]{3,}\s*$", "", t, flags=re.M)
    return t.strip()


def _fallback_reply(headline: str, status: str = "warn") -> dict:
    return {"headline": _strip_md(headline)[:60] or "教練暫無回覆",
            "status": status, "rows": [], "tips": [], "ask": ""}


def _normalize_reply(data: dict) -> dict:
    """把 respond 工具的 input 收斂成保證安全的結構（防呆，不信任模型 100% 照 schema 給）。"""
    status = data.get("status") if data.get("status") in ("good", "warn", "bad") else "warn"
    rows = []
    for r in (data.get("rows") or [])[:7]:
        label = _strip_md(str(r.get("label", "")).strip())
        value = _strip_md(str(r.get("value", "")).strip())
        if label and value:
            rows.append({"label": label, "value": value})
    tips = [_strip_md(str(t).strip()) for t in (data.get("tips") or [])[:3] if str(t).strip()]
    return {
        "headline": _strip_md(str(data.get("headline", "")).strip()) or "教練回覆",
        "status": status,
        "rows": rows,
        "tips": tips,
        "ask": _strip_md(str(data.get("ask", "")).strip()),
    }


def run_coach(user_message: str, max_loops: int = 12) -> dict:
    """跑一輪對話：Claude tool-use 迴圈，最終透過 respond 工具收斂成結構化答案
    （headline/status/rows/tips/ask），交給 coach_flex.build_reply() 組 Flex 卡，
    不再回長文字段落——手機讀起來要能一眼掃過。"""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    messages = [{"role": "user", "content": user_message}]
    for _ in range(max_loops):
        resp = client.messages.create(model=MODEL, max_tokens=1024,
                                       system=SYSTEM, tools=TOOLS, messages=messages)
        if resp.stop_reason != "tool_use":
            # respond 是唯一該有的終止路徑；模型若直接吐文字，防呆包成最小結構
            text = "".join(b.text for b in resp.content if b.type == "text")
            return _fallback_reply(text)
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            if block.name == "respond":
                return _normalize_reply(block.input or {})
            fn = _DISPATCH.get(block.name, lambda inp: {"error": "unknown tool"})
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": json.dumps(fn(block.input or {}), ensure_ascii=False)})
        messages.append({"role": "user", "content": results})
    return _fallback_reply("教練想太久了，請再問一次或換個問法")
