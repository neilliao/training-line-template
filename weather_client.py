"""
天氣資料客戶端
- 預報：氣象署 F-D0047-061（台北市鄉鎮逐3小時），fallback Open-Meteo
- 歷史：Open-Meteo archive API
"""
import os
import requests
from datetime import datetime, timezone, timedelta

# ── 氣象署 ────────────────────────────────────────────────────
CWA_FORECAST_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-061"

# CWA 天氣代碼 → 顯示碼（對應 _weather_accent 的 WMO-like 分類）
_CWA_CODE_MAP = {
    1: 0, 2: 1, 3: 1,           # 晴、晴時多雲
    4: 2, 5: 2, 6: 2,           # 多雲
    7: 3,                        # 陰
    8: 51, 9: 51, 10: 51,       # 短暫雨
    11: 61, 12: 61, 13: 61,     # 雨
    14: 63, 15: 63,              # 中雨
    16: 65, 17: 65,              # 大雨
    18: 65, 19: 65, 20: 65,     # 豪雨以上
    21: 95, 22: 95, 23: 95,     # 雷雨
    24: 1, 25: 2, 26: 3,        # 晴有霧、多雲有霧、陰有霧
    27: 51, 28: 61, 29: 65,     # 有霧+雨
    30: 95, 31: 95,              # 有霧+雷雨
    32: 1, 33: 2, 34: 3,        # 晴多雲陰（另一組）
    35: 51, 36: 61, 37: 65,
    38: 95, 39: 1, 40: 2,
    41: 3, 42: 61,
}


def _cwa_to_display_code(cwa_code: int) -> int:
    return _CWA_CODE_MAP.get(cwa_code, 3)


def get_daily_forecast_cwa(date_str: str, district: str = "中正區") -> dict:
    """氣象署逐3小時預報 → 彙整成單日摘要"""
    api_key = os.getenv("CWA_API_KEY", "")
    if not api_key:
        return {}

    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        resp = requests.get(CWA_FORECAST_URL, params={
            "Authorization": api_key,
            "locationName":  district,
            "timeFrom": f"{date_str}T00:00:00",
            "timeTo":   f"{next_day}T00:00:00",
        }, timeout=12, verify=False)
        resp.raise_for_status()
        data = resp.json()

        loc      = data["records"]["Locations"][0]["Location"][0]
        elements = {e["ElementName"]: e["Time"] for e in loc.get("WeatherElement", [])}

        def pt_vals(elem_name, value_key):
            """逐點時刻資料（DataTime）"""
            result = []
            for t in elements.get(elem_name, []):
                v = t["ElementValue"][0].get(value_key)
                if v not in (None, "", "-"):
                    result.append((t.get("DataTime", ""), int(v)))
            return result

        def rng_vals(elem_name, value_key):
            """區間資料（StartTime/EndTime）"""
            result = []
            for t in elements.get(elem_name, []):
                v = t["ElementValue"][0].get(value_key)
                if v not in (None, "", "-"):
                    result.append((t.get("StartTime", ""), int(v)))
            return result

        # 氣溫
        temps = [v for _, v in pt_vals("溫度", "Temperature")]
        t_max = max(temps) if temps else None
        t_min = min(temps) if temps else None

        # 體感溫度
        ats = [v for _, v in pt_vals("體感溫度", "ApparentTemperature")]
        at_max = max(ats) if ats else None
        at_min = min(ats) if ats else None

        # 濕度（下午 12-18 點平均）
        rh_all = pt_vals("相對濕度", "RelativeHumidity")
        rh_pm  = [v for t, v in rh_all if "T12:" <= t[11:16] <= "T18:"]
        humidity = round(sum(rh_pm) / len(rh_pm)) if rh_pm else (rh_all[0][1] if rh_all else None)

        # 降雨機率（全天最大）
        pops = [v for _, v in rng_vals("3小時降雨機率", "ProbabilityOfPrecipitation")]
        rain_pct = max(pops) if pops else None

        # 天氣代碼（取白天第一筆）
        cwa_code = 0
        for t in elements.get("天氣現象", []):
            wc = t["ElementValue"][0].get("WeatherCode")
            if wc not in (None, "", "-"):
                try: cwa_code = int(wc); break
                except: pass

        def _comfort(t, h):
            if t is None: return ""
            if t >= 35: return "高溫危險" if (h or 0) >= 70 else "酷熱"
            if t >= 32: return "悶熱"    if (h or 0) >= 70 else "炎熱"
            if t >= 28: return "偏熱"    if (h or 0) >= 75 else "溫熱"
            if t >= 22: return "舒適"
            if t >= 16: return "涼爽"
            if t >= 10: return "偏冷"
            return "寒冷"

        return {
            "code":     _cwa_to_display_code(cwa_code),
            "t_max":    t_max,  "t_min":  t_min,
            "at_max":   at_max, "at_min": at_min,
            "humidity": humidity,
            "precip":   None,
            "rain_pct": rain_pct,
            "comfort":  _comfort(t_max, humidity),
        }
    except Exception as e:
        print(f"[weather_cwa] {date_str} {district} 失敗：{e}")
        return {}


