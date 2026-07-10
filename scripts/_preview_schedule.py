# 腳本已移入 scripts/，把專案根目錄加回 import path 才能匯入根目錄模組
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import schedule_parser as sp
import line_notifier as ln
import sys
sys.path.insert(0, ".")
from webhook_server import _build_schedule_flex

sample = """2026 04/13-04/19
D1
Rest

D2
老石、Jessie、小明、麗芬
10-12k P'530-540/km

D3
B 組 小欣、Jessie、小明、麗芬、VV、祖君、Kerry、小蓉包
400*14-16 P'106-108 r75s

D4
小明 Rest

D5
@AII 8k Z2

D6
Rest

D7
週末有氧區訓練
小明 15-18k FR'
"""

parsed = sp.parse_schedule(sample)
flex = _build_schedule_flex(parsed)
ln.send_flex(flex)
print("推播成功")
