"""Garmin garth token 自動續期（本機 launchd 定時跑，不部署到 Vercel）。

背景（2026-07-10）：garth 的 oauth2 短效權杖約 24 小時到期，到期後拿 oauth1
長效權杖去換新的，但這個 exchange 請求會被 Garmin 的 Cloudflare 自動化防護
以 TLS 指紋攔下（403）。解法＝簽名照用 requests_oauthlib、實際送出改用
curl_cffi 偽裝 chrome 指紋，實測放行。

流程：resume ~/.garth-training-line → 快到期就手動 exchange（curl_cffi）→ 存回本機
→ 把整份 token（garth dumps）寫進 Firestore `_meta/garth_token`，線上兩個
Vercel 服務（wellness /api/run-dynamics、training-line garmin 同步）冷啟時
從 Firestore 讀最新 token，不再依賴部署時凍結的 GARTH_TOKEN env。

換發連續失敗 → LINE 通知 原作者 走手動 ticket 流程（見 memory
reference_garmin_auth_method）。

用法：
  python garth_refresh.py            # 快到期（<12h）才換發
  python garth_refresh.py --force    # 立刻換發
需要 garth + curl_cffi + requests_oauthlib（launchd 用專屬 venv 跑）。
"""
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

TOKEN_DIR = os.path.expanduser("~/.garth-training-line")
REFRESH_BEFORE_SEC = 12 * 3600  # 剩不到 12 小時就換發
EXCHANGE_RETRIES = 3
FIRESTORE_DOC = "garth_token"  # _meta/garth_token


def exchange_via_curl_cffi(client):
    """手動 oauth1→oauth2 exchange：oauthlib 簽名 + curl_cffi chrome 指紋送出。
    成功回 True 並把新 oauth2 設回 client。"""
    import requests as real_requests
    from curl_cffi import requests as curl_requests
    from garth.auth_tokens import OAuth2Token
    from garth.sso import OAUTH_CONSUMER_URL, set_expirations
    from requests_oauthlib import OAuth1

    o1 = client.oauth1_token
    consumer = real_requests.get(OAUTH_CONSUMER_URL, timeout=15).json()
    url = f"https://connectapi.{client.domain}/oauth-service/oauth/exchange/user/2.0"
    data = {"audience": "GARMIN_CONNECT_MOBILE_ANDROID_DI"}
    auth = OAuth1(consumer["consumer_key"], consumer["consumer_secret"],
                  o1.oauth_token, o1.oauth_token_secret)
    signed = real_requests.Request("POST", url, data=data, auth=auth).prepare()
    headers = {
        "Authorization": signed.headers["Authorization"],
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "com.garmin.android.apps.connectmobile",
    }
    r = curl_requests.post(url, headers=headers, data=data,
                           impersonate="chrome", timeout=30)
    if r.status_code != 200:
        print(f"[garth-refresh] exchange HTTP {r.status_code}: {r.text[:200]}")
        return False
    client.oauth2_token = OAuth2Token(**set_expirations(r.json()))
    return True


def push_token_to_firestore(dumps_b64: str):
    """把 token 寫進 Firestore _meta/garth_token，線上服務冷啟時讀這裡。"""
    import firebase_client as fb
    db = fb._init()
    from datetime import datetime, timezone
    db.collection("_meta").document(FIRESTORE_DOC).set({
        "token": dumps_b64,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def notify_failure():
    """換發失敗 → LINE 通知 原作者 手動走 ticket 流程（失敗不 raise，別讓通知
    問題蓋掉原始錯誤）。"""
    try:
        import line_notifier as ln
        ln.send(
            "Garmin token 自動換發失敗，跑姿/壓力資料快斷線了。\n"
            "需要手動更新：瀏覽器登入 Garmin SSO 拿 ticket 貼給 Claude"
            "（作法見 memory garmin-auth-token-method）。"
        )
    except Exception as e:
        print(f"[garth-refresh] LINE 通知也失敗：{e}")


def main(force: bool = False) -> int:
    import garth
    garth.resume(TOKEN_DIR)
    client = garth.client
    remaining = client.oauth2_token.expires_at - int(time.time())
    print(f"[garth-refresh] oauth2 剩 {remaining / 3600:.1f} 小時")
    if not force and remaining > REFRESH_BEFORE_SEC:
        print("[garth-refresh] 還早，不換發")
        return 0

    for attempt in range(EXCHANGE_RETRIES):
        if exchange_via_curl_cffi(client):
            garth.save(TOKEN_DIR)
            push_token_to_firestore(client.dumps())
            print(f"[garth-refresh] 換發成功，新效期至 "
                  f"{client.oauth2_token.expires_at}（已存本機＋Firestore）")
            return 0
        if attempt < EXCHANGE_RETRIES - 1:
            time.sleep(15)

    print("[garth-refresh] 連續換發失敗")
    notify_failure()
    return 1


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))