# WMO 天氣代碼對照（https://open-meteo.com/en/docs）
_WMO_MAP = {
    0:  ("晴天", "☀️"),
    1:  ("晴時多雲", "🌤️"),
    2:  ("多雲", "⛅"),
    3:  ("陰天", "☁️"),
    45: ("霧", "🌫️"),
    48: ("霧", "🌫️"),
    51: ("毛毛雨", "🌦️"),
    53: ("毛毛雨", "🌦️"),
    55: ("毛毛雨", "🌦️"),
    61: ("小雨", "🌧️"),
    63: ("中雨", "🌧️"),
    65: ("大雨", "🌧️"),
    71: ("小雪", "❄️"),
    73: ("中雪", "❄️"),
    75: ("大雪", "❄️"),
    80: ("陣雨", "🌦️"),
    81: ("陣雨", "🌦️"),
    82: ("大陣雨", "⛈️"),
    85: ("陣雪", "❄️"),
    86: ("大陣雪", "❄️"),
    95: ("雷雨", "⛈️"),
    96: ("雷雨夾冰雹", "⛈️"),
    99: ("雷雨夾冰雹", "⛈️"),
}

def _wmo_to_condition(code: int) -> str:
    return _WMO_MAP.get(code, ("未知", ""))[0]

def _wmo_to_emoji(code: int) -> str:
    return _WMO_MAP.get(code, ("", "🌡️"))[1]


OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# 若活動沒有 GPS 座標，預設台北
DEFAULT_LAT = 25.0478
DEFAULT_LON = 121.5318


def get_weather_at_activity(
    start_date_local: str,
    lat: float = None,
    lon: float = None,
) -> dict:
    """
    取得活動時的天氣資料

    Args:
        start_date_local: 活動開始時間（本地時間），格式 "2026-04-13T07:30:00"
        lat: 緯度（可選，預設台北）
        lon: 經度（可選，預設台北）

    Returns:
        dict: {
            "temp_c": float,       # 氣溫（°C）
            "humidity": int,       # 相對濕度（%）
            "apparent_temp_c": float, # 體感溫度（°C）
            "wind_kph": float,     # 風速（km/h）
            "precip_mm": float,    # 降水量（mm）
            "source": "open-meteo"
        }
        若失敗回傳 None
    """
    if not start_date_local:
        return None

    lat = lat or DEFAULT_LAT
    lon = lon or DEFAULT_LON

    try:
        # 解析時間，取得日期與小時
        dt = datetime.fromisoformat(start_date_local.replace("Z", ""))
        date_str = dt.strftime("%Y-%m-%d")
        hour = dt.hour

        # 判斷使用歷史 API 或預報 API（今日之前用歷史）
        today = datetime.now().date()
        activity_date = dt.date()

        if activity_date < today:
            url = OPEN_METEO_ARCHIVE_URL
        else:
            url = OPEN_METEO_FORECAST_URL

        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": date_str,
            "end_date": date_str,
            "hourly": "temperature_2m,relativehumidity_2m,apparent_temperature,windspeed_10m,precipitation,weathercode",
            "timezone": "Asia/Taipei",
        }

        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])

        if not times:
            return None

        # 找最接近活動開始時間的整點資料
        target_time = f"{date_str}T{hour:02d}:00"
        idx = 0
        if target_time in times:
            idx = times.index(target_time)
        else:
            # 找最近的時間點
            for i, t in enumerate(times):
                if t >= target_time:
                    idx = i
                    break

        def safe_get(key):
            vals = hourly.get(key, [])
            return vals[idx] if idx < len(vals) else None

        temp = safe_get("temperature_2m")
        humidity = safe_get("relativehumidity_2m")
        apparent = safe_get("apparent_temperature")
        wind = safe_get("windspeed_10m")
        precip = safe_get("precipitation")
        code = safe_get("weathercode")

        if temp is None:
            return None

        return {
            "temp_c": round(temp, 1),
            "humidity": int(humidity) if humidity is not None else None,
            "apparent_temp_c": round(apparent, 1) if apparent is not None else None,
            "wind_kph": round(wind, 1) if wind is not None else None,
            "precip_mm": round(precip, 1) if precip is not None else None,
            "condition": _wmo_to_condition(int(code)) if code is not None else None,
            "condition_emoji": _wmo_to_emoji(int(code)) if code is not None else None,
            "source": "open-meteo",
        }

    except Exception as e:
        print(f"[weather] 查詢失敗：{e}")
        return None


