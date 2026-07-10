"""課表勾稽（三態誠實版）：比對實際訓練 vs 課表，回 (status, detail)。
純函式、無外部依賴，可獨立測試。

status:
  matched   ✅ 完成      —— 達課表範圍
  partial   🟡 部分/超量 —— 有做但組數不符、距離/時間超量或略少
  unmatched ❌ 未達      —— 跑了但明顯不符（間歇<3組、距離/時間遠不足）

設計理由：舊版只做「在場點名」（間歇≥3組、距離≥85%即✅、時間型/無法解析「有跑就算」），
會給假✅（跑超過、間歇做不對結構都蓋章）。三態讓指標誠實，partial 附數字落差。
"""
import re
from typing import NamedTuple, Optional

_INTERVAL_RE = re.compile(r"\d+\s*[x*×]\s*\d+")


def _g(x) -> str:
    return f"{x:g}"


def parse_interval_reps(workout: str) -> int:
    """課表總組數：每個 AxB 區塊取較小數為組數（距離通常 > 組數）。
    「1200*3 + 400*6」→ 3+6=9；「3x1200」→ 3；無法解析回 0。"""
    total = 0
    for a, b in re.findall(r"(\d+)\s*[x*×]\s*(\d+)", workout):
        total += min(int(a), int(b))
    return total


def parse_distance_range(workout: str):
    """回 (min, max) km 或 None。支援「10-12k」「8k」「10K」。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*[kK]", workout)
    if m:
        return float(m.group(1)), float(m.group(2))
    s = re.search(r"(\d+(?:\.\d+)?)\s*[kK]", workout)
    if s:
        v = float(s.group(1))
        return v, v
    return None


def parse_time_range_min(workout: str):
    """回 (min, max) 分鐘 或 None。支援「20-30min」「30min」「40分」。"""
    m = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*(?:min|分)", workout)
    if m:
        return float(m.group(1)), float(m.group(2))
    s = re.search(r"(\d+)\s*(?:min|分)", workout)
    if s:
        v = float(s.group(1))
        return v, v
    return None


def evaluate_match(workout: str, dist_km: float = 0.0, time_sec: int = 0,
                   interval_count: int = 0):
    """回 (status, detail)。detail：matched 為 None；partial/unmatched 為數字落差說明。"""
    workout = workout or ""
    dist_km = dist_km or 0.0
    minutes = (time_sec or 0) / 60.0

    # ① 間歇課表（含 * / x）：比組數
    if _INTERVAL_RE.search(workout):
        if interval_count < 3:
            return "unmatched", f"實際僅 {interval_count} 組間歇，未達課表"
        req = parse_interval_reps(workout)
        if not req:
            return "matched", None            # 課表組數無法解析，有 ≥3 組就算
        if interval_count == req:
            return "matched", None
        return "partial", f"實際 {interval_count} 組 / 課表 {req} 組"

    # ② 距離課表：比範圍
    rng = parse_distance_range(workout)
    if rng:
        lo, hi = rng
        if lo <= dist_km <= hi * 1.05:
            return "matched", None
        if dist_km > hi * 1.05:
            return "partial", f"{_g(round(dist_km, 1))}k / 課表 {_g(lo)}–{_g(hi)}k（超量）"
        if dist_km >= lo * 0.85:
            return "partial", f"{_g(round(dist_km, 1))}k / 課表 {_g(lo)}–{_g(hi)}k（略少）"
        return "unmatched", f"{_g(round(dist_km, 1))}k / 課表 {_g(lo)}–{_g(hi)}k（未達）"

    # ③ 時間課表：比分鐘（須有實際時間才比，否則落到 ④）
    tr = parse_time_range_min(workout)
    if tr and minutes > 0:
        lo, hi = tr
        if lo <= minutes <= hi * 1.05:
            return "matched", None
        if minutes > hi * 1.05:
            return "partial", f"{round(minutes)} 分 / 課表 {_g(lo)}–{_g(hi)} 分（超量）"
        if minutes >= lo * 0.85:
            return "partial", f"{round(minutes)} 分 / 課表 {_g(lo)}–{_g(hi)} 分（略少）"
        return "unmatched", f"{round(minutes)} 分 / 課表 {_g(lo)}–{_g(hi)} 分（未達）"

    # ④ 無法解析（純 FR'/Z2 無數字）：有跑就算完成
    if dist_km > 0 or minutes > 0:
        return "matched", None
    return "unmatched", "查無實際訓練"


# ── 執行達成度評分（#4，偷 Coach Watts execution score）────────────
def _exec_label(score: int) -> str:
    if score >= 100:
        return "完整達成"
    if score >= 85:
        return "接近完成"
    if score >= 70:
        return "部分完成"
    return "未達標"


def execution_score(workout: str, dist_km: float = 0.0, time_sec: int = 0,
                    interval_count: int = 0):
    """課表執行達成度 0–100（量/結構面），回 (score:int, label:str)。純函式。
    間歇比組數、距離/時間比範圍；無法解析（FR'/Z2 純文字）有跑就 100。"""
    workout = workout or ""
    dist_km = dist_km or 0.0
    minutes = (time_sec or 0) / 60.0

    def _ranged(actual: float, lo: float, hi: float) -> int:
        if actual <= 0:
            return 0
        if actual < lo:
            return max(0, round(actual / lo * 100))
        if actual <= hi * 1.05:
            return 100
        over = (actual - hi) / hi  # 超量略扣，提醒沒照課表收
        return max(85, round(100 - min(over, 0.5) * 30))

    if _INTERVAL_RE.search(workout):
        req = parse_interval_reps(workout)
        if not req:
            s = 100 if interval_count >= 3 else round(interval_count / 3 * 100)
        else:
            s = min(100, round(interval_count / req * 100))
        return s, _exec_label(s)

    rng = parse_distance_range(workout)
    if rng:
        s = _ranged(dist_km, *rng)
        return s, _exec_label(s)

    tr = parse_time_range_min(workout)
    if tr and minutes > 0:
        s = _ranged(minutes, *tr)
        return s, _exec_label(s)

    s = 100 if (dist_km > 0 or minutes > 0) else 0
    return s, _exec_label(s)


