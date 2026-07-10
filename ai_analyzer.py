"""
AI 訓練分析器 - 使用 Anthropic Claude API
分析每次跑步訓練，給出個人化建議
"""
import os
import re
from datetime import datetime
from typing import Optional
import requests
from dotenv import load_dotenv
from schedule_match import evaluate_pace
load_dotenv()


def strip_markdown(text: str) -> str:
    """AI 輸出淨化：去掉 Markdown 記號（LINE 卡與儀表板都是純文字渲染，
    殘留的 ** 會變成「本週目標 ****」這種怪東西——2026-07-10 原作者 實截）。
    prompt 已要求純文字，這裡是模型漏網時的程式層防線。"""
    if not text:
        return text
    out = re.sub(r"\*+", "", text)               # 粗體/斜體/列表星號
    out = re.sub(r"^#+\s*", "", out, flags=re.MULTILINE)  # 標題井號
    return out.strip()

_client = None

def _get_client():
    global _client
    if _client is None:
        try:
            import anthropic
            _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        except ImportError:
            pass
    return _client

_athlete_name = os.getenv("ATHLETE_NAME", "小明")
SYSTEM_PROMPT = f"""你是一位專業跑步教練助理，協助分析業餘跑者（{_athlete_name}）的訓練數據。

背景：
- 跑者為長期跑者，練習 Zone 2、間歇、長距離，有教練課表
- 每次分析需簡短（3-5句話，總字數控制在150字以內），語氣親切但專業
- 使用繁體中文，避免冗詞與 AI 腔
- 輸出格式為純文字，可適度換行，不使用 Markdown
- 聚焦：訓練表現評估 + 一個具體建議或提醒
"""


def build_training_desc(summary: dict, schedule_workout: str = None, weather: dict = None) -> str:
    """把單次訓練的原始欄位組成一段結構化文字描述（純函式，無 LLM 呼叫）。

    這是 analyze_training()（Haiku，跑後即時推播用）與 analyze_deep()（Sonnet，
    深度分析用）共用的「今日表現」事實底稿——同一組數字只組一次，兩邊 AI 各自
    用不同語氣/長度轉述，不重刻欄位邏輯（DRY，見 training-line 純函式鐵則）。
    """
    lines = [
        f"訓練日期：{summary.get('date', '')}",
        f"距離：{summary.get('distance_km', 0)} km",
        f"時間：{summary.get('moving_time', '')}",
        f"均配速：{summary.get('avg_pace', 'N/A')} /km",
    ]

    if summary.get("avg_hr"):
        lines.append(f"均心率：{summary['avg_hr']} bpm（最高 {summary.get('max_hr', '?')} bpm）")

    cadence = summary.get("average_cadence")
    if cadence:
        spm = int(cadence * 2)
        lines.append(f"步頻：{spm} spm")

    stride = summary.get("average_stride")
    if stride:
        lines.append(f"步幅：{round(stride, 2)} m")

    elev = summary.get("total_elevation_gain")
    if elev and elev > 0:
        lines.append(f"爬升：{round(elev)} m")

    load = summary.get("icu_training_load") or summary.get("trimp")
    if load:
        lines.append(f"訓練負荷：{round(load, 1)}")

    rpe = summary.get("icu_rpe")
    if rpe:
        lines.append(f"RPE：{rpe}/10")

    zone_times = summary.get("icu_hr_zone_times")
    if zone_times and len(zone_times) >= 4:
        total = sum(zone_times)
        if total > 0:
            z_low = (zone_times[0] + zone_times[1]) / total * 100
            z_mid = zone_times[2] / total * 100
            z_high = sum(zone_times[3:]) / total * 100
            lines.append(f"心率區間：Z1-2 {z_low:.0f}%  Z3 {z_mid:.0f}%  Z4+ {z_high:.0f}%")

    interval_detail = summary.get("interval_detail")
    interval_summary = summary.get("interval_summary")
    if interval_detail:
        d = interval_detail
        rec = (f"，組間{d['recovery_kind']}平均 {d['avg_recovery_sec']} 秒"
               if d.get("recovery_kind") and d.get("avg_recovery_sec") else "")
        lines.append(
            f"間歇（逐組真資料）：{d['n_work']} 組 × 約 {d['work_dist_m']}m，"
            f"工作段均配速 {d['avg_work_pace']}（最快 {d['best_work_pace']}／最慢 {d['worst_work_pace']}）"
            + (f"，工作段均心率 {d['avg_work_hr']}" if d.get("avg_work_hr") else "") + rec)
        lines.append(
            "重要：這是間歇課。上面的「均配速」混入了組間恢復（站休/緩跑），沒有意義，"
            "不得用它評論快慢；配速表現一律以「工作段均配速」為準。")
    elif interval_summary:
        lines.append(f"間歇：{interval_summary}")

    # 溫度優先用 GPS 記錄的 average_temp，fallback 用天氣 API
    actual_temp = summary.get("average_temp")
    humidity = weather.get("humidity") if weather else None
    apparent = weather.get("apparent_temp_c") if weather else None
    precip_mm = weather.get("precip_mm") if weather else None
    condition = weather.get("condition", "") if weather else ""

    if actual_temp is not None:
        temp_display = f"{round(actual_temp, 1)}°C"
        if apparent is not None:
            temp_display += f"（體感 {apparent}°C）"
        w_parts = [temp_display]
        if humidity is not None:
            w_parts.append(f"濕度 {humidity}%")
        if precip_mm is not None:
            w_parts.append(f"降雨 {precip_mm}mm")
        if condition:
            w_parts.append(condition)
        lines.append(f"天氣：{'，'.join(w_parts)}")

    if schedule_workout:
        lines.append(f"今日課表：{schedule_workout}")
        # 間歇課不做「全場均配速 vs 課表」判讀——均配速混入組間恢復，判了只會誤導
        if not interval_detail:
            _pace = evaluate_pace(summary.get("avg_pace"), schedule_workout)
            if _pace:
                lines.append(f"配速達標判讀（程式已算定，配速方向一律以此為準）：{_pace.text}")

    exec_score = summary.get("exec_score")
    if exec_score is not None:
        lines.append(f"課表執行達成度（程式已算定）：{exec_score} 分 · {summary.get('exec_label', '')}")

    role = summary.get("role", "standalone")
    if role == "warmup":
        lines.append("備註：此為當日暖身跑")
    elif role == "cooldown":
        lines.append("備註：此為當日緩跑")

    return "\n".join(lines)


