"""教練訓練邏輯持續學習（取代寫死不會變的 COACH_LOGIC_SUMMARY / COACH_OUTLOOK_PREDICTION 快照）。

背景：wellness-dashboard 原本的教練邏輯摘要與下兩週展望，是 2026-07-10 對 152 週歷史課表
做的一次性人工分析（見 docs/coach-history/COACH-LOGIC.md、PREDICTION.md），寫死成
wellness-dashboard app.py 裡的 Python 常數。教練會進化，貼新課表不會讓那兩個常數變化——
原作者 要的是「資料進來會自動重新學習」。

流程（maybe_relearn，供 poller.py 每輪呼叫）：
- 讀 Firestore `_meta/coach_logic_state` 記錄「上次學習依據的最新一週 week_start」
- 跟 `coach_history` 目前實際最新一週（排除 source=GAP 標記列）比對，
  有新增至少 1 週才觸發重新學習（LLM 呼叫要錢，不是每輪 poll 都跑）
- 重新學習分兩段：
  a) 純函式統計（不用 LLM，全量 coach_history 重算）：分組配速級距差異、
     質量課類型分佈、賽後恢復週長度樣本 —— 算法對照 docs/coach-history/COACH-LOGIC.md
     §2/§4/§5 的既有分類邏輯（純函式，離線可測，回傳結果供除錯與之後改 prompt 用，
     不是最終產物本身）
  b) LLM 生成質性摘要與下兩週展望：把統計結果 + 最近 8-12 週原始課表文字餵給 Claude，
     複用 ai_analyzer 的呼叫模式（_get_client()），寫死 COACH-LOGIC.md 的既有結論當錨點，
     避免小樣本統計把方向帶偏
- 產出寫入 Firestore `_meta/coach_logic`：logic_summary(list) / outlook(dict，結構同
  COACH_OUTLOOK_PREDICTION) / based_on_latest_week / generated_at / stats
  （LLM 失敗就不寫、也不更新 state，下一輪 poll 會再試一次，不會卡在假成功）

CLI：
  python coach_logic_learner.py --force   忽略 state 比對，強制重新學習一次
"""
import argparse
import json
import os
import re
import statistics
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TPE = ZoneInfo("Asia/Taipei")

COACH_HISTORY_COLLECTION = "coach_history"
STATE_DOC = "coach_logic_state"
OUTPUT_DOC = "coach_logic"
META_COLLECTION = "_meta"

ATHLETE_NAME = os.getenv("ATHLETE_NAME", "小明")
MODEL = os.getenv("COACH_LOGIC_MODEL", "claude-sonnet-5")
RECENT_WEEKS_FOR_LLM = 10  # 8-12 週原始文字餵給 LLM，取中間值

DAY_KEYS = [f"D{i}" for i in range(1, 8)]


def _now_iso() -> str:
    return datetime.now(TPE).isoformat(timespec="seconds")


# ── 純函式 1：分組配速級距差異（比對 COACH-LOGIC.md §2 分組體系）──────
#
# 2024 年樣本用「S/A/B/C/D/E/F 字母組」標題，緊接著配速範圍（如「S組...P'72-70s」）；
# 2025 年後改用姓名+完賽時間帶分組，不再出現字母標題，這類週會被自然跳過（COACH-LOGIC.md
# §2.4 已記錄這個演變，不是 bug）。

_LETTER_MAP = {"Ｓ": "S", "Ａ": "A", "Ｂ": "B", "Ｃ": "C", "Ｄ": "D", "Ｅ": "E", "Ｆ": "F"}
_GROUP_TOKEN_RE = re.compile(
    r"([SABCDEFＳＡＢＣＤＥＦ])組"
    r"|(?<=[‘’'\"])([SABCDEFＳＡＢＣＤＥＦ])(?=\s*[一-鿿（(])"
)
_PACE_RANGE_RE = re.compile(
    r"P[‘’'\"“”]?\s*(\d{2,3})\s*[-~]\s*(\d{2,3})(?!\s*%)"
)
_ADJACENT_TIERS = [("S", "A", "S→A"), ("A", "B", "A→B"), ("B", "C", "B→C"), ("C", "D", "C→D")]
_MAX_PLAUSIBLE_TIER_DIFF = 60  # 排除不同基準單位混算造成的離群值（純函式門檻，非魔法數）
_GROUP_WINDOW_CHARS = 300  # 字母標題後往後找配速範圍的字元視窗


