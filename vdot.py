"""Daniels VDOT 跑力計算（純函式）。

estimate_vdot：Daniels-Gilbert 公式，從一場成績（距離、時間）估 VDOT。
training_paces：從 VDOT 反解各訓練配速。做法是把目標 %VO2max 代回
VO2-速度二次式反解速度（不是網路流傳的 -10.8736/ln(...) 那個壞公式，
那個代入正常 VDOT 會得到負秒數）。

錨點驗證（對 Daniels 官方配速表）：
  VDOT 50 → T 配速 4'15"/km（表值 4'15"）、M 4'30"（表值 4'31"）、I 3'50"（表值 3'55"）
%VO2max 常數：E 66-74% / M 82% / T 88% / I 100% / R 107%
"""
import math

# 各訓練強度對應 %VO2max
PCT_E_LOW, PCT_E_HIGH = 0.66, 0.74
PCT_M, PCT_T, PCT_I, PCT_R = 0.82, 0.88, 1.00, 1.07


def estimate_vdot(distance_km: float, time_min: float) -> float:
    """從一場成績估 VDOT（Daniels-Gilbert）"""
    v = distance_km * 1000 / time_min  # m/min
    pct = (0.8 + 0.1894393 * math.exp(-0.012778 * time_min)
           + 0.2989558 * math.exp(-0.1932605 * time_min))
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v * v
    return round(vo2 / pct, 1)


def _velocity_at(vo2: float) -> float:
    """反解 0.000104 v² + 0.182258 v - (4.60 + vo2) = 0，回 m/min"""
    a, b, c = 0.000104, 0.182258, -(4.60 + vo2)
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def pace_sec_per_km(vdot: float, pct: float) -> int:
    """VDOT × 強度百分比 → 配速（秒/公里）"""
    return round(1000 / _velocity_at(vdot * pct) * 60)


def _fmt(sec: int) -> str:
    return f"{sec // 60}'{sec % 60:02d}\""


def training_paces(vdot: float) -> dict:
    """五種訓練配速（字串，分'秒"/km）"""
    return {
        "E 輕鬆跑": f"{_fmt(pace_sec_per_km(vdot, PCT_E_HIGH))}–{_fmt(pace_sec_per_km(vdot, PCT_E_LOW))}",
        "M 馬拉松配速": _fmt(pace_sec_per_km(vdot, PCT_M)),
        "T 閾值": _fmt(pace_sec_per_km(vdot, PCT_T)),
        "I 間歇": _fmt(pace_sec_per_km(vdot, PCT_I)),
        "R 重複": _fmt(pace_sec_per_km(vdot, PCT_R)),
    }