def analyze_training(summary: dict, schedule_workout: str = None, weather: dict = None) -> str:
    """
    分析單次訓練，回傳 AI 評語

    Args:
        summary: format_activity_summary() 的輸出
        schedule_workout: 當天課表要求（可選）
        weather: weather_client 的輸出（可選）

    Returns:
        AI 分析文字（3-5 句）
    """
    sport = summary.get("sport", "Unknown")
    if sport != "Run":
        return _analyze_non_run(summary)

    training_desc = build_training_desc(summary, schedule_workout, weather)

    user_msg = f"""以下是今日跑步訓練數據：

{training_desc}

請根據上述數據給出訓練評語，需涵蓋：
1. 訓練表現整體評估
2. 天氣（溫度、濕度、降雨）對心率與表現的影響
3. 一個具體可執行的建議
若上方有「配速達標判讀」，配速快慢方向與秒數一律照它陳述，不得自行重新判斷（配速數字越大代表越慢）。請結合心率與天氣綜合評估這趟的實質強度，而非只看配速。"""

    c = _get_client()
    if not c:
        return ""
    try:
        with c.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            return strip_markdown(stream.get_final_message().content[0].text)
    except Exception as e:
        print(f"[ai_analyzer] 分析失敗：{e}")
        return ""


def _analyze_non_run(summary: dict) -> str:
    """非跑步活動的簡短分析"""
    sport = summary.get("sport", "Unknown")
    time_str = summary.get("moving_time", "")
    load = summary.get("icu_training_load") or summary.get("trimp")

    lines = [
        f"運動項目：{sport}",
        f"時間：{time_str}",
    ]
    if load:
        lines.append(f"訓練負荷：{round(load, 1)}")

    rpe = summary.get("icu_rpe")
    if rpe:
        lines.append(f"RPE：{rpe}/10")

    training_desc = "\n".join(lines)

    c = _get_client()
    if not c:
        return ""
    try:
        with c.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"以下是今日訓練紀錄：\n{training_desc}\n\n請給一句簡短鼓勵與提醒。"}],
        ) as stream:
            return strip_markdown(stream.get_final_message().content[0].text)
    except Exception as e:
        print(f"[ai_analyzer] 分析失敗：{e}")
        return ""