def extract_group_paces(day_text: str) -> dict:
    """從單日課表文字抓 S/A/B/C/D/E/F 字母分組後緊接的配速範圍中點（純函式）。

    回傳 {字母: 中點秒數}，找不到任何字母分組回空 dict。同一字母只取第一次出現。
    """
    if not day_text:
        return {}
    markers = list(_GROUP_TOKEN_RE.finditer(day_text))
    result = {}
    for i, m in enumerate(markers):
        letter = m.group(1) or m.group(2)
        letter = _LETTER_MAP.get(letter, letter)
        if letter in result:
            continue
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else min(
            len(day_text), start + _GROUP_WINDOW_CHARS
        )
        window = day_text[start:end]
        pm = _PACE_RANGE_RE.search(window)
        if pm:
            lo, hi = int(pm.group(1)), int(pm.group(2))
            result[letter] = (lo + hi) / 2
    return result


def pace_gap_by_tier(weeks: list) -> dict:
    """算 S→A / A→B / B→C / C→D 各級距平均配速差（純函式，離線可測）。

    weeks：coach_history doc 的 list（見 _fetch_coach_history_weeks）。
    """
    tier_diffs = {label: [] for _, _, label in _ADJACENT_TIERS}
    for week in weeks:
        for day_key in DAY_KEYS:
            paces = extract_group_paces(week.get(day_key))
            if not paces:
                continue
            for hi_letter, lo_letter, label in _ADJACENT_TIERS:
                if hi_letter in paces and lo_letter in paces:
                    diff = paces[lo_letter] - paces[hi_letter]
                    if 0 < diff < _MAX_PLAUSIBLE_TIER_DIFF:
                        tier_diffs[label].append(diff)
    return {
        label: {
            "avg": round(statistics.mean(vals), 1) if vals else None,
            "n_samples": len(vals),
        }
        for label, vals in tier_diffs.items()
    }


# ── 純函式 2：質量課類型分佈（比對 COACH-LOGIC.md §4 質量課類型學）────

_COMBO_RE = re.compile(r"\(\s*\d+\s*\+\s*\d+")
_FARTLEK_KEYWORDS = ("法特雷克", "Fartlek", "fartlek")
_INTERVAL_DIST_RE = re.compile(r"(\d{3,4})\s*[*×xX]\s*\d+")

QUALITY_TYPE_OTHER = "其他/待分類"


def classify_quality_type(text: str):
    """依 COACH-LOGIC.md §4 分類邏輯：關鍵字類（組合金字塔/法特雷克）優先判定，
    否則取文字中出現的最大間隔距離歸類。純函式，text 為 None/空字串回 None（不計入統計）。
    """
    if not text:
        return None
    if _COMBO_RE.search(text):
        return "組合金字塔"
    if any(kw in text for kw in _FARTLEK_KEYWORDS):
        return "法特雷克"
    dists = [int(m.group(1)) for m in _INTERVAL_DIST_RE.finditer(text)]
    if not dists:
        return QUALITY_TYPE_OTHER
    base = max(dists)
    if base >= 2000:
        return "2000+ 超長間歇"
    if base >= 1600:
        return "1600 長間歇"
    if 1000 <= base < 1600:
        return "1000-1200 長間歇"
    if base == 800:
        return "800 定量間歇"
    if base == 600:
        return "600 定量間歇"
    if base == 400:
        return "400 定量間歇"
    if base == 200:
        return "200 定量間歇"
    return QUALITY_TYPE_OTHER


def quality_type_distribution(weeks: list) -> dict:
    """統計質量課類型出現週數與占比（純函式）。質量日優先用 doc 的「質量日」欄位
    （notion 來源週有這欄），沒有就退回 D4、再退回 D3（比照 COACH-LOGIC.md §3 質量日
    多落在 D3/D4 的觀察）。
    """
    counts = {}
    total = 0
    for week in weeks:
        quality_day_key = week.get("質量日") or "D4"
        text = week.get(quality_day_key) or week.get("D4") or week.get("D3")
        label = classify_quality_type(text)
        if label is None:
            continue
        counts[label] = counts.get(label, 0) + 1
        total += 1
    by_type = {
        k: {"weeks": v, "pct": round(v / total * 100, 1) if total else 0}
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
    }
    return {"total_weeks_classified": total, "by_type": by_type}


