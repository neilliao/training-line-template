"""歷史同類課表比較：純函式，供 ai_analyzer.analyze_deep() 組裝深度分析用。
無外部依賴（不碰 Firestore、不呼叫 LLM），可獨立測試。

同類判斷刻意保持簡單（原作者 2026-07-10 拍板：別自創複雜分類器）：
- 間歇課看「課表文字裡出現的間歇距離集合」是否相同（例如都含 1200m/400m 反覆＝同類，
  不比配速級距或組數，配速/組數差異本身就是「同類課表裡的差異」，交給後面的數字比較）
- 純距離課看「距離下限」落在哪個 2km 一桶的區間，同桶＝同類
- 兩者都解析不出結構（純 FR'/Z2 無數字的自由訓練文字）回 None，不強行比對——
  沒有結構就沒有「同類」可言，比了也是雜訊
"""
import re
from typing import NamedTuple, Optional

import schedule_match as sm

_INTERVAL_DIST_RE = re.compile(r"(\d{3,4})\s*[*×xX]\s*\d+")
DEFAULT_MAX_SAMPLES = 5
_DIST_BUCKET_KM = 2  # 距離課表分桶寬度（純函式，非魔法數：每 2km 視為同一類距離課）


def workout_signature(workout: Optional[str]) -> Optional[str]:
    """課表文字 → 分類 key。解析不出結構回 None（不強行比對同類）。"""
    if not workout:
        return None
    dists = sorted(set(int(m.group(1)) for m in _INTERVAL_DIST_RE.finditer(workout)))
    if dists:
        return "interval:" + ",".join(str(d) for d in dists)
    rng = sm.parse_distance_range(workout)
    if rng:
        lo, _ = rng
        bucket = int(lo // _DIST_BUCKET_KM) * _DIST_BUCKET_KM
        return f"distance:{bucket}-{bucket + _DIST_BUCKET_KM}"
    return None


class HistoryComparison(NamedTuple):
    matched_count: int
    pace_delta_sec: Optional[int]   # 負值＝比歷史平均快；正值＝較慢；None＝配速資料不足
    hr_delta_bpm: Optional[float]   # 負值＝比歷史平均低；正值＝較高；None＝心率資料不足
    pace_text: str
    hr_text: str
    sample_dates: list


def _avg(vals: list) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def compare_with_history(current: dict, history: list,
                          max_samples: int = DEFAULT_MAX_SAMPLES) -> Optional[HistoryComparison]:
    """把本次訓練跟「同類型」的近期歷史訓練比較配速與心率。

    current：本次訓練 summary dict（需含 schedule_workout / avg_pace / avg_hr / id）。
    history：候選歷史訓練列表（training_logs doc，已按日期新到舊排序；不要求預先過濾，
             這裡自己篩 sport=Run、排除自己、取同類前 max_samples 筆）。
    回傳 None：本次課表無法分類（無結構文字，或找不到任何同類歷史樣本）。
    """
    sig = workout_signature(current.get("schedule_workout"))
    if not sig:
        return None

    current_id = str(current.get("id") or "")
    same_type = []
    for h in history:
        if h.get("sport") != "Run":
            continue
        if current_id and str(h.get("id") or "") == current_id:
            continue
        if workout_signature(h.get("schedule_workout")) != sig:
            continue
        same_type.append(h)
        if len(same_type) >= max_samples:
            break

    if not same_type:
        return None

    cur_pace_sec = sm.pace_str_to_sec(current.get("avg_pace"))
    hist_paces = [sm.pace_str_to_sec(h.get("avg_pace")) for h in same_type]
    hist_paces = [p for p in hist_paces if p is not None]
    pace_delta = None
    pace_text = "配速資料不足，無法比較"
    if cur_pace_sec is not None and hist_paces:
        avg_hist_pace = _avg(hist_paces)
        pace_delta = round(cur_pace_sec - avg_hist_pace)
        if pace_delta == 0:
            pace_text = f"這次均配速跟近 {len(hist_paces)} 次同類課表平均打平"
        else:
            direction = "快" if pace_delta < 0 else "慢"
            pace_text = f"這次均配速比近 {len(hist_paces)} 次同類課表平均{direction} {abs(pace_delta)} 秒"

    cur_hr = current.get("avg_hr")
    hist_hrs = [h.get("avg_hr") for h in same_type if h.get("avg_hr")]
    hr_delta = None
    hr_text = "心率資料不足，無法比較"
    if cur_hr and hist_hrs:
        avg_hist_hr = _avg(hist_hrs)
        hr_delta = round(cur_hr - avg_hist_hr, 1)
        if hr_delta == 0:
            hr_text = f"心率跟近 {len(hist_hrs)} 次同類課表平均持平"
        else:
            direction = "低" if hr_delta < 0 else "高"
            hr_text = f"心率比近 {len(hist_hrs)} 次同類課表平均{direction} {abs(hr_delta):g} bpm"

    return HistoryComparison(
        matched_count=len(same_type),
        pace_delta_sec=pace_delta,
        hr_delta_bpm=hr_delta,
        pace_text=pace_text,
        hr_text=hr_text,
        sample_dates=[h.get("date") for h in same_type if h.get("date")],
    )