def analyze_schedule(parsed: dict) -> dict:
    """
    分析教練課表，回傳訓練目標與注意事項
    Returns: {"goal": str, "notes": str}
    """
    week_range = parsed.get("week_range", "")
    days = parsed.get("days", {})

    lines = [f"週期：{week_range}"]
    for key in sorted(days.keys()):
        info = days[key]
        if not info.get("is_for_me"):
            continue
        workout = info.get("my_workout", "")
        if info.get("is_rest") or not workout:
            lines.append(f"{key}：休息")
        else:
            lines.append(f"{key}：{workout}")

    schedule_desc = "\n".join(lines)

    c = _get_client()
    if not c:
        return {}

    prompt = f"""以下是這週的個人跑步課表：

{schedule_desc}

請回答兩件事（用繁體中文，每點 2-3 句，不用 Markdown）：
1. 本週訓練目標：這週課表的核心訓練目的是什麼？
2. 執行注意事項：跑這週課表時最需要注意什麼？（例如配速控制、疲勞累積、天氣應對等）"""

    try:
        msg = c.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=f"你是一位專業跑步教練助理，協助分析業餘跑者（{_athlete_name}）的訓練課表。語氣親切但專業，使用繁體中文，避免 AI 腔。",
            messages=[{"role": "user", "content": prompt}],
        )
        text = strip_markdown(msg.content[0].text)
        # 拆成目標 / 注意事項兩段
        lines_out = [l.strip() for l in text.split("\n") if l.strip()]
        goal_lines, notes_lines = [], []
        current = None
        for l in lines_out:
            if l.startswith("1.") or "訓練目標" in l:
                current = "goal"
                l = l.lstrip("1. ").replace("本週訓練目標：", "").strip()
            elif l.startswith("2.") or "注意事項" in l:
                current = "notes"
                l = l.lstrip("2. ").replace("執行注意事項：", "").strip()
            if current == "goal" and l:
                goal_lines.append(l)
            elif current == "notes" and l:
                notes_lines.append(l)
        return {
            "goal": " ".join(goal_lines),
            "notes": " ".join(notes_lines),
            "raw": text,
        }
    except Exception as e:
        print(f"[ai_analyzer] 課表分析失敗：{e}")
        return {}


def analyze_daily_reminder(workout: str, weather: dict) -> str:
    """
    每日課表提醒的微觀分析：今日課表 + 今日天氣 → 簡短建議
    Returns: 純文字，2-3 句，100 字以內
    """
    c = _get_client()
    if not c:
        return ""

    wx_parts = []
    t_max = weather.get("t_max")
    t_min = weather.get("t_min")
    humidity = weather.get("humidity")
    rain_pct = weather.get("rain_pct")
    comfort = weather.get("comfort", "")
    if t_max and t_min:
        wx_parts.append(f"氣溫 {t_min}–{t_max}°C")
    if humidity is not None:
        wx_parts.append(f"濕度 {humidity}%")
    if rain_pct is not None:
        wx_parts.append(f"降雨機率 {rain_pct}%")
    if comfort:
        wx_parts.append(f"舒適度：{comfort}")

    weather_desc = "，".join(wx_parts) if wx_parts else "天氣資料不足"

    prompt = f"""今日課表：{workout}
今日天氣：{weather_desc}

請根據今日課表與天氣，給出 2-3 句具體建議（繁體中文，100 字以內，不用 Markdown，不用標題）。
聚焦：配速/強度如何因天氣調整、補水或注意事項。"""

    try:
        msg = c.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=f"你是一位專業跑步教練助理，協助業餘跑者（{_athlete_name}）調整當日訓練。語氣親切專業，繁體中文，避免 AI 腔。",
            messages=[{"role": "user", "content": prompt}],
        )
        return strip_markdown(msg.content[0].text)
    except Exception as e:
        print(f"[ai_analyzer] 每日分析失敗：{e}")
        return ""


