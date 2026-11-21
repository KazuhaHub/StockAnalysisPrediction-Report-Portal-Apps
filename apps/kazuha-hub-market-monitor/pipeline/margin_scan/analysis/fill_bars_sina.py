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
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fetch_data import DATA, log  # noqa: E402

import akshare as ak  # noqa: E402

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

S_START = PREV.replace("-", "")
S_END = TARGET.replace("-", "")


def _mkt(code):
    if code[0] in "56":
        return "sh"
    if code[0] in "48":
        return "bj"
    return "sz"


def _one(code):
    """个股走 stock_zh_a_daily，场内基金（5/1 开头）走 fund_etf_hist_sina。

    2026-11-17 实测：新浪股票接口对 ETF 返回非 JSON（JSONDecodeError），
    ETF 必须走基金接口；两者 volume 均为股、amount 为元，与本地东财口径一致。
    """
    is_etf = code[0] in "15"
    for a in range(3):
        try:
            if is_etf:
                df = ak.fund_etf_hist_sina(symbol=_mkt(code) + code)
            else:
                df = ak.stock_zh_a_daily(symbol=_mkt(code) + code, start_date=S_START,
                                         end_date=S_END, adjust="qfq")
            if df is None or not len(df):
                return None
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            if is_etf:
                df = df[(df["date"] >= PREV) & (df["date"] <= TARGET)]
            return df
        except Exception:
            time.sleep(0.3 * (a + 1))
    return None


t0 = time.time()
recs, bad, none, ok_ref = [], [], [], 0
done = 0
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs = {ex.submit(_one, c): c for c in miss}
    for f in as_completed(futs):
        c = futs[f]
        df = f.result()
        done += 1
        if df is None:
            none.append(c)
        else:
            rrow = df[df["date"] == PREV]
            trow = df[df["date"] == TARGET]
            if not len(rrow):
                none.append(c)
            else:
                # 同日同口径校验：参照日必须与本地东财值一致
                dclose = abs(rrow.iloc[-1]["close"] / prevd.loc[c, "close"] - 1) * 100
                damt = (abs(rrow.iloc[-1]["amount"] / prevd.loc[c, "amount"] - 1) * 100
                        if prevd.loc[c, "amount"] else 0.0)
                if max(dclose, damt) > TOL:
                    bad.append((c, round(dclose, 2), round(damt, 2)))
                elif not len(trow):
                    none.append(c)
                else:
                    ok_ref += 1
                    r = trow.iloc[-1]
                    recs.append((c, TARGET, float(r["open"]), float(r["close"]),
                                 float(r["high"]), float(r["low"]),
                                 float(r["volume"]) / 100.0, float(r["amount"])))
        if done % 400 == 0 or done == len(miss):
            log("  进度 %d/%d  取得 %d  口径不符 %d  无数据 %d  %.0fs"
                % (done, len(miss), len(recs), len(bad), len(none), time.time() - t0))

log("汇总：取得 %d，参照日口径不符 %d，源无数据 %d" % (len(recs), len(bad), len(none)))
if bad:
    log("  不符样例（代码, 收盘偏差%%, 成交额偏差%%）：%s" % bad[:8])
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
