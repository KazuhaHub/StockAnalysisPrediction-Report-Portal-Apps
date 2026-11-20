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
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

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

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _px(code):
    mkt = "sh" if code[0] == "6" else ("bj" if code[0] in "48" else "sz")
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    for a in range(3):
        try:
            r = requests.get(url, params={"param": "%s%s,day,,,40,qfq" % (mkt, code)},
                             timeout=8, headers=UA)
            j = r.json()
            d = j.get("data", {}).get(mkt + code, {})
            k = d.get("qfqday") or d.get("day") or []
            if not k:
                return None
            return {x[0]: (float(x[1]), float(x[2]), float(x[3]), float(x[4]),
                           float(x[5])) for x in k}
        except Exception:
            time.sleep(0.2 * (a + 1))
    return None


t0 = time.time()
recs, bad, none = [], [], []
done = 0
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs = {ex.submit(_px, c): c for c in miss}
    for f in as_completed(futs):
        c = futs[f]
        m = f.result()
        done += 1
        if not m:
            none.append(c)
        else:
            ref_tx = m.get(PREV, (None, None))[1]
            if ref_tx and abs(ref_tx / prev[c] - 1) * 100 > TOL:
                bad.append((c, prev[c], ref_tx))
            elif TARGET in m:
                o, cl, hi, lo, vol = m[TARGET]
                recs.append((c, TARGET, o, cl, hi, lo, vol * 100, 0.0))
        if done % 500 == 0 or done == len(miss):
            log("  进度 %d/%d  取得 %d  拒绝 %d  无数据 %d  %.0fs"
                % (done, len(miss), len(recs), len(bad), len(none), time.time() - t0))

log("汇总：取得 %d，拒绝(复权不一致) %d，源无目标日 %d"
    % (len(recs), len(bad), len(none)))
if bad:
    log("  拒绝样例：%s" % bad[:5])
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
