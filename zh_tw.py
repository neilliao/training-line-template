"""
簡體字硬防線：任何要送出 LINE 的文字先過簡轉繁（OpenCC s2twp，含台灣詞彙轉換）。

設計原則：
- 防線失效不能變成炸掉推播 → OpenCC import / 初始化 / 轉換失敗一律 fallback 原樣回
- converter 為 module 層 lazy singleton，不每次呼叫重建
- convert_payload 遞迴走訪 dict/list：dict key 不轉（LINE API 欄位名）、URL 不轉
"""

_converter = None
_converter_failed = False

_URL_PREFIXES = ("http://", "https://")


def _get_converter():
    """Lazy singleton：第一次呼叫才建 OpenCC converter，失敗後不再重試。"""
    global _converter, _converter_failed
    if _converter is not None or _converter_failed:
        return _converter
    try:
        from opencc import OpenCC
        _converter = OpenCC("s2twp")
    except Exception:
        _converter_failed = True
        _converter = None
    return _converter


def to_taiwan(text):
    """簡體轉台灣正體（含詞彙轉換）。None / 非字串原樣回；轉換失敗原樣回。"""
    if not isinstance(text, str):
        return text
    converter = _get_converter()
    if converter is None:
        return text
    try:
        return converter.convert(text)
    except Exception:
        return text


def convert_payload(obj):
    """遞迴走訪 dict/list，把所有字串值過 to_taiwan。

    - dict 的 key 不轉（LINE API 欄位名）
    - http/https 開頭的 URL 字串不轉
    - 其餘型別原樣回
    """
    if isinstance(obj, dict):
        return {key: convert_payload(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [convert_payload(item) for item in obj]
    if isinstance(obj, str):
        if obj.startswith(_URL_PREFIXES):
            return obj
        return to_taiwan(obj)
    return obj
