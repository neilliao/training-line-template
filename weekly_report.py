"""
週訓練量報告
執行方式：python weekly_report.py
排程建議：每週一早上 08:00（cron: 0 8 * * 1）
"""
import os
from dotenv import load_dotenv
load_dotenv()

import firebase_client as fb
import intervals_client as ic
import line_notifier as ln
import flex_tokens as t
from datetime import datetime, timedelta, date as date_cls

WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]

# 週度深度回顧用模型：低頻高價值，預設 Sonnet；可用 env 覆寫；失敗自動 fallback
DEEP_MODEL = os.getenv("DEEP_ANALYSIS_MODEL", "claude-sonnet-4-6")
FALLBACK_MODEL = "claude-haiku-4-5-20251001"

# Design system：與 v2 網頁同色系（mindflows 色票，見 flex_tokens.py，Bento Grid 風格）
C_NAVY    = t.WOOD       # header 主色
C_BLUE    = t.SKY_DEEP   # 主數據
C_ORANGE  = t.AMBER      # 跑量重點
C_GREEN   = t.GREEN
C_RED     = t.RED
C_MUTED   = t.TEXT_MUTED
C_MAIN    = t.TEXT_MAIN
C_BG      = t.BG_BODY    # 整體底色
C_CARD    = t.BG_CARD    # 卡片白底
C_BORDER  = t.BORDER


def run():
    today = datetime.now()
    # 週日(weekday=6)執行時：本週一到今天即為「上週」
    # 週一(weekday=0)執行時：往前推 7 天取上週
    days_since_monday = today.weekday()  # 0=週一, 6=週日
    if days_since_monday == 6:
        last_monday = today - timedelta(days=6)
    else:
        last_monday = today - timedelta(days=days_since_monday + 7)
    last_sunday = last_monday + timedelta(days=6)
    start = last_monday.strftime("%Y-%m-%d")
    end   = last_sunday.strftime("%Y-%m-%d")
    print(f"週報範圍：{start} ~ {end}")

    activities = fb.get_week_activities(start, end)
    if not activities:
        raw = ic.get_recent_activities(days=8)
        activities = [
            ic.format_activity_summary(a) for a in raw
            if start <= (a.get("start_date_local") or "")[:10] <= end
        ]

    today_str = today.strftime("%Y-%m-%d")
    wellness_data = ic.get_wellness(today_str, today_str)
    wellness_today = wellness_data[0] if wellness_data else None

    # 整週 + 前一週 wellness（恢復軌跡用）
    week_wellness = _gather_week_wellness(start, end)

    schedule = fb.get_latest_schedule()

    # AI 深度週度回顧
    deep_review = ""
    try:
        deep_review = _analyze_week(activities, start, end, wellness_today, schedule, week_wellness)
        if deep_review:
            print(f"深度回顧：{deep_review[:40]}...")
    except Exception as e:
        print(f"[weekly-report] AI 失敗：{e}")

    # flex 卡片放一句 TL;DR headline，深度全文走獨立純文字訊息（讀起來清爽、可長按複製）
    headline = _first_sentence(deep_review) if deep_review else ""
    flex = build_weekly_flex(activities, start, end, wellness_today, schedule, ai_comment=headline)
    ln.send_flex(flex)
    if deep_review:
        ln.send(deep_review)
    print("週報推播完成")

    # 賽事倒數提醒（有賽事才推）
    try:
        import race_flex as rf
        races = fb.get_upcoming_races()
        if races:
            # 只推 90 天內的賽事
            from datetime import date as d_cls
            near_races = [r for r in races
                          if 0 <= (d_cls.fromisoformat(r["date"]) - d_cls.today()).days <= 90]
            if near_races:
                carousel = rf.build_races_carousel(near_races)
                if carousel:
                    ln.send_flex(carousel)
                    print(f"賽事倒數推播：{len(near_races)} 場")
    except Exception as e:
        print(f"[weekly-report] 賽事倒數失敗：{e}")


