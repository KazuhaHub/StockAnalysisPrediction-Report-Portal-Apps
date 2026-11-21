# -*- coding: utf-8 -*-
"""补齐 2026-11-12 日线缺口（09:00 开盘高峰限流导致 3012 只失败）。

复用 fetch_data._fetch_bars_one，低并发 + 重试 5，只补目标日缺失行，
不触碰历史，不删旧表。写盘走临时文件 + os.replace。
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fetch_data import _fetch_bars_one, DATA, log  # noqa: E402

TARGET = "2026-11-12"
END = "20261112"
WORKERS = 4
RETRY = 5

cache = DATA / "bars.parquet"
bak = DATA / ("bars.parquet.bak_" + time.strftime("%Y%m%d_%H%M%S"))
old = pd.read_parquet(cache)
old.to_parquet(bak, index=False)
log("备份 -> %s（%d 行）" % (bak.name, len(old)))

have_t = set(old[old["date"] == TARGET]["code"].unique())
prev = set(old[old["date"] == "2026-11-11"]["code"].unique())
miss = sorted(prev - have_t)
log("目标日 %s 已有 %d 只，待补 %d 只" % (TARGET, len(have_t), len(miss)))

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
    log("未取到任何新行，放弃写盘")
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
log("写盘完成：%d 行 / %d 只；%s 覆盖 %d 只（前一日 %d，占比 %.1f%%）"
    % (len(out), out["code"].nunique(), TARGET, cov, len(prev), 100.0 * cov / len(prev)))
if failed:
    log("仍缺 %d 只：%s" % (len(failed), ",".join(failed[:20])))
