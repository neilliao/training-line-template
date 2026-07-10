"""每日 06:00 教練卡推播（合併版：課表 × 天氣 × 身體數據）。

排程：GitHub Actions daily_reminder.yml，每天 06:00 Asia/Taipei。
合併後與「今天」「教練」指令同源——共用 webhook_server._send_coach_card（單一卡片定義）。
舊的 _build_reminder_flex / _build_ai_section / 微觀 AI 已退役（建議改由 /api/coach 天氣感知產出）。
"""
import re
from datetime import date

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _parse_base_date(week_range: str):
    """從 week_range 字串（'2026 04/13-04/19'）解析 D1 的日期。"""
    m = re.search(r"(\d{4})\s+(\d{2})/(\d{2})", week_range)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
    return None


def _find_today_key(week_range: str, days: dict) -> str:
    """找今天對應的 D1-D7 key；週六/週日統一找含「週末」的課表 key。
    （仍供 webhook /daily-remind?debug 與 /debug-remind 使用。）"""
    base = _parse_base_date(week_range)
    if not base:
        return ""
    today = date.today()
    diff = (today - base).days  # 0=D1, 1=D2, ...
    if not (0 <= diff <= 6):
        return ""
    if diff in (5, 6):  # 週末
        for k in days:
            if "週末" in k:
                return k
        return f"D{diff + 1}"
    return f"D{diff + 1}"


def main():
    """06:00 推今日教練合併卡。cron 無 reply_token → 直接 push。"""
    print(f"[reminder] 執行每日教練卡，日期：{date.today()}")
    from webhook_server import _send_coach_card
    # retries=1：這條路徑跑在 GitHub Actions（job timeout 3 分鐘），不受 Vercel
    # 60s 函式時限綁住，可以多試一次撐過冷啟動（見 _send_coach_card 內註解）
    _send_coach_card(retries=1)  # 抓天氣 → /api/coach（帶天氣）→ coach_flex 合併卡 → push
    print("[reminder] 推播完成")


if __name__ == "__main__":
    main()