# ── 深度分析（第二層 Flex，Sonnet，低頻）─────────────────────────
#
# 設計（原作者 2026-07-10 拍板）：
# - 推播當下（poller.py 流程內）就把整份深度分析生成好存進 training_logs.deep_analysis，
#   LINE postback 只負責讀取顯示，不即時呼叫 LLM（按鈕點下去要秒開）
# - 模型只負責「轉述」，不負責「算數」：配速/心率差異（schedule_history）、
#   心率漂移、ACWR/TSB（wellness-dashboard /api/health-check）全部程式先算好數字，
#   餵給 Sonnet 當事實底稿，跟 schedule_match.py／coach_logic_learner.py 同一套鐵則
# - 任一段資料來源失敗（Firestore 查詢、跨服務呼叫、LLM 呼叫本身）只讓「那一段」
#   顯示「這部分資料不足」，不讓整份深度分析開天窗
DEEP_MODEL = os.getenv("DEEP_ANALYSIS_MODEL", "claude-sonnet-5")

_DEEP_SYSTEM_PROMPT = (
    f"你是專業跑步教練助理，正在幫業餘跑者（{_athlete_name}）寫一份完整的課後深度記錄，"
    "像真教練會寫的訓練筆記那樣具體、根據數字說話。只回傳合法 JSON，"
    "不要有任何 JSON 以外的文字、不要加 ```json 圍欄。語氣專業不誇大，"
    "繁體中文台灣用語，避免 AI 腔（不用「賦能」「打造閉環」「深刻理解」之類空話），"
    "不使用破折號，不用 Markdown、不用項目符號或標題前綴，每段 2-4 句。"
    "所有數字（配速快慢方向、心率飄移、ACWR/TSB 判讀）都已經算定，你只負責用白話轉述，"
    "不得自行重新判斷或跟給定數字矛盾。若某段標示「（無資料）」，該段就原樣寫"
    "「這部分資料不足」，不要編造內容。"
    "提到配速時一律寫成「6分10秒」這種純文字格式，絕對不要用 6'10\" 這種帶單引號/雙引號的寫法"
    "（未跳脫的雙引號會讓你回傳的 JSON 直接壞掉、整份深度分析都讀不到）。"
)


def _format_history_facts(cmp) -> Optional[str]:
    """把 schedule_history.HistoryComparison 轉成給 LLM 看的事實文字；cmp 為 None 回 None。"""
    if cmp is None:
        return None
    dates = "、".join(cmp.sample_dates) if cmp.sample_dates else ""
    sample_note = f"（比對樣本：近 {cmp.matched_count} 次同類課表{'，日期 ' + dates if dates else ''}）"
    return f"{cmp.pace_text}；{cmp.hr_text}{sample_note}"


def _format_phase_facts(coach_logic: dict) -> Optional[str]:
    """把 `_meta/coach_logic` doc 轉成給 LLM 看的事實文字；缺 logic_summary 回 None。"""
    if not coach_logic:
        return None
    summary_list = coach_logic.get("logic_summary") or []
    if not summary_list:
        return None
    based_on = coach_logic.get("based_on_latest_week")
    lines = [f"（教練邏輯持續學習系統，根據截至 {based_on} 的課表資料歸納）"] if based_on else []
    lines.extend(summary_list)
    return "\n".join(lines)


def _format_body_facts(cardiac_drift, wellness: dict) -> Optional[str]:
    """心率漂移 + wellness-dashboard /api/health-check 訊號（ACWR/TSB/恢復）轉成事實文字；
    兩者都沒有才回 None。"""
    parts = []
    if cardiac_drift is not None:
        if cardiac_drift <= 4:
            interp = "有氧穩定"
        elif cardiac_drift <= 9:
            interp = "略有飄移，留意配速是否偏快"
        else:
            interp = "飄移明顯，可能恢復不足或強度偏高"
        parts.append(f"心率漂移（同配速下後段比前段高幾下）：{cardiac_drift:+d} bpm（{interp}）")

    if wellness:
        signals = wellness.get("signals") or []
        by_key = {s.get("key"): s for s in signals if s.get("key")}
        acwr = by_key.get("load_spike")
        if acwr:
            parts.append(f"ACWR 訓練負荷比值：{acwr.get('value')}（{acwr.get('msg')}）")
        tsb = by_key.get("tsb")
        if tsb:
            parts.append(f"疲勞狀態值 TSB：{tsb.get('value')}（{tsb.get('msg')}）")
        recovery = by_key.get("recovery")
        if recovery:
            parts.append(f"恢復狀況：{recovery.get('msg')}")

    return "\n".join(parts) if parts else None