# ── 配速達標判讀 ──────────────────────────────────────────────────
# 原作者 2026-06-25：AI 把 4'36"（偏慢）誤判成「偏快」。配速數字越大越慢，
# 方向不可外包給小模型，用純函式算定，AI 只轉述（同天氣預算好 AI 轉述的藥方）。
_PACE_RANGE_RE = re.compile(r"(\d{3,4})\s*[-–~]\s*(\d{3,4})\s*/\s*km")
_PACE_SINGLE_RE = re.compile(r"(\d{3,4})\s*/\s*km")
_ACTUAL_PACE_RE = re.compile(r"(\d+)\s*['′:]\s*(\d+)")


class PaceEval(NamedTuple):
    verdict: str        # "faster" | "on_target" | "slower"
    delta_sec: int      # 偏離秒數（on_target 為 0）
    actual_sec: int
    target_lo_sec: int  # 快端（秒較小）
    target_hi_sec: int  # 慢端（秒較大）
    text: str           # 中文判讀句；間歇課表附「均速含恢復」提醒


def _mmss_to_sec(n: int) -> Optional[int]:
    """課表配速數字 mmss → 秒/km（425→4:25=265）。秒位 ≥60 視為非法回 None。"""
    m, s = n // 100, n % 100
    if s >= 60:
        return None
    return m * 60 + s


def _sec_to_pace(sec: int) -> str:
    return f"{sec // 60}'{sec % 60:02d}\""


def _parse_actual_pace_sec(actual_pace) -> Optional[int]:
    """實際均配速字串 m'ss" → 秒/km。無法解析（N/A、None）回 None。"""
    if not actual_pace or not isinstance(actual_pace, str):
        return None
    m = _ACTUAL_PACE_RE.search(actual_pace)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _parse_target_pace_sec(workout: str):
    """從課表解析目標配速 (lo, hi) 秒/km，或 None。
    僅認 '/km' 結尾，避免把距離 10-12k 誤當配速。"""
    w = workout or ""
    m = _PACE_RANGE_RE.search(w)
    if m:
        a, b = _mmss_to_sec(int(m.group(1))), _mmss_to_sec(int(m.group(2)))
        if a is None or b is None:
            return None
        return min(a, b), max(a, b)
    s = _PACE_SINGLE_RE.search(w)
    if s:
        v = _mmss_to_sec(int(s.group(1)))
        return None if v is None else (v, v)
    return None


def pace_str_to_sec(actual_pace) -> Optional[int]:
    """公開版 _parse_actual_pace_sec：實際均配速字串 m'ss" → 秒/km，供其他模組（如
    schedule_history.py 算歷史同類課表配速差異）重用，避免重刻同一個 regex。"""
    return _parse_actual_pace_sec(actual_pace)


def evaluate_pace(actual_pace, workout: str) -> Optional[PaceEval]:
    """比對實際均配速 vs 課表目標配速，回 PaceEval 或 None。

    None 的情況：實際配速無法解析，或課表沒有可解析的目標配速（FR'/Z2/純距離）。
    配速數字越大越慢：actual > 慢端 → 偏慢；actual < 快端 → 偏快。
    間歇課表均速含組間恢復會偏慢，文字附提醒避免再誤導。
    """
    actual_sec = _parse_actual_pace_sec(actual_pace)
    if actual_sec is None:
        return None
    rng = _parse_target_pace_sec(workout)
    if rng is None:
        return None
    lo, hi = rng  # lo=快端（秒小），hi=慢端（秒大）

    target_disp = f"{_sec_to_pace(lo)}–{_sec_to_pace(hi)}/km"
    actual_disp = _sec_to_pace(actual_sec)
    caveat = ("（註：此為全程均速、含組間恢復，間歇工作段通常更快，僅供參考）"
              if _INTERVAL_RE.search(workout or "") else "")

    if actual_sec < lo:
        delta = lo - actual_sec
        text = f"實際均配速 {actual_disp}，比課表目標 {target_disp} 快 {delta} 秒（偏快）{caveat}"
        return PaceEval("faster", delta, actual_sec, lo, hi, text)
    if actual_sec > hi:
        delta = actual_sec - hi
        text = f"實際均配速 {actual_disp}，比課表目標 {target_disp} 慢 {delta} 秒（偏慢未達）{caveat}"
        return PaceEval("slower", delta, actual_sec, lo, hi, text)
    text = f"實際均配速 {actual_disp}，落在課表目標 {target_disp} 區間內（達標）{caveat}"
    return PaceEval("on_target", 0, actual_sec, lo, hi, text)