def format_weather_str(weather: dict) -> str:
    """格式化天氣為單行字串，用於 bubble 顯示"""
    if not weather:
        return ""
    temp = weather.get("temp_c")
    humidity = weather.get("humidity")
    apparent = weather.get("apparent_temp_c")
    emoji = weather.get("condition_emoji", "")
    condition = weather.get("condition", "")

    parts = []
    if condition:
        parts.append(f"{emoji} {condition}")
    if temp is not None:
        parts.append(f"{temp}°C")
    if apparent is not None and apparent != temp:
        parts.append(f"體感{apparent}°C")
    if humidity is not None:
        parts.append(f"濕度{humidity}%")
    return "  ".join(parts)


def get_daily_forecast(date_str: str, lat: float = None, lon: float = None, district: str = None) -> dict:
    """優先使用氣象署 API，失敗才 fallback Open-Meteo"""
    # 根據座標決定行政區
    if district is None:
        if lat and abs(lat - 25.0579) < 0.02:
            district = "松山區"
        else:
            district = "中正區"
    result = get_daily_forecast_cwa(date_str, district=district)
    if result:
        return result
    return _get_daily_forecast_openmeteo(date_str, lat=lat, lon=lon)


def _get_daily_forecast_openmeteo(date_str: str, lat: float = None, lon: float = None) -> dict:
    """
    取得單日天氣預報，用於每日課表提醒與課表 Carousel
    Returns: {code, t_max, t_min, at_max, at_min, humidity, precip, rain_pct, comfort}
    """
    import os
    lat = lat or DEFAULT_LAT
    lon = lon or DEFAULT_LON

    def _comfort(t_max, humidity):
        if t_max is None: return ""
        if t_max >= 35: return "高溫危險" if (humidity or 0) >= 70 else "酷熱"
        if t_max >= 32: return "悶熱" if (humidity or 0) >= 70 else "炎熱"
        if t_max >= 28: return "偏熱" if (humidity or 0) >= 75 else "溫熱"
        if t_max >= 22: return "舒適"
        if t_max >= 16: return "涼爽"
        if t_max >= 10: return "偏冷"
        return "寒冷"

    for attempt in range(3):
        try:
            resp = requests.get(OPEN_METEO_FORECAST_URL, params={
                "latitude": lat, "longitude": lon,
                "daily": ",".join([
                    "weathercode",
                    "temperature_2m_max", "temperature_2m_min",
                    "apparent_temperature_max", "apparent_temperature_min",
                    "precipitation_sum", "precipitation_probability_max",
                ]),
                "hourly": "relativehumidity_2m",
                "timezone": "Asia/Taipei",
                "start_date": date_str, "end_date": date_str,
            }, timeout=12)
            resp.raise_for_status()
            break
        except Exception as e:
            if attempt == 2:
                print(f"[weather] 預報失敗（{date_str}）：{e}")
                return {}
            import time as _t; _t.sleep(2)

    data   = resp.json()
    daily  = data.get("daily", {})
    hourly = data.get("hourly", {})

    def dv(key):
        v = daily.get(key, [None])
        return v[0] if v else None

    humidity_vals = hourly.get("relativehumidity_2m") or []
    humidity_pm = [humidity_vals[i] for i in range(13, 16) if i < len(humidity_vals) and humidity_vals[i] is not None]
    humidity = round(sum(humidity_pm) / len(humidity_pm)) if humidity_pm else None

    t_max    = round(dv("temperature_2m_max"))         if dv("temperature_2m_max")         is not None else None
    t_min    = round(dv("temperature_2m_min"))         if dv("temperature_2m_min")         is not None else None
    at_max   = round(dv("apparent_temperature_max"))   if dv("apparent_temperature_max")   is not None else None
    at_min   = round(dv("apparent_temperature_min"))   if dv("apparent_temperature_min")   is not None else None
    precip   = round(dv("precipitation_sum"), 1)       if dv("precipitation_sum")          is not None else None
    rain_pct = int(dv("precipitation_probability_max")) if dv("precipitation_probability_max") is not None else None
    code     = int(dv("weathercode"))                  if dv("weathercode")                is not None else None

    return {
        "code": code,
        "t_max": t_max, "t_min": t_min,
        "at_max": at_max, "at_min": at_min,
        "humidity": humidity,
        "precip": precip,
        "rain_pct": rain_pct,
        "comfort": _comfort(t_max, humidity),
    }


