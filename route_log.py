#!/usr/bin/env python3
"""route_log.py — 跑步路線距離庫維護(路段模型 v2)

河濱=一維數線,每個地標釘『沿河里程』(起點橋=0,一方向正另一方向負)。
任兩節點距離=里程差,來回×2,多段串接=各段相加。一次來回跑就是在數線上移動。

用法:
  python3 route_log.py --list                       看路線庫(節點里程線 + 自動路段表)
  python3 route_log.py --scan [天數]                列 intervals 最近活動,標 ⚠ 對不上的(預設14天)
  python3 route_log.py --between 起點橋 折返公園  算任兩節點單程/來回距離(可用部分名稱)
  python3 route_log.py --plan 17 [--from 起點橋]   給目標距離,建議折返組合湊到該距離

路線庫: routes.json(同目錄)。節點里程校正請直接編輯 routes.json 的 km 值。
"""
import os
import sys
import json
from datetime import date, timedelta, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROUTES_PATH = os.path.join(HERE, "routes.json")
TOL = 0.4  # 距離比對容差(km)


def _load_env():
    env_path = os.path.join(HERE, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _load_routes():
    with open(ROUTES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _runs(days):
    import intervals_client as ic
    today = date.today()
    acts = ic.get_activities_by_range((today - timedelta(days=days)).isoformat(), today.isoformat())
    runs = [a for a in acts if a.get("type") == "Run"]
    runs.sort(key=lambda a: a.get("start_date_local", ""))
    return runs


def _find_node(name_to_km, key):
    """節點名比對:完全 > 部分包含。回傳實際節點名或 None"""
    if key in name_to_km:
        return key
    cand = [k for k in name_to_km if key in k or k in key]
    return cand[0] if cand else None


def _corridor_legs(c):
    """corridor 內所有節點兩兩單程距離 (name_i, name_j, leg_km)"""
    nodes = c["nodes"]
    out = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            leg = round(abs(nodes[i]["km"] - nodes[j]["km"]), 2)
            if leg >= 0.2:
                out.append((nodes[i]["name"], nodes[j]["name"], leg))
    return out


def match_route(total_km, region, data):
    """回傳距離對得上的跑法清單(空 = 可能新路線)。corridor 任兩節點單程/來回、loop 整數圈、other 單程/來回。"""
    hits = []
    for c in data.get("corridors", []):
        creg = c.get("region")
        if creg and region and creg not in region:
            continue
        for a, b, leg in _corridor_legs(c):
            if abs(total_km - leg) < TOL:
                hits.append(f"{a}↔{b} 單程")
            elif abs(total_km - leg * 2) < TOL:
                hits.append(f"{a}↔{b} 來回")
    for r in data.get("loops", []):
        reg = r.get("region")
        if reg and region and reg not in region:
            continue
        lk = r["loop_km"]
        if lk >= 1.5:
            n = round(total_km / lk)
            if 1 <= n <= 8 and abs(total_km - n * lk) < max(TOL, n * 0.1):
                hits.append(f"{r['name']}×{n}圈")
    for r in data.get("other", []):
        leg = r.get("leg_km")
        if leg:
            if abs(total_km - leg) < TOL:
                hits.append(f"{r['name']} 單程")
            elif abs(total_km - leg * 2) < TOL:
                hits.append(f"{r['name']} 來回")
    return hits


def cmd_list():
    data = _load_routes()
    for c in data.get("corridors", []):
        print(f"\n■ {c['name']}(線性河濱,原點={c.get('origin')})")
        nodes = sorted(c["nodes"], key=lambda n: n["km"])
        print("  里程線(─ 往南 ┃ 0 ┃ 往北 ─):")
        for n in nodes:
            print(f"    {n['km']:+5.1f}k  {n['name']:<14}[{n.get('source', '')}]")
        print("  相鄰路段:")
        for i in range(len(nodes) - 1):
            seg = round(nodes[i + 1]["km"] - nodes[i]["km"], 2)
            print(f"    {nodes[i]['name']} → {nodes[i + 1]['name']}: {seg}k")
    if data.get("loops"):
        print("\n■ 繞圈路線")
        for r in data["loops"]:
            print(f"    {r['name']}: {r['loop_km']}k/圈  [{r.get('region', '')}]")
    if data.get("tracks"):
        print("\n■ 田徑場(間歇,不辨識路線)")
        for r in data["tracks"]:
            print(f"    {r['name']}: {r['loop_km']}k/圈")
    if data.get("other"):
        print("\n■ 其他(未節點化)")
        for r in data["other"]:
            lk = r.get("leg_km")
            print(f"    {r['name']}: 單程{lk}k(來回{lk * 2:.1f}k)")


def cmd_between(a, b):
    data = _load_routes()
    for c in data.get("corridors", []):
        nm = {n["name"]: n["km"] for n in c["nodes"]}
        ka, kb = _find_node(nm, a), _find_node(nm, b)
        if ka and kb:
            leg = abs(nm[ka] - nm[kb])
            print(f"{ka} ↔ {kb}: 單程 {leg:.1f}k / 來回 {leg * 2:.1f}k  ({c['name']})")
            return
    print(f"找不到節點「{a}」或「{b}」,用 --list 看可用節點名。")


def cmd_plan(target, from_node):
    data = _load_routes()
    corridors = data.get("corridors", [])
    if not corridors:
        print("沒有 corridor 可規劃。")
        return
    c = corridors[0]
    nm = {n["name"]: n["km"] for n in c["nodes"]}
    origin = _find_node(nm, from_node) or c.get("origin")
    o = nm.get(origin, 0.0)
    north = [(k, v) for k, v in nm.items() if v > o]
    south = [(k, v) for k, v in nm.items() if v < o]

    cands = []
    # 單向:來回到某節點
    for k, v in nm.items():
        if k == origin:
            continue
        d = round(abs(v - o) * 2, 1)
        cands.append((d, f"{origin} ↔ {k} 來回 = {d}k"))
    # 雙向:北折返 + 南折返
    for kn, vn in north:
        for ks, vs in south:
            d = round((vn - o) * 2 + (o - vs) * 2, 1)
            cands.append((d, f"{origin}→{kn}折返 + →{ks}折返 = {d}k"))

    seen, picks = set(), []
    for d, desc in sorted(cands, key=lambda x: abs(x[0] - target)):
        if desc in seen:
            continue
        seen.add(desc)
        picks.append((d, desc))
        if len(picks) >= 5:
            break
    print(f"\n目標 {target}k(從 {origin} 出發),最接近的跑法:")
    for d, desc in picks:
        print(f"    {desc}  (差 {d - target:+.1f}k)")


def cmd_scan(days):
    data = _load_routes()
    runs = _runs(days)
    print(f"\n近 {days} 天跑步 {len(runs)} 筆(⚠ = 庫裡對不上,可能是新路線/組合):\n")
    print(f"{'日期':<11}{'距離':>7}{'配速':>8}{'心率':>6}  {'區域':<9}比對")
    print("-" * 76)
    for a in runs:
        km = round((a.get("distance") or 0) / 1000, 2)
        region = (a.get("name") or "").replace(" 跑步", "")
        mt = a.get("moving_time") or 0
        pace = f"{int((mt / km) // 60)}'{int((mt / km) % 60):02d}" if km and mt else ""
        hr = a.get("average_heartrate")
        hr_s = f"{hr:.0f}" if isinstance(hr, (int, float)) else "-"
        hits = match_route(km, region, data)
        if not hits:
            tag = "⚠ 可能新路線"
        elif len(hits) == 1:
            tag = hits[0]
        else:
            tag = " / ".join(hits[:2]) + (" …" if len(hits) > 2 else "") + " (多條相近)"
        print(f"{a.get('start_date_local', '')[:10]:<11}{km:>6.2f}k{pace:>8}{hr_s:>6}  {region[:8]:<9}{tag}")


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--scan":
        days = int(args[1]) if len(args) > 1 and args[1].isdigit() else 14
        _load_env()
        cmd_scan(days)
    elif args[0] == "--list":
        cmd_list()
    elif args[0] == "--between" and len(args) >= 3:
        cmd_between(args[1], args[2])
    elif args[0] == "--plan" and len(args) >= 2:
        try:
            target = float(args[1])
        except ValueError:
            print("用法: python3 route_log.py --plan 17 [--from 起點橋]")
            return
        from_node = args[args.index("--from") + 1] if "--from" in args else "起點橋"
        cmd_plan(target, from_node)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
