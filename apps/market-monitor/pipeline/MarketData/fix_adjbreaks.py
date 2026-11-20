#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修两类「零成交行」瑕疵。默认只报告，`--apply` 才写回（写前自动快照）。


瑕疵 1：停牌日的复权断点（768 行 / 630 只）
------------------------------------------------
零成交行（停牌）的 OHLC 本应全部等于前收。实际有 768 行的收盘价与前一日不同，
而 factor 没变——源端把除权后的价格先落了下来、复权因子晚了很久才更新，或者
干脆没更新。后果是后复权序列凭空多出一根假收益：中位 −0.5%，极端 −75% / +705%，
集中在 2014–2018（那轮停牌潮）。全库 |收益|>50% 的怪值里有 202 例出自这里。

修法是「把价格拉平、让因子吸收股本变动」：
    C = 前收(已修正) / 本行收盘
    本行及后续行的 OHLC ×= C，factor ×= C
于是
    - 后复权 = OHLC×C  → 与前一交易日相等，序列连续；
    - 真实价 = (OHLC×C)/(factor×C) → **完全不变**，没有篡改事实；
    - 停牌期后复权价格恒定，天然满足「无成交 = 无收益」。

三个细节（都是踩过的）：
  a) 必须**传播**到后续行。600381 在 2014-06-27 缩股后价格涨 8 倍而因子一直没跟上，
     只修那一行，断点会顺移到下一行（复查仍是 767 行）。
  b) 但传播必须在「源端自己更新因子」时**撤销**。000007 在 2017-07-17 复牌时源端把
     factor 从 8.03 改成 12.05（正好是应补的 ×1.5），若继续乘我们的 1.5 会把之后
     整段放大 1.5 倍，复牌收益从 −10% 变成 +35%。
  c) 判别式用「已修正的前收」，不是原始前收，否则一段停牌里的第二根就开始漏。

瑕疵 2：denormal 噪声（967 行）
------------------------------------------------
零成交行的 amount 不是 0，而是 5.877472e-39（float32 下溢）。肉眼是 0，但下游
任何 `amount > 0` 的过滤都会把这 967 行 2026 年的停牌票当成「有成交」。

不修的东西：有成交日 |涨跌幅|>25% 的 333 行。逐条看过样本（002506 协鑫集成
2015-08-12 重整复牌、股本 1 拆 3，无涨跌幅限制），是真实事件。把它们当异常抹掉
才是制造错误。修完仍有 127 行 |收益|>50%，都是这类真事。

用法：
    python3 fix_adjbreaks.py             # 报告（含前 10 例）
    python3 fix_adjbreaks.py --apply     # 写回，并把修过的行记到 docs/adjbreak_fixed_<日期>.csv
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                       # noqa: E402
import pandas as pd                      # noqa: E402
import pyarrow.parquet as pq             # noqa: E402

import market_data as md                 # noqa: E402

COLS = ["code", "date", "open", "high", "low", "close", "volume", "amount",
        "factor", "tradestatus"]
DENORM = 1e-30
TOL = 1e-6


def _load() -> pd.DataFrame:
    parts = [pq.read_table(f, columns=COLS).to_pandas()
             for f in sorted(glob.glob(os.path.join(md.BARS, "*.parquet")))]
    return pd.concat(parts, ignore_index=True).sort_values(["code", "date"])


def _walk(g: pd.DataFrame) -> np.ndarray:
    """逐票前向走一遍，返回每行的修正倍数 C。g 需已按 date 排序。"""
    cl = g["close"].to_numpy(float)
    pf = g["factor"].to_numpy(float)
    vol = g["volume"].to_numpy(float)
    n = len(g)
    C = np.ones(n)
    c, prev_p = 1.0, None
    for i in range(n):
        # 源端自己 step 了因子、且当日有成交 → 之前的补偿撤销（细节 b）
        if i and pf[i] != pf[i - 1] and vol[i] > 0:
            c = 1.0
        p = cl[i] * c
        if (prev_p is not None and vol[i] <= 0
                and abs(p / prev_p - 1) > TOL):
            c = prev_p / cl[i]          # 细节 c：以已修正的前收为基准
            p = prev_p
        C[i] = c
        prev_p = p
    return C


