# -*- coding: utf-8 -*-
"""定点补齐某一交易日的日线缺口（开盘高峰限流 / 东财 K 线未更新导致覆盖率不达标）。

用法：
  /opt/daily-tasks/venv/bin/python3 -u analysis/fill_bars.py 2026-11-13

设计原则（2026-11-13 确立，此后沿用）：
  - 复用 fetch_data._fetch_bars_one，低并发 + retry，只补目标日缺失行；
  - 不触碰历史、不删旧表，写盘走临时文件 + os.replace；
  - 写前自动备份 bars.parquet；
  - 补完不自动 build，看覆盖率再决定（<99% 直接 build 会污染池与余额口径）。
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fetch_data import _fetch_bars_one, DATA, log  # noqa: E402

if len(sys.argv) < 2:
    print("用法: fill_bars.py YYYY-MM-DD [workers] [retry]")
    sys.exit(1)

TARGET = sys.argv[1]
END = TARGET.replace("-", "")
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 4
RETRY = int(sys.argv[3]) if len(sys.argv) > 3 else 5

cache = DATA / "bars.parquet"
bak = DATA / ("bars.parquet.bak_" + time.strftime("%Y%m%d_%H%M%S"))
old = pd.read_parquet(cache)
old.to_parquet(bak, index=False)
log("备份 -> %s（%d 行）" % (bak.name, len(old)))

have_t = set(old[old["date"] == TARGET]["code"].unique())
prev_dates = sorted(d for d in old["date"].unique() if d < TARGET)
if not prev_dates:
    log("找不到 %s 之前的交易日，退出" % TARGET)
    sys.exit(1)
PREV = prev_dates[-1]
prev = set(old[old["date"] == PREV]["code"].unique())

# 若表里已有目标日但数量不足，也把"目标日缺、前一日有"的全部补齐
miss = sorted(prev - have_t)
log("目标日 %s 已有 %d 只；参照日 %s 有 %d 只；待补 %d 只（%d 并发 / retry %d）"
    % (TARGET, len(have_t), PREV, len(prev), len(miss), WORKERS, RETRY))

if not miss:
    log("无需补齐，退出")
    sys.exit(0)

t0 = time.time()
recs = []
failed = []
done = 0
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs = {ex.submit(_fetch_bars_one, c, RETRY, END): c for c in miss}
    for f in as_completed(futs):
        c = futs[f]
        try:
            r = f.result()
        except Exception:
            r = None
        done += 1
        if r:
            hit = [x for x in r if x[1] == TARGET]
            if hit:
                recs.extend(hit)
            else:
                failed.append(c)
        else:
            failed.append(c)
        time.sleep(0.15)
        if done % 250 == 0 or done == len(miss):
            log("  补齐进度 %d/%d  成功 %d  失败 %d  用时 %.0fs"
                % (done, len(miss), len(recs), len(failed), time.time() - t0))

if not recs:
    log("未取到任何新行，放弃写盘（bars.parquet 保持原样，已备份 %s）" % bak.name)
    sys.exit(2)

cols = ["code", "date", "open", "close", "high", "low", "volume", "amount"]
new = pd.DataFrame(recs, columns=cols).drop_duplicates(subset=["code", "date"])
out = (pd.concat([old, new], ignore_index=True)
         .drop_duplicates(subset=["code", "date"], keep="last")
         .sort_values(["code", "date"]))
tmp = cache.with_name("bars.parquet.tmp")
out.to_parquet(tmp, index=False)
os.replace(tmp, cache)

cov = out[out["date"] == TARGET]["code"].nunique()
log("写盘完成：%d 行 / %d 只；%s 覆盖 %d 只（%s 为 %d 只，占比 %.1f%%）"
    % (len(out), out["code"].nunique(), TARGET, cov, PREV, len(prev), 100.0 * cov / len(prev)))
if failed:
    log("仍缺 %d 只：%s" % (len(failed), ",".join(failed[:20])))
    log("可再跑一次本脚本补第二轮")