def _analyze_week(activities, start_str, end_str, wellness=None, schedule=None, week_wellness=None) -> str:
    """產生本週深度回顧：恢復軌跡 + 強度分布 + 逐趟配恢復 + 跑姿效率（Sonnet，失敗 fallback Haiku）"""
    try:
        import ai_analyzer as ai
        import firebase_client as fb
        from datetime import date as d_cls
    except ImportError:
        return ""

    runs = [s for s in activities if s.get("sport") == "Run"]
    total_km = round(sum(s.get("distance_km", 0) for s in runs), 1)
    run_count = len(runs)
    by_date = (week_wellness or {}).get("by_date", {})

    lines = [
        f"週期：{start_str} ~ {end_str}",
        f"跑步：{run_count} 次，共 {total_km} km",
    ]

    # 各次跑步摘要 + 當天恢復狀態配對（看硬課是否踩在差恢復上）
    for s in sorted(runs, key=lambda x: x.get("date", "")):
        pace = s.get("avg_pace", "N/A")
        hr   = s.get("avg_hr", "?")
        load = s.get("icu_training_load") or s.get("trimp") or "?"
        role = s.get("role", "standalone")
        status = s.get("schedule_status", "free")
        tag = {"main": "主課表", "warmup": "暖身", "cooldown": "緩跑"}.get(role, "訓練")
        matched = "已勾稽" if status == "matched" else ("未勾稽" if status == "unmatched" else "")
        cad = s.get("average_cadence")
        cad_str = f" 步頻{int(cad * 2)}spm" if cad else ""
        stride = s.get("average_stride")
        stride_str = f" 步幅{round(stride, 2)}m" if stride else ""
        temp = s.get("average_temp")
        temp_str = f" {round(temp)}°C" if temp is not None else ""
        # 當天恢復
        w = by_date.get(s.get("date"))
        rec = ""
        if w:
            recp = []
            if w.get("hrv") is not None:
                recp.append(f"HRV{round(w['hrv'])}")
            if w.get("sleepSecs"):
                recp.append(f"睡{round(w['sleepSecs'] / 3600, 1)}h")
            if recp:
                rec = f" [當天恢復:{' '.join(recp)}]"
        lines.append(
            f"  {s.get('date','')} {tag} {s.get('distance_km',0)}km 配{pace} HR{hr} 負荷{load}"
            f"{cad_str}{stride_str}{temp_str} {matched}{rec}"
        )

    # 強度分布（各趟 HR 區間時間加總 → 看是否塞太多 Z3 灰色地帶）
    ztot = [0] * 7
    has_zone = False
    for s in runs:
        z = s.get("icu_hr_zone_times")
        if z:
            has_zone = True
            for i, zt in enumerate(z[:7]):
                ztot[i] += (zt or 0)
    if has_zone and sum(ztot) > 0:
        tot = sum(ztot)
        z_low = (ztot[0] + ztot[1]) / tot * 100
        z_mid = ztot[2] / tot * 100
        z_high = sum(ztot[3:]) / tot * 100
        lines.append(f"強度分布：Z1-2 {z_low:.0f}%  Z3 {z_mid:.0f}%  Z4+ {z_high:.0f}%")

    # 恢復軌跡（本週 vs 上週）
    if week_wellness:
        trend = _fmt_wellness_trend(week_wellness)
        if trend:
            lines.append(trend)

    # 今日體能狀態 + 負荷爬升率 + VO2max
    if wellness:
        ctl = wellness.get("ctl")
        atl = wellness.get("atl")
        if ctl and atl:
            tsb = float(ctl) - float(atl)
            lines.append(f"今日體能：CTL {round(float(ctl),1)}  ATL {round(float(atl),1)}  TSB {round(tsb,1)}")
        rr = wellness.get("rampRate")
        if rr is not None:
            lines.append(f"負荷爬升率 rampRate：{round(float(rr),1)}（>5-7 偏陡，受傷風險升高）")
        vo2 = wellness.get("vo2max")
        if vo2:
            lines.append(f"VO2max：{vo2}")

    # 課表執行率
    if schedule:
        total_days, done_days = 0, 0
        for info in schedule.get("days", {}).values():
            if info.get("is_for_me") and not info.get("is_rest"):
                total_days += 1
                if info.get("completed"):
                    done_days += 1
        if total_days > 0:
            lines.append(f"課表執行率：{done_days}/{total_days} 天")

    # 最近賽事
    try:
        races = fb.get_upcoming_races()
        near = [r for r in races if 0 <= (d_cls.fromisoformat(r["date"]) - d_cls.today()).days <= 90]
        if near:
            r = near[0]
            days_left = (d_cls.fromisoformat(r["date"]) - d_cls.today()).days
            lines.append(f"最近賽事：{r['name']} {r.get('distance_km',0)}km，距今 {days_left} 天")
    except Exception:
        pass

    training_desc = "\n".join(lines)

    c = ai._get_client()
    if not c:
        return ""

    system = f"""你是一位帶過馬拉松跑者的耐力教練，每週為跑者（{ai._athlete_name}）做一次深度訓練回顧。對象是長期跑者，懂基本術語。

寫作要求：
- 繁體中文，控制在 650 到 850 字，精煉、同一個重點不要重複講；像真的懂這個跑者的教練在跟他覆盤，不是罐頭評語
- 不使用 Markdown、不使用條列編號（不要「一、二、三」），用自然段落串起來
- 不使用破折號，少用引號
- 每個判斷都扣著實際數字講，不要空泛鼓勵

回顧融進敘事（不要分點列標題），涵蓋：本週訓練量與強度分布是否合理（Z3 灰色地帶過多要點出）；身體恢復軌跡（HRV、睡眠、靜息心率走向，與上週相比）；疲勞與狀態（CTL 體能、ATL 疲勞、TSB 狀態、rampRate 是否過陡）；哪幾趟硬課是踩在差恢復上做的；跑姿效率（用步頻與步幅的關係談，並誠實說明真正的垂直振幅與觸地時間數據目前資料源沒有、要接 Garmin 才看得到）；最後收在下週一個最關鍵的具體調整。"""

    user_msg = f"本週訓練與身體數據如下：\n\n{training_desc}\n\n請做這位跑者的本週深度回顧。"

    def _call(model, max_tokens):
        with c.messages.stream(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            return stream.get_final_message().content[0].text.strip()

    try:
        return _call(DEEP_MODEL, 1400)
    except Exception as e:
        print(f"[weekly-report] 深度模型 {DEEP_MODEL} 失敗，改用 {FALLBACK_MODEL}：{e}")
        try:
            return _call(FALLBACK_MODEL, 1200)
        except Exception as e2:
            print(f"[weekly-report] fallback 也失敗：{e2}")
            return ""


def _gather_week_wellness(start_str, end_str):
    """拉本週 + 前一週 wellness，供恢復軌跡分析。回傳 {this_week, last_week, by_date}"""
    from datetime import date as d_cls, timedelta as td
    try:
        prior_start = (d_cls.fromisoformat(start_str) - td(days=7)).isoformat()
        rows = ic.get_wellness(prior_start, end_str)
    except Exception as e:
        print(f"[weekly-report] wellness 區間抓取失敗：{e}")
        return None
    by_date = {r.get("id"): r for r in rows if r.get("id")}
    this_week = sorted([r for d, r in by_date.items() if start_str <= d <= end_str], key=lambda r: r["id"])
    last_week = sorted([r for d, r in by_date.items() if prior_start <= d < start_str], key=lambda r: r["id"])
    return {"this_week": this_week, "last_week": last_week, "by_date": by_date}


def _fmt_wellness_trend(week_wellness) -> str:
    """把本週恢復數據整理成趨勢描述（含與上週均值對比）"""
    tw = week_wellness.get("this_week", [])
    lw = week_wellness.get("last_week", [])
    if not tw:
        return ""

    def _avg(rows, key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    parts = []
    hrv_vals = [round(r["hrv"]) for r in tw if r.get("hrv") is not None]
    if hrv_vals:
        seg = f"HRV {'→'.join(str(v) for v in hrv_vals)}"
        tw_avg, lw_avg = _avg(tw, "hrv"), _avg(lw, "hrv")
        if tw_avg and lw_avg:
            seg += f"（本週均{round(tw_avg)} vs 上週均{round(lw_avg)}）"
        parts.append(seg)

    sl = [round(r["sleepSecs"] / 3600, 1) for r in tw if r.get("sleepSecs")]
    if sl:
        nights_low = sum(1 for h in sl if h < 6)
        parts.append(f"睡眠時數 {sl}，其中 {nights_low} 晚不足 6h")

    rhr = [round(r["restingHR"]) for r in tw if r.get("restingHR") is not None]
    if rhr:
        seg = f"靜息心率 {'→'.join(str(v) for v in rhr)}"
        tw_avg, lw_avg = _avg(tw, "restingHR"), _avg(lw, "restingHR")
        if tw_avg and lw_avg:
            seg += f"（本週均{round(tw_avg)} vs 上週均{round(lw_avg)}）"
        parts.append(seg)

    return "恢復軌跡（本週逐日）：" + "；".join(parts) if parts else ""


def _first_sentence(text: str) -> str:
    """取深度回顧第一句當作 flex 卡片的 TL;DR headline"""
    if not text:
        return ""
    idx = text.find("。")
    if idx != -1:
        return text[:idx + 1].strip()
    nl = text.find("\n")
    if nl != -1:
        return text[:nl].strip()
    return text[:60].strip()


def build_weekly_flex(summaries, start_str, end_str, wellness=None, schedule=None, ai_comment=""):
    runs       = [s for s in summaries if s.get("sport") == "Run"]
    total_km   = round(sum(s.get("distance_km", 0) for s in runs), 1)
    run_count  = len(runs)
    total_sess = len(summaries)

    total_s = sum(_parse_time(s.get("moving_time", "0:00:00")) for s in summaries)
    h, rem  = divmod(total_s, 3600)
    m       = rem // 60

    # 平均配速（加權）
    avg_pace_str = "—"
    pace_runs = [s for s in runs if s.get("avg_pace") and s["avg_pace"] != "N/A"]
    if pace_runs:
        total_d = sum(s.get("distance_km", 0) for s in pace_runs)
        total_ps = sum(_pace_to_sec(s["avg_pace"]) * s.get("distance_km", 0) for s in pace_runs)
        if total_d > 0:
            avg_s = total_ps / total_d
            avg_pace_str = f"{int(avg_s//60)}'{int(avg_s%60):02d}\""

    # ── Header：深藍底，週期顯示 ──────────────────────────
    header = {
        "type": "box", "layout": "vertical",
        "backgroundColor": C_NAVY, "paddingAll": "16px",
        "contents": [
            {
                "type": "box", "layout": "horizontal", "alignItems": "center",
                "contents": [
                    {
                        "type": "box", "layout": "vertical", "flex": 1,
                        "contents": [
                            {"type": "text", "text": "週訓練報告",
                             "size": "lg", "weight": "bold", "color": "#FFFFFF"},
                            {"type": "text", "text": f"{start_str}  ～  {end_str}",
                             "size": "xxs", "color": "#FFFFFFB3", "margin": "xs"}
                        ]
                    },
                    {
                        "type": "box", "layout": "vertical", "flex": 0,
                        "alignItems": "flex-end",
                        "contents": [
                            {"type": "text", "text": str(total_km),
                             "size": "3xl", "weight": "bold", "color": C_ORANGE},
                            {"type": "text", "text": "km",
                             "size": "xxs", "color": "#FFFFFFB3", "align": "end"}
                        ]
                    }
                ]
            }
        ]
    }

    # ── Body ────────────────────────────────────────────
    body = []

    # Bento 主數據（3欄）
    body.append({
        "type": "box", "layout": "horizontal", "spacing": "sm",
        "contents": [
            _bento("跑步", f"{run_count} 次", C_BLUE),
            _bento("總訓練", f"{total_sess} 次", t.TEXT_MUTED),
            _bento("總時間", f"{h}h{m}m", C_MAIN),
        ]
    })

    # 平均配速（若有）
    if avg_pace_str != "—":
        body.append({
            "type": "box", "layout": "horizontal", "spacing": "sm", "margin": "sm",
            "contents": [
                _bento("平均配速", f"{avg_pace_str}/km", C_BLUE, flex=2),
                _bento("跑量", f"{total_km} km", C_ORANGE, flex=1),
            ]
        })

    # 每日跑步清單
    if runs:
        body.append({"type": "separator", "margin": "lg", "color": C_BORDER})
        body.append({
            "type": "text", "text": "本週跑步紀錄",
            "size": "xxs", "color": C_MUTED, "margin": "md", "weight": "bold"
        })
        for s in sorted(runs, key=lambda x: x.get("date", "")):
            d_str = s.get("date", "")
            try:
                d = date_cls.fromisoformat(d_str)
                day_label = f"{d_str[-5:]} 週{WEEKDAY_ZH[d.weekday()]}"
            except Exception:
                day_label = d_str[-5:]
            dist  = s.get("distance_km", 0)
            pace  = s.get("avg_pace", "—")
            hr    = s.get("avg_hr")
            load  = s.get("icu_training_load") or s.get("trimp")
            role  = s.get("role", "standalone")

            role_tag = ""
            if role == "warmup":
                role_tag = "  暖身"
            elif role == "cooldown":
                role_tag = "  緩跑"

            right_parts = [f"{pace}/km"]
            if hr:
                right_parts.append(f"HR{hr}")
            if load:
                right_parts.append(f"負荷{int(load)}")
            right_str = "  ".join(right_parts)

            body.append({
                "type": "box", "layout": "horizontal",
                "margin": "sm", "alignItems": "center",
                "contents": [
                    # 左側色條
                    {
                        "type": "box", "layout": "vertical",
                        "width": "3px", "height": "32px",
                        "backgroundColor": C_ORANGE if role == "main" or role == "standalone" else C_MUTED,
                        "cornerRadius": "3px",
                        "contents": []
                    },
                    {
                        "type": "box", "layout": "vertical", "flex": 1,
                        "paddingStart": "8px",
                        "contents": [
                            {"type": "text",
                             "text": f"{day_label}{role_tag}",
                             "size": "xxs", "color": C_MUTED},
                            {"type": "text",
                             "text": f"{dist} km  {right_str}",
                             "size": "xs", "color": C_MAIN, "wrap": True}
                        ]
                    }
                ]
            })

    # CTL / ATL / TSB
    if wellness:
        ctl = wellness.get("ctl")
        atl = wellness.get("atl")
        tsb_raw = wellness.get("tsb")
        # intervals.icu wellness 沒有直接的 tsb，用 ctl - atl 估算
        if ctl and atl:
            tsb = tsb_raw if tsb_raw is not None else (float(ctl) - float(atl))
            tsb_color = C_GREEN if tsb >= 0 else C_RED
            tsb_tag   = "🟢 狀態佳" if tsb >= 0 else "🔴 有疲勞"
            body.append({"type": "separator", "margin": "lg", "color": C_BORDER})
            body.append({
                "type": "text", "text": "體能狀態（今日）",
                "size": "xxs", "color": C_MUTED, "margin": "md", "weight": "bold"
            })
            body.append({
                "type": "box", "layout": "horizontal", "spacing": "sm", "margin": "sm",
                "contents": [
                    _bento("體能 CTL", str(round(float(ctl), 1)), C_BLUE),
                    _bento("疲勞 ATL", str(round(float(atl), 1)), C_ORANGE),
                    _bento(tsb_tag, str(round(float(tsb), 1)), tsb_color),
                ]
            })

    # 課表執行摘要
    if schedule:
        completed, missed = [], []
        for day_key, info in schedule.get("days", {}).items():
            if not info.get("is_for_me") or info.get("is_rest"):
                continue
            if info.get("completed"):
                completed.append(day_key)
            else:
                missed.append(day_key)
        if completed or missed:
            body.append({"type": "separator", "margin": "lg", "color": C_BORDER})
            body.append({
                "type": "text", "text": "課表執行",
                "size": "xxs", "color": C_MUTED, "margin": "md", "weight": "bold"
            })
            if completed:
                body.append({"type": "text",
                             "text": f"完成：{', '.join(completed)}",
                             "size": "xs", "color": C_GREEN, "margin": "sm", "wrap": True})
            if missed:
                body.append({"type": "text",
                             "text": f"未記錄：{', '.join(missed)}",
                             "size": "xs", "color": C_ORANGE, "margin": "sm", "wrap": True})

    # AI 週評區塊
    if ai_comment:
        body.append({"type": "separator", "margin": "lg", "color": C_BORDER})
        body.append({
            "type": "text", "text": "AI 週評",
            "size": "xxs", "color": C_MUTED, "margin": "md", "weight": "bold"
        })
        body.append({
            "type": "text", "text": ai_comment,
            "size": "xs", "color": C_MAIN, "wrap": True, "margin": "sm"
        })

    bubble = {
        "type": "bubble", "size": "mega",
        "header": header,
        "body": {
            "type": "box", "layout": "vertical",
            "backgroundColor": C_BG,
            "paddingAll": "14px", "spacing": "sm",
            "contents": body
        },
        "styles": {
            "header": {"backgroundColor": C_NAVY},
            "body":   {"backgroundColor": C_BG}
        }
    }
    return {"type": "flex", "altText": f"週訓練報告 跑量 {total_km} km", "contents": bubble}


def _bento(label, value, color=None, flex=1):
    """Bento 風格小卡：白底、圓角、彩色數值"""
    color = color or t.SKY_DEEP
    return {
        "type": "box", "layout": "vertical", "flex": flex,
        "backgroundColor": C_CARD,
        "cornerRadius": "12px", "paddingAll": "10px",
        "contents": [
            {"type": "text", "text": value, "size": "md",
             "weight": "bold", "color": color, "wrap": True},
            {"type": "text", "text": label, "size": "xxs",
             "color": C_MUTED, "margin": "xs", "wrap": True}
        ]
    }


def _parse_time(time_str: str) -> int:
    parts = time_str.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 0


def _pace_to_sec(pace_str: str) -> float:
    try:
        pace_str = pace_str.replace('"', '').replace("'", ":")
        parts = pace_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return 0


if __name__ == "__main__":
    run()