def _comfort(t_max, humidity):
    """氣溫(℃)+濕度(%) → 舒適度標籤。"""
    if t_max is None:
        return ""
    h = humidity or 0
    if t_max >= 35: return "高溫危險" if h >= 70 else "酷熱"
    if t_max >= 32: return "悶熱" if h >= 70 else "炎熱"
    if t_max >= 28: return "偏熱" if h >= 75 else "溫熱"
    if t_max >= 22: return "舒適"
    if t_max >= 16: return "涼爽"
    if t_max >= 10: return "偏冷"
    return "寒冷"


def _outdoor_penalty(at_max, precip, rain_pct, code) -> float:
    """戶外跑步友善度懲罰分（越低越適合跑）：體感熱、雨量、降雨機率、雷雨各加權。
    用來預先排序「戶外較佳日」，避免讓 Haiku 自己做跨日數字比較（會凸槌）。"""
    p = 0.0
    if at_max is not None:
        p += max(0, at_max - 28) * 2      # 體感超過 28°C 每度 +2
    if precip is not None:
        p += precip * 3                    # 雨量 mm 權重最高
    if rain_pct is not None:
        p += (rain_pct / 100) * 5          # 降雨機率
    if code in (95, 96, 99):
        p += 20                            # 雷雨重罰
    return p


