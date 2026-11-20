#!/usr/bin/env python3
"""补回被误删的 2014 年历史（2014-06-03 ~ 2014-12-31）。

背景：2026-11-08 09:18 一次 `add` 把 `bars/2014.parquet` 整分区顶掉，
968 只原库票的 2014 年数据（138,975 根 bar）静默消失。meta 里 n_bars 仍是
3023，磁盘上只有 2877，`md.verify()` 报「meta 对不上的票 1201」。

两条硬约束：

1. **成交量口径先验一遍再落盘。** 实测 stock-server 对这个窗口返回的是"随价格
   同步复权"的量（v×c ≈ amt，amt/(v×100×c) ≈ 0.01），与库里 ss_cache 的
   2015+ 行一致，不需要换算。但别的源/别的字段组合会返回"手"（比值 ≈1）。
   判据就一条：比值 > 0.3 说明 amt = v×100×c，量是手，乘 100 归一。
   不做这一步的后果是同一条序列里夹着两种单位，`norm_volume_unit` 按整条取
   中位数，少数派那一段会被静默留在 1/100 上。
2. **ingest 用 keep="first"，让磁盘上已有的行优先。** 补的是缺口，不是覆盖。

  python3 repair_2014.py --stage pull      # 只新建 pull_cache/rep_*.parquet，可后台
  python3 repair_2014.py --stage ingest    # 原子替换分区，需前台审批
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CACHE = os.path.join(HERE, "pull_cache")
LIST = os.path.join(HERE, "repair_2014.json")
PENDING = os.path.join(HERE, "pending_repair2014.txt")
START, END = "2014-06-03", "2014-12-31"
_tls = threading.local()


def _cli(timeout: int):
    import market_data as md
    s = getattr(_tls, "cli", None)
    if s is None:
        s = md.StockServer(timeout=timeout)
        _tls.cli = s
    return s


def stage_pull(a) -> int:
    import numpy as np
    import pandas as pd
    import market_data as md

    codes = json.load(open(LIST, encoding="utf-8"))["codes"]
    print(f"待补 {len(codes)} 只 ｜ 窗口 {START} ~ {END}", flush=True)
    if a.dry_run or not codes:
        return 0
    os.makedirs(CACHE, exist_ok=True)
    md._ping()

    base = 0
    ex = glob.glob(os.path.join(CACHE, "rep_*.parquet"))
    if ex:
        base = max(int(os.path.basename(p)[4:8]) for p in ex) + 1
        print(f"  已有 {len(ex)} 个缓存，从 rep_{base:04d} 起编号")

    t0 = dt.datetime.now()
    ok_all, fails = 0, []
    for i in range(0, len(codes), a.chunk):
        part = codes[i:i + a.chunk]
        rows, fail = [], []
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            futs = {pool.submit(lambda c: _cli(a.timeout).daily_hfq(c, START, END, retries=1), c): c
                    for c in part}
            for fu in as_completed(futs):
                code = futs[fu]
                try:
                    r = fu.result()
                    bars = r.get("bars") or []
                    if not bars:
                        fail.append({"code": code, "err": "返回 0 根 bar"})
                        continue
                    # ---- 单位归一：手 → 股
                    v = np.array([float(b.get("v") or 0) for b in bars])
                    amt = np.array([float(b.get("amt") or 0) for b in bars])
                    c_ = np.array([float(b.get("c") or 0) for b in bars])
                    with np.errstate(invalid="ignore", divide="ignore"):
                        ratio = np.nanmedian(amt / (v * 100.0 * c_))
                    k = 100.0 if (np.isfinite(ratio) and ratio > 0.3) else 1.0
                    for b in bars:
                        rows.append((code, str(b["d"])[:10],
                                     float(b.get("o") or 0), float(b.get("h") or 0),
                                     float(b.get("l") or 0), float(b.get("c") or 0),
                                     float(b.get("v") or 0) * k,
                                     float(b.get("amt") or 0),
                                     float(b.get("f") or 0), int(b.get("trd") or 1)))
                except Exception as e:                              # noqa: BLE001
                    fail.append({"code": code, "err": repr(e)[:110]})
        if rows:
            df = pd.DataFrame(rows, columns=md.ORDER)
            out = os.path.join(CACHE, f"rep_{base + i // a.chunk:04d}.parquet")
            df.to_parquet(out + ".tmp", index=False, compression="zstd")
            os.replace(out + ".tmp", out)
        ok_all += len(part) - len(fail)
        fails += fail
        sec = (dt.datetime.now() - t0).total_seconds()
        print(f"  [{i // a.chunk + 1:>3}] {i + len(part):>4}/{len(codes)}  "
              f"ok {len(part) - len(fail):>3} fail {len(fail):>3}  {sec:.0f}s", flush=True)
        if fail:
            with open(PENDING, "a", encoding="utf-8") as f:
                for x in fail:
                    f.write(f"{x['code']}  # {x['err']}\n")
    print(f"\n拉取完成 {ok_all}/{len(codes)}，{(dt.datetime.now() - t0).total_seconds() / 60:.1f} 分钟")
    if fails:
        print(f"失败 {len(fails)} 只 → {PENDING}；重跑 --stage pull 前先把清单并回 repair_2014.json")
    print("下一步（前台）：python3 repair_2014.py --stage ingest")
    return 0


def stage_ingest(a) -> int:
    import pandas as pd
    import market_data as md

    files = sorted(glob.glob(os.path.join(CACHE, "rep_*.parquet")))
    if not files:
        print(f"{CACHE} 里没有 rep_*.parquet，先跑 --stage pull")
        return 2
    new = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    new["date"] = new["date"].astype(str)
    print(f"补齐数据 {len(new):,} 行 / {new['code'].nunique()} 只 ｜ "
          f"{new['date'].min()} ~ {new['date'].max()}")
    if a.dry_run:
        return 0

    p = os.path.join(md.BARS, "2014.parquet")
    old = pd.read_parquet(p)
    before_rows, before_codes = len(old), old["code"].nunique()
    merged = pd.concat([old, new], ignore_index=True)
    # keep="first"：磁盘上已有的行优先，补的是缺口
    merged = merged.drop_duplicates(["code", "date"], keep="first")
    n = md.rebuild_partition("2014", merged)
    print(f"  2014.parquet：{before_rows:,} 行 / {before_codes:,} 只 → "
          f"{n:,} 行 / {merged['code'].nunique():,} 只")

    # 落盘后按磁盘重算每票 first/last/n_bars，meta 的 3023 才是真的
    md.rebuild_meta()
    print("下一步：python3 -c 'import market_data as md; md.verify()' 应对上 0 只")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["pull", "ingest"], default="pull")
    ap.add_argument("--chunk", type=int, default=40)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    return stage_pull(a) if a.stage == "pull" else stage_ingest(a)


if __name__ == "__main__":
    raise SystemExit(main())
