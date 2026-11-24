# -*- coding: utf-8 -*-
"""定点补齐某交易日缺口 —— 新浪备用源版（东财 push2his 拒连时使用）。

背景（2026-11-17）：东财 push2his 对单请求也返回 RemoteDisconnected，fetch_bars 无法补数。
新浪 `ak.stock_zh_a_daily(adjust="qfq")` 实测与东财逐字段一致（600519 / 2026-11-12：
close 1410.27、volume 3,237,294 股 = 32,373 手、amount 4.536815e9 完全相同），可整段替代。

单位换算：新浪 volume 单位为股，本项目 bars.parquet 为手（东财口径）→ 除以 100。

安全阀（关键）：对每只票同时取「参照日」与「目标日」，用参照日收盘/成交额与本地东财值
逐只比对，偏差 > 0.5% 判为复权口径或数据不一致 → 该票不写入。这样校验的是同日同口径，
不会被正常涨跌误伤。

用法：fill_bars_sina.py 2026-11-13 [workers] [tol_pct]
"""
import os
import sys
import time
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fetch_data import DATA, log  # noqa: E402

TARGET = sys.argv[1] if len(sys.argv) > 1 else "2026-11-13"
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 4
TOL = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5

cache = DATA / "bars.parquet"
old = pd.read_parquet(cache)

have = set(old[old["date"] == TARGET]["code"].unique())
prev_dates = sorted(d for d in old["date"].unique() if d < TARGET)
PREV = prev_dates[-1]
prevd = old[old["date"] == PREV].set_index("code")[["close", "amount"]]
miss = sorted(set(prevd.index) - have)
log("目标日 %s 已有 %d 只；参照日 %s %d 只；待补 %d 只（%d 并发，容差 %.2f%%）"
    % (TARGET, len(have), PREV, len(prevd), len(miss), WORKERS, TOL))
if not miss:
    log("无需补齐")
    sys.exit(0)

import bar_sources  # noqa: E402

t0 = time.time()
recs, nbad = bar_sources.from_sina(miss, TARGET, PREV, prevd, workers=WORKERS, tol=TOL)
log("汇总：取得 %d，参照日口径不符 %d，未取到 %d，%.0fs"
    % (len(recs), nbad, len(miss) - len(recs) - nbad, time.time() - t0))
if not recs:
    log("无有效数据，不写盘")
    sys.exit(2)

bak = DATA / ("bars.parquet.bak_" + time.strftime("%Y%m%d_%H%M%S"))
old.to_parquet(bak, index=False)
log("备份 -> %s" % bak.name)

cols = ["code", "date", "open", "close", "high", "low", "volume", "amount"]
new = pd.DataFrame(recs, columns=cols)
out = (pd.concat([old, new], ignore_index=True)
         .drop_duplicates(subset=["code", "date"], keep="last")
         .sort_values(["code", "date"]))
tmp = cache.with_name("bars.parquet.tmp")
out.to_parquet(tmp, index=False)
os.replace(tmp, cache)

cov = out[out["date"] == TARGET]["code"].nunique()
log("写盘完成：%d 行 / %d 只；%s 覆盖 %d 只（%s 为 %d 只，占比 %.1f%%）"
    % (len(out), out["code"].nunique(), TARGET, cov, PREV, len(prevd), 100.0 * cov / len(prevd)))