def forecast_bundle(lat: float = None, lon: float = None, days: int = 3) -> dict:
    """一次 Open-Meteo 取今日＋未來(days-1)天，供合併教練卡用。

    回 {
      "weather_text": "今 陣雨/體感34°C/降雨100%/20mm；明 …；後天 …"  # 餵 /api/coach 的 AI，
                                                                      # 涵蓋窗供「明日準備/週末擇一」判斷
      "today": {code,emoji,desc,t_max,t_min,at_max,humidity,rain_pct,precip,comfort}  # coach_flex 顯示用
    }
    失敗回 {"weather_text": "", "today": {}}（不阻斷卡片）。
    帶 lat/lon 時，AQI 也會改挑該座標最近的測站。"""
    _explicit_loc = lat is not None and lon is not None
    lat = lat or 25.0579   # 松山（原作者 常用區）
    lon = lon or 121.5673
    try:
        resp = requests.get(OPEN_METEO_FORECAST_URL, params={
            "latitude": lat, "longitude": lon,
            "daily": ",".join([
                "weathercode", "temperature_2m_max", "temperature_2m_min",
                "apparent_temperature_max", "precipitation_probability_max", "precipitation_sum",
            ]),
            "hourly": "relativehumidity_2m",
            "timezone": "Asia/Taipei", "forecast_days": days,
        }, timeout=12)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[weather] forecast_bundle 失敗：{e}")
        # 預報掛掉不連坐 AQI（資料源獨立）
        return _merge_aqi({"weather_text": "", "today": {}},
                          lat if _explicit_loc else None, lon if _explicit_loc else None)

    daily = data.get("daily", {})
    times = daily.get("time", [])

    def col(key, i):
        v = daily.get(key) or []
        return v[i] if i < len(v) else None

    labels = ["今", "明", "後天", "大後天"]
    parts = []
    ranked = []
    for i in range(min(days, len(times))):
        code = col("weathercode", i)
        desc = _wmo_to_condition(int(code)) if code is not None else ""
        at = col("apparent_temperature_max", i)
        pop = col("precipitation_probability_max", i)
        psum = col("precipitation_sum", i)
        label = labels[i] if i < len(labels) else f"+{i}天"
        seg = label
        if desc: seg += f" {desc}"
        if at is not None: seg += f"/體感{round(at)}°C"
        if pop is not None: seg += f"/降雨{pop}%"
        if psum is not None: seg += f"/{psum}mm"
        parts.append(seg)
        ranked.append((label, _outdoor_penalty(at, psum, pop, code)))
    weather_text = "；".join(parts)
    # 預先算好「戶外較佳日」排序塞進摘要，AI 只負責轉述（不自己做跨日數字比較）
    if len(ranked) >= 2:
        order = [lbl for lbl, _ in sorted(ranked, key=lambda x: x[1])]
        weather_text += f"\n〔戶外建議〕適合戶外排序：{' > '.join(order)}（體感低、雨量少者佳；已為你算好，直接採用）"

    today = {}
    if times:
        code = col("weathercode", 0)
        hum_vals = (data.get("hourly", {}).get("relativehumidity_2m") or [])[:24]
        hum_pm = [hum_vals[h] for h in (13, 14, 15) if h < len(hum_vals) and hum_vals[h] is not None]
        humidity = round(sum(hum_pm) / len(hum_pm)) if hum_pm else None
        t_max = col("temperature_2m_max", 0)
        t_min = col("temperature_2m_min", 0)
        at_max = col("apparent_temperature_max", 0)
        today = {
            "code": int(code) if code is not None else None,
            "emoji": _wmo_to_emoji(int(code)) if code is not None else "🌡️",
            "desc": _wmo_to_condition(int(code)) if code is not None else "無資料",
            "t_max": round(t_max) if t_max is not None else None,
            "t_min": round(t_min) if t_min is not None else None,
            "at_max": round(at_max) if at_max is not None else None,
            "humidity": humidity,
            "rain_pct": col("precipitation_probability_max", 0),
            "precip": col("precipitation_sum", 0),
            "comfort": _comfort(round(t_max) if t_max is not None else None, humidity),
        }
        if t_max is not None and humidity is not None:
            w = wbgt_estimate(t_max, humidity)
            risk = wbgt_risk(w)
            today["wbgt"] = w
            today["wbgt_level"] = risk["level"]
            today["wbgt_advice"] = risk["advice"]
            weather_text += f"\n〔熱壓力〕今日約 {w}°C＝{risk['level']}：{risk['advice']}"
    return _merge_aqi({"weather_text": weather_text, "today": today},
                      lat if _explicit_loc else None, lon if _explicit_loc else None)


def _merge_aqi(bundle: dict, lat: float = None, lon: float = None) -> dict:
    """把 AQI 併進天氣 bundle（today 欄位＋weather_text 一行）；沒 key 或失敗不影響原 bundle"""
    air = get_aqi(lat=lat, lon=lon)
    if not air:
        return bundle
    today = bundle.get("today") or {}
    today.update({"aqi": air["aqi"], "aqi_status": air["status"],
                  "aqi_advice": air["aqi_advice"], "aqi_site": air["sitename"]})
    line = (f"〔空氣〕{air['sitename']}站 AQI {air['aqi']}＝"
            f"{air['aqi_level']}：{air['aqi_advice']}")
    text = bundle.get("weather_text") or ""
    bundle["weather_text"] = f"{text}\n{line}" if text else line
    bundle["today"] = today
    return bundle