def scan(detailed: bool = False):
    d = _load()
    d["C"] = np.concatenate([_walk(g) for _, g in d.groupby("code", sort=False)])
    d["close_f"] = d["close"] * d["C"]
    brk = d[d["C"] != 1.0]
    # 只把「断点那一行」算作断点（后续行是被传播的，不是新断点）
    first = brk.groupby("code").head(1)
    n_denorm = int(((d["amount"] > 0) & (d["amount"] < DENORM)).sum())
    n_zero = int((d["volume"] <= 0).sum())
    return d, first, n_denorm, n_zero


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写回分区（默认只报告）")
    a = ap.parse_args()

    d, brk, n_denorm, n_zero = scan()
    print(f"零成交行 {n_zero:,}｜复权断点 {len(brk)} 行 / {brk['code'].nunique()} 只"
          f"｜denormal 成交额 {n_denorm} 行")
    if len(brk):
        # 被抹掉的假收益 = 原始收盘 / 修正后收盘 − 1 = 1/C − 1
        r = brk["close"] / brk["close_f"] - 1
        print(f"  假收益：中位 {r.median():+.2%}｜最负 {r.min():+.1%}｜最正 {r.max():+.1%}")
        print("  年份：" + " ".join(f"{y}:{n}" for y, n in
                                  sorted(brk["date"].str.slice(0, 4).value_counts().items())))
        print(brk.assign(fake_ret=r)[["code", "date", "close", "close_f", "factor", "fake_ret"]]
              .reindex(r.abs().sort_values(ascending=False).index).head(10)
              .to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    if not a.apply:
        print(f"\n只报告，未改动。确认要改就加 --apply（会先快照，可 restore）。"
              f"\n预计改动 {int((d['C'] != 1).sum()):,} 行（含传播），真实价全部不变。")
        return 0

    snap = md.snapshot(tag="fix_adjbreaks")
    print(f"\n快照 {snap['stamp']}（回滚：market_data.py restore {snap['stamp']}）")

    d["open"] = d["open"] * d["C"]
    d["high"] = d["high"] * d["C"]
    d["low"] = d["low"] * d["C"]
    d["close"] = d["close_f"]
    d["factor"] = d["factor"] * d["C"]
    tiny = (d["amount"] > 0) & (d["amount"] < DENORM)
    d.loc[tiny, "amount"] = 0.0
    d = d.drop(columns=["C", "close_f"])

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    ev = os.path.join(md.ROOT, "docs", f"adjbreak_fixed_{stamp}.csv")
    out = brk.assign(fake_ret=(brk["close"] / brk["close_f"] - 1))[
        ["code", "date", "close", "close_f", "factor", "fake_ret"]]
    out.columns = ["code", "date", "close_raw", "close_fixed", "factor", "fake_ret_removed"]
    if len(out):
        out.to_csv(ev, index=False)
        print(f"  断点清单 → {ev}（{len(out)} 行）")
    else:
        print("  本次没有断点，不写清单（避免用空文件覆盖上一次的证据）")

    d["_y"] = d["date"].str.slice(0, 4)
    for y, g in d.groupby("_y"):
        # protect=False：整轮改动开头已经拍过一次全库快照，逐分区再拍会把
        # 那份「整轮回滚点」挤出滚动窗口（快照只留最近 10 份）。
        md.rebuild_partition(y, g.drop(columns=["_y"]).reset_index(drop=True),
                             quiet=True, protect=False)
        print(f"  {y}.parquet 写回 {len(g):,} 行")
    md.rebuild_meta()

    d2, brk2, denorm2, _ = scan()
    print(f"\n复查：断点 {len(brk2)} 行（应 0）｜denormal {denorm2} 行（应 0）")
    dd = d2["close"] / d2["factor"]
    print(f"     真实价 = close/factor 抽查中位 {dd.median():.4f}")
    return 0 if (len(brk2) == 0 and denorm2 == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