def _fetch_wellness_signals() -> Optional[dict]:
    """跨服務呼叫 wellness-dashboard /api/health-check，仿 webhook_server._send_coach_card
    的呼叫模式（X-Access-Token header）。深度分析屬推播當下的附加資料，寧可短逾時就放棄、
    不拖慢 poller 的 60 秒天花板，因此不比照 _send_coach_card 用 50 秒與重試。"""
    coach_api = os.environ.get("WELLNESS_COACH_API", "")
    coach_token = os.environ.get("WELLNESS_COACH_TOKEN", "")
    if not coach_api or not coach_token:
        return None
    r = requests.get(
        f"{coach_api}/api/health-check",
        headers={"X-Access-Token": coach_token},
        timeout=12,
    )
    r.raise_for_status()
    return r.json()


def _fetch_history_comparison(summary: dict, schedule_workout: str):
    """讀近期 training_logs、比對同類課表（schedule_history.compare_with_history）。
    回傳 schedule_history.HistoryComparison 或 None。"""
    import firebase_client as fb
    import schedule_history as sh
    # 100 筆（混所有運動類別）：真實資料驗證過 40 筆太窄，同類跑步課表在一堆
    # 騎車/重訓/瑜珈穿插的近期紀錄裡很快就被擠出視窗，找不到樣本
    recent_logs = fb.get_recent_training_logs(limit=100)
    current = dict(summary)
    current["schedule_workout"] = schedule_workout
    return sh.compare_with_history(current, recent_logs)


def _fetch_coach_logic() -> Optional[dict]:
    import firebase_client as fb
    return fb.get_coach_logic()


def _build_deep_prompt(perf_facts: str, history_facts: Optional[str],
                        phase_facts: Optional[str], body_facts: Optional[str]) -> str:
    def _block(title, facts):
        return f"【{title}】\n{facts if facts else '（無資料）'}"

    return f"""以下是這次訓練的完整背景資料，請根據這些「已經算好的數字與事實」寫課後深度記錄：

{_block("今日表現數據", perf_facts)}

{_block("跟歷史同類課表比較", history_facts)}

{_block("目前訓練階段", phase_facts)}

{_block("身體訊號", body_facts)}

請只回傳一個 JSON 物件，格式如下：
{{
  "today_performance": "今日表現的教練評語",
  "history_comparison": "跟歷史同類課表比較的評語，若上面是「（無資料）」就填「這部分資料不足」",
  "training_phase": "目前所處訓練階段的白話說明，若上面是「（無資料）」就填「這部分資料不足」",
  "body_signals": "身體訊號的白話解讀，若上面是「（無資料）」就填「這部分資料不足」",
  "advice": "根據以上所有可用資訊給一個具體可執行的建議"
}}"""


def _parse_deep_json(text: str) -> dict:
    """把 LLM 回應解析成 dict；格式不對或缺欄位回空 dict（呼叫端逐段 fallback，不整段開天窗）。"""
    if not text:
        return {}
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        import json
        data = json.loads(cleaned)
    except Exception as e:
        print(f"[ai_analyzer] 深度分析 LLM 輸出非合法 JSON，捨棄：{e}")
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_section(llm_text, facts_available: Optional[str], insufficient_msg: str) -> str:
    """組裝單一段落的最終顯示文字：
    - 該段完全沒有底層資料 → 固定顯示「資料不足」訊息（不信任 LLM 是否有照做，程式層保證誠實）
    - 有資料但 LLM 沒生成/生成失敗 → 退回原始事實文字（至少數字看得到，不是空白）
    - 有資料且 LLM 有生成 → 用 LLM 轉述的白話版本
    """
    if not facts_available:
        return insufficient_msg
    if llm_text and isinstance(llm_text, str) and llm_text.strip():
        return strip_markdown(llm_text)
    return facts_available