if __name__ == "__main__":
    # 快速測試：台北 2026-04-13 早上 7 點
    w = get_weather_at_activity("2026-04-13T07:30:00", lat=25.05, lon=121.53)
    print(w)
    if w:
        print(format_weather_str(w))


# ── WBGT 濕球黑球溫度（熱壓力） ──────────────────────────────
# 澳洲氣象局（BoM）簡化式：只需氣溫與相對濕度，假設無風、有日射的戶外情境。
# 對跑步夠準；正式 WBGT 需濕球/黑球溫度計。風險分級採國際賽事慣用門檻。

def wbgt_estimate(temp_c: float, humidity_pct: float) -> float:
    """簡化 WBGT（°C）。e = 水汽壓 hPa"""
    import math
    e = humidity_pct / 100 * 6.105 * math.exp(17.27 * temp_c / (237.7 + temp_c))
    return round(0.567 * temp_c + 0.393 * e + 3.94, 1)


def wbgt_risk(wbgt: float) -> dict:
    """WBGT → 風險等級與訓練建議"""
    if wbgt < 18:
        return {"level": "無風險", "advice": "正常訓練"}
    if wbgt < 23:
        return {"level": "低風險", "advice": "稍微放慢"}
    if wbgt < 28:
        return {"level": "中風險", "advice": "配速降 15-20%、縮短距離"}
    if wbgt < 32:
        return {"level": "高風險", "advice": "改輕鬆慢跑或移到室內，避開日照時段"}
    return {"level": "極高風險", "advice": "建議取消戶外跑，改室內或休息"}


# ── AQI 空氣品質（環境部） ────────────────────────────────────
# data.moenv.gov.tw aqx_p_432（每小時各測站 AQI）。政府憑證缺 SKI，
# 比照 CWA 用 verify=False。需 MOENV_API_KEY（免費申請）。

MOENV_AQI_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_432"


def get_aqi(site: str = "士林", county: str = "臺北市",
            lat: float = None, lon: float = None) -> dict:
    """取即時 AQI。預設士林站（原作者 河濱主場）；帶 lat/lon 時改抓全台挑最近測站。
    失敗回 {}（不阻斷）。"""
    api_key = os.getenv("MOENV_API_KEY", "")
    if not api_key:
        return {}
    try:
        params = {"language": "zh", "api_key": api_key}
        if lat is None or lon is None:
            params["filters"] = f"county,EQ,{county}"
        resp = requests.get(MOENV_AQI_URL, params=params, timeout=15, verify=False)
        resp.raise_for_status()
        recs = resp.json()
        if isinstance(recs, dict):
            recs = recs.get("records", [])
        if lat is not None and lon is not None:
            def dist2(x):
                try:
                    return (float(x["latitude"]) - lat) ** 2 + (float(x["longitude"]) - lon) ** 2
                except (KeyError, TypeError, ValueError):
                    return 9e9
            cands = [x for x in recs if dist2(x) < 9e9]
            rec = min(cands, key=dist2) if cands else None
        else:
            rec = next((x for x in recs if x.get("sitename") == site), None) or (recs[0] if recs else None)
        if not rec:
            return {}
        aqi = int(rec.get("aqi") or 0)
        return {
            "aqi": aqi, "status": rec.get("status"), "pm25": rec.get("pm2.5"),
            "sitename": rec.get("sitename"), "publishtime": rec.get("publishtime"),
            **aqi_risk(aqi),
        }
    except Exception as e:
        print(f"[weather] AQI 失敗：{e}")
        return {}


def aqi_risk(aqi: int) -> dict:
    """AQI → 跑步建議分級"""
    if aqi <= 50:
        return {"aqi_level": "良好", "aqi_advice": "正常訓練"}
    if aqi <= 100:
        return {"aqi_level": "普通", "aqi_advice": "正常訓練；敏感體質留意"}
    if aqi <= 150:
        return {"aqi_level": "對敏感族群不健康", "aqi_advice": "避免高強度，縮短時間"}
    if aqi <= 200:
        return {"aqi_level": "不健康", "aqi_advice": "改室內訓練"}
    return {"aqi_level": "非常不健康", "aqi_advice": "取消戶外訓練"}