# ── 純函式 3：賽後恢復週長度樣本（比對 COACH-LOGIC.md §5/§7、PREDICTION.md §3）──
#
# 只用明確的「選擇性訓練/娛樂/免評量」標記週偵測，不嘗試從課表結構反推恢復期是否
# 已結束（那需要逐週人工判讀，見 PREDICTION.md §3 的 2023-12 案例）。這裡刻意保守，
# 寧可少報也不亂報（呼應 illness_watch.py 的「資料不足就不判定」原則）——輸出主要
# 供 LLM 步驟參考樣本量，質性的「約 3-4 週」結論仍以 COACH-LOGIC.md 既有人工分析為準。

_RECOVERY_KEYWORDS = ("選擇性訓練", "娛樂", "免評量")


def _week_has_recovery_marker(week: dict) -> bool:
    for key in DAY_KEYS + ["週末訓練"]:
        text = week.get(key) or ""
        if any(kw in text for kw in _RECOVERY_KEYWORDS):
            return True
    return False


def post_race_recovery_week_lengths(weeks: list) -> dict:
    """偵測連續出現賽後恢復標記的週數，純函式。"""
    lengths = []
    streak = 0
    for week in weeks:
        if _week_has_recovery_marker(week):
            streak += 1
        else:
            if streak > 0:
                lengths.append(streak)
            streak = 0
    if streak > 0:
        lengths.append(streak)  # 資料尾端仍在恢復期，尚未結束的樣本也一併記錄
    return {
        "samples_weeks": lengths,
        "avg_weeks": round(statistics.mean(lengths), 1) if lengths else None,
        "n_samples": len(lengths),
    }


def compute_stats(weeks: list) -> dict:
    """彙整三項純函式統計，供 LLM prompt 與除錯用。"""
    return {
        "n_weeks_analyzed": len(weeks),
        "latest_week_start": weeks[-1]["week_start"] if weeks else None,
        "pace_gap_by_tier": pace_gap_by_tier(weeks),
        "quality_type_distribution": quality_type_distribution(weeks),
        "post_race_recovery_week_lengths": post_race_recovery_week_lengths(weeks),
    }


# ── Firestore 讀取（延遲 import firebase_admin，呼應 data_vault.py 既有慣例）───

def _fetch_coach_history_weeks(db) -> list:
    """讀全部 coach_history docs，排除 GAP 標記列與缺 week_start 的髒資料，
    依 week_start 升冪排序回傳。

    ⚠ 全掃整個集合，只准在「確定要重新學習」後呼叫；每輪 poll 的變化偵測
    用 _latest_week_start()（limit 查詢）。全掃 × 每 5 分鐘 poll 一天可燒
    數萬 reads，會把 Firestore Spark 免費額度（50k reads/日）打爆。"""
    docs = db.collection(COACH_HISTORY_COLLECTION).stream()
    weeks = []
    for d in docs:
        row = d.to_dict() or {}
        if row.get("source") == "GAP" or not row.get("week_start"):
            continue
        weeks.append(row)
    weeks.sort(key=lambda r: r["week_start"])
    return weeks


def _latest_week_start(db):
    """便宜查最新一週 week_start（排除 GAP 標記列），供每輪 poll 變化偵測。
    limit 8 足以涵蓋零星 GAP 列；查不到有效列回 None（呼叫端視同無資料）。"""
    from firebase_admin import firestore
    docs = (db.collection(COACH_HISTORY_COLLECTION)
            .order_by("week_start", direction=firestore.Query.DESCENDING)
            .limit(8).stream())
    for d in docs:
        row = d.to_dict() or {}
        if row.get("source") != "GAP" and row.get("week_start"):
            return row["week_start"]
    return None


# ── LLM：質性摘要與展望（複用 ai_analyzer 的呼叫模式）─────────────────

_ANCHOR_FACTS = (
    f"- 分層同構：不論幾組，同一天質量課永遠是同一套動作結構，只有配速帶不同\n"
    f"- 質量課類型：400m 定量間歇與 1000-1200m 長間歇是最常見的兩種質量課\n"
    f"- 賽後恢復：質量日從規定內容降級為「選擇性訓練/娛樂/免評量」標籤，平日多半 Rest，"
    f"歷史唯一完整追蹤到的案例約 3-4 週恢復團課節奏（樣本很少，僅供參考方向）\n"
    f"- 教練從不對賽後/傷後給個別化漸進課表，只在週主題用心理喊話式提醒"
)

_SYSTEM_PROMPT = (
    f"你是專業跑步教練助理，負責幫業餘跑者（{ATHLETE_NAME}）維護一份會隨教練課表持續更新的"
    "「教練邏輯摘要」與「下兩週展望」。只回傳合法 JSON，不要有任何 JSON 以外的文字、"
    "不要加 ```json 圍欄。語氣專業不誇大，不確定的地方誠實標低信心，繁體中文台灣用語，"
    "避免 AI 腔（不用「賦能」「打造閉環」「深刻理解」之類空話），不使用破折號。"
)


