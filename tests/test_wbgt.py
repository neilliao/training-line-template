import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import weather_client as wc


def test_wbgt_cool_morning():
    # 20°C / 50% 濕度：低風險區
    w = wc.wbgt_estimate(20, 50)
    assert 18 <= w <= 22
    assert wc.wbgt_risk(w)["level"] == "低風險"


def test_wbgt_taiwan_summer_morning():
    # 28°C / 75%：台灣夏天清晨，高風險區
    w = wc.wbgt_estimate(28, 75)
    assert 28 <= w <= 32
    assert wc.wbgt_risk(w)["level"] == "高風險"


def test_wbgt_taiwan_noon_extreme():
    # 33°C / 70%：正午，極高風險
    w = wc.wbgt_estimate(33, 70)
    assert w > 32
    assert wc.wbgt_risk(w)["level"] == "極高風險"


def test_wbgt_winter_no_risk():
    w = wc.wbgt_estimate(14, 60)
    assert wc.wbgt_risk(w)["level"] == "無風險"


def test_aqi_risk_levels():
    assert wc.aqi_risk(42)["aqi_level"] == "良好"
    assert wc.aqi_risk(80)["aqi_level"] == "普通"
    assert wc.aqi_risk(120)["aqi_advice"] == "避免高強度，縮短時間"
    assert wc.aqi_risk(180)["aqi_advice"] == "改室內訓練"
    assert wc.aqi_risk(250)["aqi_advice"] == "取消戶外訓練"


def test_get_aqi_without_key_returns_empty():
    import os
    old = os.environ.pop("MOENV_API_KEY", None)
    try:
        assert wc.get_aqi() == {}
    finally:
        if old:
            os.environ["MOENV_API_KEY"] = old
