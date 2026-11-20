# -*- coding: utf-8 -*-
"""把 fetch_catalog.py 的元数据补丁落进 meta.json（只填空，冲突只报不改）。

为什么单独一步
--------------
`expand_run.py --stage ingest` 只写 name/first/last/n_bars，`board`/`list_date`
它从 pool_gap.json 的 A/C 批里取——那两批是 2026-11-08 的老清单，新补的票不在里面。
不补这一步的后果：`filter_listing_age` 会把缺 list_date 的票整只剔掉，
补了行情等于白补（2026-11-14 实测缺 252 只）。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market_data as md  # noqa: E402

PATCH = os.path.join(HERE, "meta_patch.json")
BACKUP_DIR = os.path.join(HERE, "backup")


def main() -> int:
    patch = json.load(open(PATCH, encoding="utf-8"))
    meta = md._read_meta()
    st = meta.setdefault("stocks", {})
    filled, conflict = 0, []
    for code, add in patch.items():
        cur = st.get(code)
        if cur is None:                      # 还没入库的票，等下一轮 ingest
            continue
        hit = False
        for k, v in add.items():
            if not cur.get(k) and v:
                cur[k] = v
                hit = True
        if hit:
            filled += 1
        else:
            for k, v in add.items():
                if cur.get(k) and v and str(cur.get(k))[:10] != str(v)[:10]:
                    conflict.append((code, k, cur.get(k), v))
    # 写前备份：_write_meta 是原子替换（tmp→replace），本身不留快照。
    # 补丁是「只填空」的增量改动，但没有回滚点在故障排查时很被动，这里补一道护栏。
    # 仅在真的填补了内容时备份，避免空补丁每轮刷出一个 1.7MB 文件。
    if filled:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        bak = os.path.join(BACKUP_DIR,
                           f"meta-before-patch-{dt.datetime.now():%Y%m%d-%H%M%S}.json")
        shutil.copy2(md.META, bak)
        print(f"写前备份 {bak}")
    md._write_meta(meta)
    n_nold = sum(1 for v in st.values() if not v.get("list_date"))
    n_nobd = sum(1 for v in st.values() if not v.get("board"))
    n_nosw = sum(1 for v in st.values() if not v.get("sw1"))
    print(f"填补 {filled} 只 ｜ 仍缺 list_date {n_nold} 只、board {n_nobd} 只、sw1 {n_nosw} 只")
    if conflict:
        print(f"冲突 {len(conflict)} 项（未覆盖，仅报告）：")
        for c in conflict[:10]:
            print("  ", c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