def _week_range_label(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    return f"{monday.month:02d}/{monday.day:02d}-{sunday.month:02d}/{sunday.day:02d}"


def _format_recent_weeks(weeks: list, n: int = RECENT_WEEKS_FOR_LLM) -> str:
    recent = weeks[-n:]
    blocks = []
    for week in recent:
        lines = [f"== 週起始 {week.get('week_start')}（來源：{week.get('source')}）=="]
        for key in DAY_KEYS + ["週末訓練"]:
            text = week.get(key)
            if text:
                snippet = text if len(text) <= 400 else text[:400] + "…（截斷）"
                lines.append(f"[{key}] {snippet}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _build_prompt(stats: dict, weeks: list) -> str:
    latest_monday = date.fromisoformat(weeks[-1]["week_start"])
    target1 = latest_monday + timedelta(days=7)
    target2 = target1 + timedelta(days=7)
    weeks_by_start = {w["week_start"]: w for w in weeks}
    target1_actual = weeks_by_start.get(target1.isoformat())
    target2_actual = weeks_by_start.get(target2.isoformat())

    def _actual_note(target_monday, actual):
        label = _week_range_label(target_monday)
        if actual is None:
            return f"{label}：coach_history 還沒有這週資料，這是預測範圍。"
        return (
            f"{label}：coach_history 已經有這週的真實課表了（週起始 {actual.get('week_start')}），"
            "這不是預測範圍——請改成客觀描述教練實際排了什麼，不要用「預測」「大機率」這種語氣，"
            "confidence 一律填「高」。"
        )

    stats_desc = json.dumps(stats, ensure_ascii=False, indent=2)
    recent_text = _format_recent_weeks(weeks)
    today_str = datetime.now(TPE).date().isoformat()

    return f"""你要更新「教練訓練邏輯摘要」與「下兩週課表展望」，這是持續學習機制的一部分：
教練每週貼新課表，你的任務是根據最新資料重新歸納規律、更新展望，取代寫死不會變的舊快照。

今天日期：{today_str}

已知的既有深度分析結論（{ATHLETE_NAME} 教練班，152 週人工分析，你的新結論不能跟這些
已驗證的事實矛盾，除非新資料明確推翻它）：
{_ANCHOR_FACTS}

程式重新統計的最新數字（僅供參考，可能因樣本量或分類方式跟上面的深度分析有出入，
出入是正常的、不代表矛盾，兩邊結論方向一致即可）：
{stats_desc}

最近 {min(RECENT_WEEKS_FOR_LLM, len(weeks))} 週原始課表文字（內容是全班課表，
你要自己從裡面找出 {ATHLETE_NAME} 那一段來判讀）：
{recent_text}

下兩週的狀態判斷（用來決定是預測還是客觀描述）：
{_actual_note(target1, target1_actual)}
{_actual_note(target2, target2_actual)}

請只回傳一個 JSON 物件，格式如下：
{{
  "logic_summary": ["重點1", "重點2", "重點3"],
  "outlook": {{
    "generated_at": "{today_str}",
    "note": "統計推測，不是教練實際排定的課表，教練課表永遠優先",
    "weeks": [
      {{"range": "{_week_range_label(target1)}", "summary": "...", "confidence": "低/中/高"}},
      {{"range": "{_week_range_label(target2)}", "summary": "...", "confidence": "低/中/高"}}
    ]
  }}
}}

規則：
- logic_summary 給 3-4 條，繁體中文，每條一句濃縮重點，不用 Markdown、不用編號前綴，
  風格比照「分層同構：不論幾組...」這種「關鍵詞：說明」格式
- outlook.weeks 剛好兩筆，range 直接用上面給定的字串，不要自己重算日期
- 若上面已經明講某週有真實資料，summary 改成客觀描述當週實際安排，不要用「預測」語氣，
  confidence 固定填「高」
- 若是真的預測週，summary 要講清楚依據是什麼（延續什麼模式、跟哪個歷史樣本類推），
  confidence 要老實反映樣本量（樣本少、待驗證就填「低」）"""


def _parse_llm_json(text: str) -> dict:
    """把 LLM 回應解析成 dict；格式不對就回空 dict（呼叫端視為失敗，不寫入）。"""
    if not text:
        return {}
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"[coach_logic_learner] LLM 輸出非合法 JSON，捨棄：{e}")
        return {}
    if not isinstance(data, dict) or "logic_summary" not in data or "outlook" not in data:
        print("[coach_logic_learner] LLM 輸出缺必要欄位，捨棄")
        return {}
    return data


def generate_logic_update(stats: dict, weeks: list) -> dict:
    """呼叫 Claude 產生 logic_summary + outlook；失敗回空 dict（呼叫端不寫入、下輪再試）。"""
    if not weeks:
        return {}
    import ai_analyzer as ai  # 延遲 import：複用既有 _get_client() 模式，避免模組層依賴 dotenv
    client = ai._get_client()
    if not client:
        print("[coach_logic_learner] 無 Anthropic client（缺 ANTHROPIC_API_KEY 或未裝 anthropic），略過")
        return {}

    prompt = _build_prompt(stats, weeks)
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        if msg.stop_reason == "max_tokens":
            print("[coach_logic_learner] LLM 回應被 max_tokens 截斷，內容可能不完整")
        # claude-sonnet-5 預設會先吐一個 thinking content block（.text 是 None），
        # 真正的文字在後面的 text block；不能直接假設 content[0] 就是答案
        # （2026-07-10 首跑踩過：content[0].text=None 導致 _parse_llm_json 靜默收到空字串）。
        text = "".join(
            getattr(block, "text", "") or ""
            for block in msg.content
            if getattr(block, "type", None) == "text"
        )
        return _parse_llm_json(text)
    except Exception as e:
        print(f"[coach_logic_learner] LLM 呼叫失敗：{e}")
        return {}


# ── 主流程：maybe_relearn（供 poller.py 每輪呼叫）─────────────────────

def _run_relearn(db, weeks: list, latest_week_start: str):
    stats = compute_stats(weeks)
    llm_result = generate_logic_update(stats, weeks)
    if not llm_result:
        print("[coach_logic_learner] LLM 生成失敗，state 不更新（下一輪再試，避免卡在假成功）")
        return False

    doc = {
        "logic_summary": llm_result.get("logic_summary", []),
        "outlook": llm_result.get("outlook", {}),
        "based_on_latest_week": latest_week_start,
        "generated_at": _now_iso(),
        "stats": stats,
    }
    db.collection(META_COLLECTION).document(OUTPUT_DOC).set(doc)
    db.collection(META_COLLECTION).document(STATE_DOC).set(
        {"based_on_latest_week": latest_week_start, "updated_at": _now_iso()}, merge=True
    )
    print(
        f"[coach_logic_learner] 學習完成，寫入 _meta/{OUTPUT_DOC}"
        f"（based_on_latest_week={latest_week_start}）"
    )
    return True


def maybe_relearn(force: bool = False) -> bool:
    """有新一週 coach_history 資料才重新學習；force=True 忽略 state 比對強制重跑。

    回傳是否真的跑了一次學習（含 LLM 呼叫失敗仍算「有觸發」但寫入失敗的情況回 False，
    呼叫端只需知道有沒有寫出新結果）。
    """
    try:
        import firebase_client as fb
        db = fb._init()

        # 先便宜比對（1 筆 state + limit 8 查詢），沒新週就結束——
        # 不准每輪 poll 全掃歷史（見 _fetch_coach_history_weeks 註解）
        if not force:
            latest = _latest_week_start(db)
            if latest is None:
                print("[coach_logic_learner] coach_history 目前沒有資料，略過")
                return False
            state_snap = db.collection(META_COLLECTION).document(STATE_DOC).get()
            last_learned = state_snap.to_dict().get("based_on_latest_week") if state_snap.exists else None
            if last_learned == latest:
                print(f"[coach_logic_learner] 最新一週 {latest} 沒變化，略過重新學習")
                return False

        weeks = _fetch_coach_history_weeks(db)
        if not weeks:
            print("[coach_logic_learner] coach_history 目前沒有資料，略過")
            return False
        latest_week_start = weeks[-1]["week_start"]

        print(f"[coach_logic_learner] 偵測到新資料（最新一週 {latest_week_start}），開始重新學習")
        return _run_relearn(db, weeks, latest_week_start)
    except Exception as e:
        print(f"[coach_logic_learner] 重新學習失敗：{e}")
        return False


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="教練訓練邏輯持續學習")
    parser.add_argument("--force", action="store_true", help="忽略 state 比對，強制重新學習一次")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    ran = maybe_relearn(force=args.force)
    print("[coach_logic_learner] 完成，有寫入新結果" if ran else "[coach_logic_learner] 完成，本次沒有寫入")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    main()
