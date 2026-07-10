"""
主輪詢腳本：偵測新訓練並推播
執行方式：python poller.py
排程建議：每 30 分鐘執行一次（cron: */30 * * * *）
"""
import os
from dotenv import load_dotenv
load_dotenv()

import intervals_client as ic
import firebase_client as fb
import line_notifier as ln
import flex_builder as fb_flex
import weather_client as wc
import ai_analyzer as ai
from datetime import datetime


def run():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 輪詢開始")

    # Garmin 壓力/Body Battery 每日同步（每台北日只真跑一次，失敗靜默不影響推播）
    try:
        import garmin_wellness_sync
        garmin_wellness_sync.maybe_daily_sync()
    except Exception as e:
        print(f"[poller] garmin 同步略過：{e}")

    # 生病前兆偵測（每台北日判定一次；資料未到齊會自動下輪重試，紅/黃才推播）
    try:
        import illness_watch
        illness_watch.maybe_daily_check()
    except Exception as e:
        print(f"[poller] 生病偵測略過：{e}")

    # 教練訓練邏輯持續學習（coach_history 有新一週才重新學習，避免每輪都打 LLM）
    try:
        import coach_logic_learner
        coach_logic_learner.maybe_relearn()
    except Exception as e:
        print(f"[poller] 教練邏輯學習略過：{e}")

    # 今日環境快照（天氣/AQI/WBGT → _meta/today_env，自帶 60 分鐘節流；
    # wellness 總覽頁環境列讀這份）
    try:
        import env_snapshot
        env_snapshot.maybe_refresh_env()
    except Exception as e:
        print(f"[poller] 環境快照略過：{e}")

    activities = ic.get_recent_activities(days=2)
    if not activities:
        print("無新活動")
        return

    # 依時間排序，最新在前
    activities.sort(key=lambda a: a.get("start_date_local", ""), reverse=True)
    latest = activities[0]
    latest_id = str(latest.get("id"))

    # 對比上次推播的 ID
    last_notified_id = fb.get_last_notified_activity_id()
    if last_notified_id == latest_id:
        print(f"無新活動（最新 ID: {latest_id}）")
        return

    # 找出同一天的所有活動，一起分類推播
    latest_date = (latest.get("start_date_local") or "")[:10]
    same_day = [a for a in activities if (a.get("start_date_local") or "")[:10] == latest_date]

    # 分類：暖身 / 主課表 / 緩跑
    same_day = ic.classify_daily_activities(same_day)

    print(f"當日活動：{len(same_day)} 筆（日期：{latest_date}）")

    # 課表勾稽逐筆於迴圈內處理（帶入各活動 actual_summary 做三態比對）
    for activity in sorted(same_day, key=lambda a: a.get("start_date_local", "")):
        act_id = str(activity.get("id"))

        # 已推播過的跳過
        if fb.is_activity_notified(act_id):
            print(f"  已推播：{act_id}")
            continue

        summary = ic.format_activity_summary(activity)
        print(f"  新活動：{summary['name']} ({summary['sport']}) role={summary.get('role')}")

        # 資料主權：完整原始活動 + streams 落地 Firebase（正本自持，不影響推播主流程）
        try:
            import data_vault
            data_vault.land_activity(activity)
            data_vault.land_streams(act_id)
        except Exception as e:
            print(f"    [vault] 落地失敗：{e}")

        # 天氣（每筆各自抓，時間不同）
        weather = None
        try:
            start_time = activity.get("start_date_local", "")
            latlng = activity.get("start_latlng") or []
            lat = latlng[0] if len(latlng) > 0 else None
            lon = latlng[1] if len(latlng) > 1 else None
            weather = wc.get_weather_at_activity(start_time, lat=lat, lon=lon)
            if weather:
                summary["weather"] = weather
                summary["average_temp"] = weather.get("temp_c")
                print(f"    天氣：{wc.format_weather_str(weather)}")
        except Exception as e:
            print(f"    [weather] 失敗：{e}")

        # 間歇逐組真資料（WORK 段真配速；恢復段站休/緩跑分開）：
        # 讓 AI 與後續分析不再拿「含站休的全場均配速」評間歇課
        if summary.get("sport") == "Run" and summary.get("interval_summary"):
            try:
                idetail = ic.get_interval_detail(act_id)
                if idetail:
                    summary["interval_detail"] = idetail
                    print(f"    間歇：{idetail['n_work']}x{idetail['work_dist_m']}m"
                          f" 均 {idetail['avg_work_pace']}（{idetail.get('recovery_kind') or '無恢復段'}）")
            except Exception as e:
                print(f"    [interval_detail] 失敗：{e}")

        # 暖身/緩跑不勾稽、不做 AI 分析
        role = summary.get("role", "standalone")
        if role in ("main", "standalone"):
            s_status, s_workout, s_detail = _match_schedule_by_date(latest_date, actual_summary=summary)
            print(f"    課表勾稽：{s_status}（課表：{s_workout}）{(' — ' + s_detail) if s_detail else ''}")
        else:
            s_status, s_workout, s_detail = "free", None, None

        # AI 分析（僅主課表或獨立訓練）
        ai_comment = ""
        if role in ("main", "standalone"):
            try:
                ai_comment = ai.analyze_training(summary, schedule_workout=s_workout, weather=weather)
                if ai_comment:
                    print(f"    AI：{ai_comment[:40]}...")
            except Exception as e:
                print(f"    [ai] 失敗：{e}")

        # 心率漂移（cardiac drift）：僅連續有氧跑有意義，間歇/暖身略過
        drift = None
        if summary.get("sport") == "Run" and role in ("main", "standalone"):
            try:
                drift = ic.get_cardiac_drift(act_id)
                if drift is not None:
                    print(f"    心率漂移：{drift:+d} bpm")
            except Exception as e:
                print(f"    [drift] 失敗：{e}")
        summary["cardiac_drift"] = drift

        # Garmin 跑姿（觸地/垂直振幅/垂直比/步幅/呼吸/功率）：intervals 拿不到，
        # 錶同步 Garmin 後這裡順手撈回來落地 Firebase。Garmin 掛了靜默略過。
        if summary.get("sport") == "Run":
            try:
                import garmin_dynamics as gd
                dyn = gd.dynamics_for_activity(latest_date, summary.get("distance_km") or 0)
                if dyn:
                    summary["dynamics"] = dyn
                    print(f"    跑姿：觸地 {dyn.get('gct')}ms · 垂直比 {dyn.get('vratio')}%")
            except Exception as e:
                print(f"    [dynamics] 失敗：{e}")

        summary["ai_comment"] = ai_comment
        summary["schedule_status"] = s_status
        summary["schedule_workout"] = s_workout
        summary["schedule_detail"] = s_detail
        # 執行達成度（#4）：有對應課表才算
        if s_workout and s_status in ("matched", "partial"):
            import schedule_match as _sm, re as _re
            _isr = summary.get("interval_summary") or []
            _is = _isr[0] if isinstance(_isr, list) and _isr else (str(_isr) if _isr else "")
            _m = _re.match(r"(\d+)x", _is)
            _ic = int(_m.group(1)) if _m else 0
            summary["exec_score"], summary["exec_label"] = _sm.execution_score(
                s_workout, dist_km=summary.get("distance_km", 0) or 0,
                time_sec=summary.get("moving_time_sec", 0) or 0, interval_count=_ic)

        # 深度分析（第二層 Flex，Sonnet，低頻）：推播當下就先生成好存進 training_logs，
        # postback 只讀取顯示不現場呼叫 LLM。僅主課表/獨立跑步訓練有（同 ai_comment gating）。
        # 內部已對 Firestore 查詢／跨服務呼叫／LLM 呼叫逐段 try/except，這裡的外層 try/except
        # 只防「整個函式意外炸掉」，不應該發生，但保底別讓深度分析拖垮這筆推播。
        if summary.get("sport") == "Run" and role in ("main", "standalone"):
            try:
                summary["deep_analysis"] = ai.analyze_deep(summary, schedule_workout=s_workout, weather=weather)
                print(f"    深度分析：已生成（{len(summary['deep_analysis'])} 段）")
            except Exception as e:
                print(f"    [deep] 失敗：{e}")

        fb.save_training_log(summary)

        flex = fb_flex.build_flex(summary, s_status, s_workout, ai_comment=ai_comment, schedule_detail=s_detail)
        ln.send_flex(flex)
        print(f"    LINE 推播成功")

        fb.set_activity_notified(act_id)

    # 更新最後推播 ID（以最新活動為準）
    fb.set_last_notified_activity_id(latest_id)


