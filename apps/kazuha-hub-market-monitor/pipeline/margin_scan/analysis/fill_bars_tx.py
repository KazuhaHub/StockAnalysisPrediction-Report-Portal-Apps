# -*- coding: utf-8 -*-
"""定点补齐某交易日缺口 —— 腾讯备用源版（东财 push2his 拒连时使用）。

背景（2026-11-17）：东财 push2his.eastmoney.com 对单请求也返回 RemoteDisconnected，
fetch_bars 无法补数；腾讯 web.ifzq.gtimg.cn 的 qfq 日线正常。抽样 25 只与东财
2026-11-12 收盘价逐只比对，偏差 0.0000%（前复权口径一致），故可作临时替代。

安全阀：每只票用「参照日收盘」与本地东财值比对，偏差 > 0.5% 即判为复权口径不一致，
该票不写入（计入 skipped），避免污染历史。写盘临时文件 + os.replace，写前备份。

用法：fill_bars_tx.py 2026-11-13 [workers] [ref_tol_pct]
"""
import os
import sys
import time
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fetch_data import DATA, log  # noqa: E402

TARGET = sys.argv[1] if len(sys.argv) > 1 else "2026-11-13"
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 6
TOL = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5

cache = DATA / "bars.parquet"
old = pd.read_parquet(cache)

have = set(old[old["date"] == TARGET]["code"].unique())
prev_dates = sorted(d for d in old["date"].unique() if d < TARGET)
PREV = prev_dates[-1]
prev = old[old["date"] == PREV].set_index("code")["close"].to_dict()
miss = sorted(set(prev) - have)
log("目标日 %s 已有 %d 只；参照日 %s %d 只；待补 %d 只（%d 并发，容差 %.2f%%）"
    % (TARGET, len(have), PREV, len(prev), len(miss), WORKERS, TOL))

if not miss:
    log("无需补齐")
    sys.exit(0)

import bar_sources  # noqa: E402

t0 = time.time()
recs, nbad = bar_sources.from_tx(miss, TARGET, PREV, prev, workers=WORKERS, tol=TOL)
log("汇总：取得 %d，拒绝(复权不一致) %d，未取到 %d，%.0fs"
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
    % (len(out), out["code"].nunique(), TARGET, cov, PREV, len(prev), 100.0 * cov / len(prev)))