def analyze_deep(summary: dict, schedule_workout: str = None, weather: dict = None) -> dict:
    """深度分析（第二層 Flex 用）：結構化五段——今日表現／歷史同類課表比較／
    目前所處訓練階段／身體訊號／建議。低頻呼叫（每次新訓練推播時一次），用 Sonnet。

    Returns: dict，keys 固定為 today_performance / history_comparison / training_phase /
             body_signals / advice / generated_at。任一段資料不足會是誠實的中文說明文字，
             不會是空字串（webhook 端可直接塞進 Flex bubble，不必再判斷）。
    """
    perf_facts = build_training_desc(summary, schedule_workout, weather)

    history_cmp = None
    try:
        history_cmp = _fetch_history_comparison(summary, schedule_workout)
    except Exception as e:
        print(f"[ai_analyzer] 深度分析：歷史同類課表比較失敗：{e}")
    history_facts = _format_history_facts(history_cmp)

    coach_logic = None
    try:
        coach_logic = _fetch_coach_logic()
    except Exception as e:
        print(f"[ai_analyzer] 深度分析：讀 coach_logic 失敗：{e}")
    phase_facts = _format_phase_facts(coach_logic)

    wellness = None
    try:
        wellness = _fetch_wellness_signals()
    except Exception as e:
        print(f"[ai_analyzer] 深度分析：wellness health-check 呼叫失敗：{e}")
    body_facts = _format_body_facts(summary.get("cardiac_drift"), wellness)

    llm_out = {}
    c = _get_client()
    if c:
        prompt = _build_deep_prompt(perf_facts, history_facts, phase_facts, body_facts)
        try:
            msg = c.messages.create(
                model=DEEP_MODEL,
                max_tokens=2500,  # 五段完整記錄＋JSON 包裝，1200 曾在真實資料上截斷過
                system=_DEEP_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            if msg.stop_reason == "max_tokens":
                print("[ai_analyzer] 深度分析 LLM 回應被 max_tokens 截斷，內容可能不完整")
            # claude-sonnet-5 可能先吐 thinking block（.text 為 None），真正文字在後面的
            # text block，不能假設 content[0] 就是答案（coach_logic_learner.py 已踩過這雷）
            text = "".join(
                getattr(block, "text", "") or ""
                for block in msg.content
                if getattr(block, "type", None) == "text"
            )
            llm_out = _parse_deep_json(text)
        except Exception as e:
            print(f"[ai_analyzer] 深度分析 LLM 呼叫失敗：{e}")
    else:
        print("[ai_analyzer] 深度分析：無 Anthropic client，各段落退回事實文字")

    return {
        "today_performance": _resolve_section(
            llm_out.get("today_performance"), perf_facts, "這部分資料不足：無法取得今日訓練數據"),
        "history_comparison": _resolve_section(
            llm_out.get("history_comparison"), history_facts,
            "這部分資料不足：找不到同類型的歷史課表可比較"),
        "training_phase": _resolve_section(
            llm_out.get("training_phase"), phase_facts,
            "這部分資料不足：教練邏輯學習系統尚無資料"),
        "body_signals": _resolve_section(
            llm_out.get("body_signals"), body_facts,
            "這部分資料不足：心率飄移或身體負荷資料暫時無法取得"),
        "advice": strip_markdown(llm_out.get("advice")) if llm_out.get("advice") else
                  "這部分資料不足：建議生成失敗，請參考上方數據自行評估",
        "generated_at": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    # 快速測試
    sample = {
        "sport": "Run",
        "date": "2026-04-13",
        "distance_km": 10.5,
        "moving_time": "1:03:00",
        "avg_pace": "6'00\"",
        "avg_hr": 148,
        "max_hr": 165,
        "average_cadence": 85,
        "average_stride": 0.98,
        "icu_training_load": 62,
        "icu_rpe": 6,
        "icu_hr_zone_times": [600, 1200, 1500, 480, 0],
        "role": "standalone",
    }
    result = analyze_training(sample, schedule_workout="10-12k P'530-540/km")
    print(result)