def _match_schedule_by_date(date: str, actual_summary: dict = None):
    """根據日期找對應課表，比對實際訓練，回傳 (status, workout_str, detail)
    無 actual_summary 時 status 為 'free' / 'unmatched'；
    有實際資料時由 schedule_match.evaluate_match 回傳三態 + detail 說明。
    """
    schedule = _select_schedule_for_date(date)
    if not schedule:
        return "free", None, None

    week_range = schedule.get("week_range", "")
    days_data  = schedule.get("days", {})
    matched_day = _find_day_by_date(week_range, date, days_data)

    if not matched_day:
        return "free", None, None

    day_info = days_data[matched_day]
    if day_info.get("is_rest") or not day_info.get("is_for_me"):
        return "free", None, None

    workout = day_info.get("my_workout", "")
    if not workout:
        return "free", None, None

    # 若無實際訓練資料，視為未執行
    if not actual_summary:
        return "unmatched", workout, None

    # ── 三態勾稽：交給 schedule_match（純函式、可獨立測試）────────
    import re
    import schedule_match
    isummary_raw = actual_summary.get("interval_summary") or []
    isummary = (isummary_raw[0] if isinstance(isummary_raw, list) and isummary_raw
                else str(isummary_raw) if isummary_raw else "")
    m = re.match(r"(\d+)x", isummary)
    interval_count = int(m.group(1)) if m else 0

    status, detail = schedule_match.evaluate_match(
        workout,
        dist_km=actual_summary.get("distance_km", 0) or 0,
        time_sec=actual_summary.get("moving_time_sec", 0) or 0,
        interval_count=interval_count,
    )
    return status, workout, detail


