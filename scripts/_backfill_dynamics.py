"""一次性：把 Garmin 跑姿（dynamics）補進既有的 Firebase training_logs。

存量補齊，寫入邊界同步由 poller.py 堵上（新活動落地時就帶 dynamics）。
只 update 單一 dynamics 欄位、且只補「還沒有 dynamics」的文件——
不整份 set，避免蓋掉其他欄位（Firestore merge 蓋 backfill 的舊教訓）。

用法：
  DRY_RUN=1 python _backfill_dynamics.py   # 只看會補幾筆，不寫
  python _backfill_dynamics.py             # 實際寫入
"""
# 腳本已移入 scripts/，把專案根目錄加回 import path 才能匯入根目錄模組
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import os
import garmin_dynamics as gd
import firebase_client as fb

DRY_RUN = os.environ.get("DRY_RUN") == "1"
GARMIN_FETCH_LIMIT = 200  # Garmin 活動一次抓的上限（涵蓋約一年份跑步量）


def main():
    garmin_acts = gd.fetch_recent_garmin_runs(limit=GARMIN_FETCH_LIMIT)
    if not garmin_acts:
        print("Garmin 沒抓到活動（token 失效或沒裝 garth），中止。")
        return
    earliest = min((a.get("startTimeLocal") or "9999")[:10] for a in garmin_acts)
    print(f"Garmin 活動 {len(garmin_acts)} 筆（最早 {earliest}）")

    db = fb._init()
    docs = list(db.collection("training_logs").stream())
    print(f"training_logs 共 {len(docs)} 筆")

    stats = {"updated": 0, "already": 0, "no_match": 0, "not_run": 0, "too_old": 0}
    for doc in docs:
        row = doc.to_dict()
        if row.get("sport") != "Run":
            stats["not_run"] += 1
            continue
        # 已有 dynamics 且含最新欄位（tempMin 是 7/9 第二批加的、impactLoadKm 是
        # 7/10 第三批加的）才跳過；舊批次寫入的（缺新欄位）重刷補齊。
        # FORCE=1 全部重刷（修錯誤值用）。
        existing = row.get("dynamics")
        if (existing and "tempMin" in existing and "impactLoadKm" in existing
                and os.environ.get("FORCE") != "1"):
            stats["already"] += 1
            continue
        date_str = (row.get("start_date_local") or row.get("date") or "")[:10]
        if date_str and date_str < earliest:
            stats["too_old"] += 1
            continue
        dyn = gd.dynamics_for_activity(date_str, row.get("distance_km") or 0,
                                       garmin_acts=garmin_acts)
        if not dyn:
            stats["no_match"] += 1
            continue
        if DRY_RUN:
            print(f"  [dry] {doc.id} {date_str} {row.get('distance_km')}km → "
                  f"觸地 {dyn.get('gct')}ms 垂直比 {dyn.get('vratio')}%")
        else:
            doc.reference.update({"dynamics": dyn})
        stats["updated"] += 1

    mode = "dry-run 會補" if DRY_RUN else "已補"
    print(f"{mode} {stats['updated']} 筆；已有 {stats['already']}、無法配對 {stats['no_match']}、"
          f"非跑步 {stats['not_run']}、早於 Garmin 窗口 {stats['too_old']}")


if __name__ == "__main__":
    main()
