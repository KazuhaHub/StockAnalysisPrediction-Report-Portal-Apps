# -*- coding: utf-8 -*-
"""从行情服务拉全市场标的名录，用它算出导入缺口并给出元数据补丁。

为什么不用 akshare 补元数据（fill_meta.py 那套）
----------------------------------------------
1. akshare 只覆盖沪深，北交所（920xxx）整个板块拿不到；
2. 上市日期要拼三个接口，口径还各不一样；
3. 行情服务自己就带 `listed_date / delisted_date / status / industry`，
   而且和日线是同一份 batch（`batch_id` 相同），元数据与行情天然对得上。

产出
----
  catalog.json                全市场名录缓存（可复现，断网重跑同一份）
  pool_gap_panorama.json      缺口清单（含北交所），带 list_date 供 ingest 使用
  meta_patch.json             只含"要填的空"，ingest 后由 apply_meta_patch.py 落库

用法
----
  python3 fetch_catalog.py            # 重新拉名录
  python3 fetch_catalog.py --offline  # 用 catalog.json 重算清单
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
import warnings

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market_data as md  # noqa: E402
import pandas as pd  # noqa: E402

API = os.environ.get("QUOTE_API", "http://47.237.204.217:8000")
CAT = os.path.join(HERE, "catalog.json")
GAP = os.path.join(HERE, "pool_gap_panorama.json")
PATCH = os.path.join(HERE, "meta_patch.json")
PANORAMA = "/opt/daily-tasks/workspace/panorama/data/master_full.parquet"

BOARD = (("920", "北交所"), ("688", "科创板"), ("689", "科创板"), ("300", "创业板"),
         ("301", "创业板"), ("302", "创业板"), ("600", "沪主板"), ("601", "沪主板"),
         ("603", "沪主板"), ("605", "沪主板"), ("000", "深主板"), ("001", "深主板"),
         ("002", "深主板"), ("003", "深主板"))


def board_of(code: str) -> str | None:
    for p, b in BOARD:
        if code.startswith(p):
            return b
    return None


def fetch() -> list[dict]:
    out, off = [], 0
    while True:
        q = urllib.parse.urlencode({"type": "stock", "limit": 1000, "offset": off})
        d = json.load(urllib.request.urlopen(f"{API}/api/v1/instruments?{q}", timeout=120))
        items = d if isinstance(d, list) else (d.get("items") or [])
        if not items:
            break
        out += items
        off += len(items)
        if len(items) < 1000:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()

    if a.offline and os.path.exists(CAT):
        cat = json.load(open(CAT, encoding="utf-8"))
    else:
        cat = fetch()
        json.dump(cat, open(CAT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"名录 {len(cat):,} 只", flush=True)

    info = {}
    for x in cat:
        sym = md.norm_code(x.get("symbol") or x.get("instrument_id"))
        if not sym or not sym.isdigit():
            continue
        info[sym] = {
            "name": x.get("name"),
            "exchange": x.get("exchange"),
            "board": board_of(sym),
            "list_date": (x.get("listed_date") or "")[:10] or None,
            "delist_date": (x.get("delisted_date") or "")[:10] or None,
            "status": "delisted" if x.get("status") not in (None, "active") else None,
            "industry": x.get("industry"),
        }

    have = set(md.codes())
    if os.path.exists(PANORAMA):
        pf = pd.read_parquet(PANORAMA)
        uni = sorted({md.norm_code(s) for s in pf["symbol"].astype(str)})
    else:
        uni = sorted(info)
    gap = [c for c in uni if c not in have and c in info]

    by_board: dict[str, int] = {}
    for c in gap:
        by_board[info[c]["board"] or "?"] = by_board.get(info[c]["board"] or "?", 0) + 1
    print("缺口", len(gap), by_board, flush=True)

    batches: dict[str, list] = {}
    for c in gap:
        b = info[c]["board"] or "?"
        batches.setdefault(f"E_{b}", []).append(
            {"code": c, "name": info[c]["name"], "list_date": info[c]["list_date"],
             "delist_date": info[c]["delist_date"], "status": "alive"})
    json.dump({"generated": "auto", "source": f"{API}/api/v1/instruments",
               "n_universe": len(uni), "batches": batches},
              open(GAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 元数据补丁：只补空，不覆盖既有值；北交所的 board 库里根本没有，也算"空"
    meta = json.load(open(os.path.join(HERE, "meta.json"), encoding="utf-8"))["stocks"]
    patch = {}
    for c in uni:
        if c not in info:
            continue
        cur = meta.get(c) or {}
        add = {}
        for k_src, k_dst in (("name", "name"), ("board", "board"), ("list_date", "list_date"),
                             ("delist_date", "delist_date")):
            if not cur.get(k_dst) and info[c].get(k_src):
                add[k_dst] = info[c][k_src]
        if cur.get("status") != "delisted" and info[c].get("status") == "delisted":
            add["status"] = "delisted"
        if add:
            patch[c] = add
    json.dump(patch, open(PATCH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"元数据补丁 {len(patch)} 只 → meta_patch.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