def _select_schedule_for_date(date: str):
    """挑出 week_range 涵蓋該日期的那一週課表；找不到才退回最新一筆。
    解決週期交界：教練貼了下週課表後，當天/補推的活動被錯配到下週課表（起算日對不上 → free）。"""
    schedules = fb.get_recent_schedules(limit=8)
    for s in schedules:
        if _week_covers_date(s.get("week_range", ""), date):
            return s
    return schedules[0] if schedules else None


def _week_start(week_range: str):
    """從 week_range（如「2026 06/01-06/07」）解析該週起算日（週一），無法解析回 None。"""
    import re
    from datetime import date as date_cls
    m = re.search(r"(\d{4})\s+(\d{2})/(\d{2})-(\d{2})/(\d{2})", week_range)
    if not m:
        return None
    return date_cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _week_covers_date(week_range: str, date: str) -> bool:
    """該週（起算日起 7 天）是否涵蓋此日期。"""
    from datetime import date as date_cls
    start_date = _week_start(week_range)
    if not start_date:
        return False
    try:
        activity_date = date_cls.fromisoformat(date)
    except ValueError:
        return False
    return 0 <= (activity_date - start_date).days <= 6


def _find_day_by_date(week_range: str, date: str, days_data: dict):
    from datetime import date as date_cls

    start_date = _week_start(week_range)
    if not start_date:
        return None

    try:
        activity_date = date_cls.fromisoformat(date)
    except ValueError:
        return None

    delta = (activity_date - start_date).days
    if 0 <= delta <= 6:
        day_key = f"D{delta + 1}"
        if day_key in days_data:
            return day_key
        # 週末（週六 delta=5 / 週日 delta=6）教練常把課表存成「週末…」中文 key，
        # 而非 D6/D7，導致週末永遠勾不到課表。這裡 fallback 找含「週末」的那格。
        if delta >= 5:
            for key in days_data:
                if "週末" in key:
                    return key

    return None


if __name__ == "__main__":
    run()
