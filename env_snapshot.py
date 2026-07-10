"""今日跑步環境快照 → Firestore `_meta/today_env`。

wellness 儀表板總覽頁的環境列（天氣/AQI/WBGT）讀這份快照（原作者 2026-07-10：
總覽副標不要寫「全馬賽後第 N 天」，要寫當地天氣、AQI 等環境）。

設計：poller 每 5 分鐘被打一次，這裡自帶節流——快照未滿 REFRESH_MIN 分鐘
不重抓（Open-Meteo + AQI 兩個外部 API，沒必要每 5 分鐘打）。失敗靜默，
留舊快照（wellness 端會看 updated_at 判斷新鮮度）。
"""
import os
from datetime import datetime, timezone, timedelta

TPE = timezone(timedelta(hours=8))
REFRESH_MIN = 60  # 快照有效分鐘數，過了才重抓
META_DOC = "today_env"


def should_refresh(stored: dict, now_utc: datetime) -> bool:
    """純函式：快照缺、壞、或超過 REFRESH_MIN 分鐘 → 該重抓。"""
    if not stored or not stored.get("updated_at"):
        return True
    try:
        ts = datetime.fromisoformat(stored["updated_at"])
    except (ValueError, TypeError):
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now_utc - ts) >= timedelta(minutes=REFRESH_MIN)


def maybe_refresh_env() -> bool:
    """poller 每輪呼叫；真的重抓才回 True。任何失敗不 raise（不影響推播主流程）。"""
    try:
        import firebase_client as fb
        db = fb._init()
        ref = db.collection("_meta").document(META_DOC)
        snap = ref.get()
        stored = snap.to_dict() if snap.exists else None
        if not should_refresh(stored, datetime.now(timezone.utc)):
            return False

        import weather_client as wc
        bundle = wc.forecast_bundle()
        today = bundle.get("today") or {}
        if not today:
            return False  # 天氣源掛了就留舊快照，不寫空的蓋掉
        ref.set({
            "today": today,  # 含 t_max/humidity/rain_pct/aqi/wbgt 等，整包存前向相容
            "date": datetime.now(TPE).date().isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        print("[env] 環境快照已更新")
        return True
    except Exception as e:
        print(f"[env] 快照略過：{e}")
        return False
