"""Vercel serverless 入口。

Vercel 會把這支當成 Python serverless function，並以 WSGI 方式服務匯出的 `app`。
所有路由（/webhook、/health、/version…）仍由 webhook_server.py 內的 Flask app 處理；
此檔只負責把專案根目錄加入 import path，讓 webhook_server 及其相依模組可被匯入。
"""
import os
import sys

# 專案根目錄（api/ 的上一層）加入 sys.path，使 `import webhook_server` 及其
# `import firebase_client` 等同層相依模組都能解析。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from webhook_server import app  # noqa: E402  Vercel 以此 WSGI app 服務全部請求
