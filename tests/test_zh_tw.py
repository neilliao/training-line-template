"""zh_tw 簡體硬防線測試"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import zh_tw
from zh_tw import convert_payload, to_taiwan


def test_simplified_title_converted():
    assert to_taiwan("换两个视角看本週") == "換兩個視角看本週"


def test_taiwan_vocabulary_conversion():
    # s2twp 含台灣詞彙轉換
    assert to_taiwan("软件占用内存") == "軟體佔用記憶體"


def test_traditional_text_unchanged():
    text = "今日課表：輕鬆跑 8k，心率壓 150 以下"
    assert to_taiwan(text) == text


def test_none_and_non_string_safe():
    assert to_taiwan(None) is None
    assert to_taiwan(123) == 123
    assert to_taiwan(4.5) == 4.5
    assert to_taiwan(True) is True


def test_convert_payload_nested_flex():
    payload = {
        "to": "U123",
        "messages": [
            {
                "type": "flex",
                "altText": "换两个视角",
                "contents": {
                    "type": "bubble",
                    "body": {
                        "type": "box",
                        "contents": [
                            {"type": "text", "text": "换个角度分析这周课表"},
                            {"type": "text", "text": "维持轻松跑", "size": "sm"},
                        ],
                    },
                },
            }
        ],
    }
    result = convert_payload(payload)
    assert result["messages"][0]["altText"] == "換兩個視角"
    body = result["messages"][0]["contents"]["body"]
    assert body["contents"][0]["text"] == "換個角度分析這周課表"
    assert body["contents"][1]["text"] == "維持輕鬆跑"


def test_convert_payload_keys_untouched():
    # dict key 是 LINE API 欄位名，不可轉（用一個簡體字 key 驗證）
    payload = {"发": "发"}
    result = convert_payload(payload)
    assert "发" in result
    assert result["发"] == "發"


def test_convert_payload_url_untouched():
    payload = {
        "type": "uri",
        "uri": "https://example.com/发现?q=发",
        "label": "查看发现",
    }
    result = convert_payload(payload)
    assert result["uri"] == "https://example.com/发现?q=发"
    # s2twp 詞彙轉換：查看→檢視
    assert result["label"] == "檢視發現"


def test_convert_payload_mixed_types_safe():
    payload = {"a": None, "b": 42, "c": [1, None, "复盘"], "d": True}
    result = convert_payload(payload)
    assert result["a"] is None
    assert result["b"] == 42
    assert result["c"] == [1, None, "覆盤"]
    assert result["d"] is True


def test_convert_payload_immutable():
    # 不改原物件（immutability）
    payload = {"messages": [{"text": "两个"}]}
    convert_payload(payload)
    assert payload["messages"][0]["text"] == "两个"


def test_opencc_missing_fallback(monkeypatch):
    # OpenCC 缺席時防線靜默失效、原樣回，不炸推播
    monkeypatch.setattr(zh_tw, "_converter", None)
    monkeypatch.setattr(zh_tw, "_converter_failed", True)
    assert to_taiwan("换两个视角") == "换两个视角"
    assert convert_payload({"text": "换两个视角"}) == {"text": "换两个视角"}


def test_converter_init_failure_fallback(monkeypatch):
    # 初始化炸掉 → fallback 原樣回，且只嘗試一次
    monkeypatch.setattr(zh_tw, "_converter", None)
    monkeypatch.setattr(zh_tw, "_converter_failed", False)

    import builtins
    real_import = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if name == "opencc":
            raise ImportError("no opencc")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_import)
    assert to_taiwan("换两个") == "换两个"
    assert zh_tw._converter_failed is True


def test_converter_is_singleton():
    monkeypatch_state = (zh_tw._converter, zh_tw._converter_failed)
    try:
        zh_tw._converter = None
        zh_tw._converter_failed = False
        first = zh_tw._get_converter()
        second = zh_tw._get_converter()
        assert first is second
        assert first is not None
    finally:
        zh_tw._converter, zh_tw._converter_failed = monkeypatch_state
