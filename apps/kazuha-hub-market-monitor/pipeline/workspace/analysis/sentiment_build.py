#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从本地行情库构建全市场情绪指标日频面板。

口径约定（重要）：
- 全部指标只用 T 日及之前的信息，滚动分位用过去 750 个交易日（约 3 年），无未来函数。
- 停牌日 volume==0，收益置 nan，不参与横截面统计。
- 涨停/跌停按板块阈值判定：主板 9.8%，创业板/科创板 19.8%，北交所 29.8%。
- 基准收益用「全市场等权组合」日收益（被停牌股排除），不用指数，因为情绪主要作用于中小盘。

输出：analysis/out/sentiment/panel.csv
"""
import sys, os, json
sys.path.insert(0, os.path.expanduser("~/MarketData"))
import numpy as np
import pandas as pd
import market_data as md

OUT = "/opt/daily-tasks/workspace/analysis/out/sentiment"
os.makedirs(OUT, exist_ok=True)

START = "2014-06-03"
# 终点跟随行情库最新交易日，不硬编码——否则每日监控会静默停止更新
_META = json.load(open(md.META, encoding="utf-8"))
END = _META.get("date_range", [START, None])[1] or pd.Timestamp.today().strftime("%Y-%m-%d")

print("[1/5] 加载行情面板 ...", flush=True)
codes = md.codes()
meta = json.load(open(md.META, encoding="utf-8"))["stocks"]
close = md.panel("close", codes=codes, start=START, end=END, dtype="float32")
volume = md.panel("volume", codes=codes, start=START, end=END, dtype="float32")
amount = md.panel("amount", codes=codes, start=START, end=END, dtype="float32")
print(f"    close {close.shape}, {close.index[0].date()} ~ {close.index[-1].date()}", flush=True)

# 板块映射，用于涨跌停阈值
board = pd.Series({c: meta.get(c, {}).get("board", "?") for c in close.columns})
NAME = pd.Series({c: meta.get(c, {}).get("name", "") for c in close.columns})


def limit_pct(b):
    if b in ("创业板", "科创板"):
        return 0.198
    if b == "北交所":
        return 0.298
    return 0.098


LIM = board.map(limit_pct)

print("[2/5] 计算个股日收益（停牌置 nan）...", flush=True)
ret = close.pct_change(fill_method=None)
tradable = volume > 0
ret = ret.where(tradable)            # 停牌日不参与
ret = ret.clip(-0.55, 0.55)          # 砍掉复权断点残差（极少）

# 全市场等权基准
eq_ret = ret.mean(axis=1)
eq_nav = (1 + eq_ret.fillna(0)).cumprod()

print("[3/5] 逐日横截面统计 ...", flush=True)
rows = []
dates = close.index
cnt_valid = ret.notna().sum(axis=1)

# 预计算滚动高低点（250 日）
# 用 ffill 后 close 的滚动最大/最小，停牌日 ffilled 不影响极值
close_ff = close.ffill()
high250 = close_ff.rolling(250, min_periods=120).max()
low250 = close_ff.rolling(250, min_periods=120).min()
ma20 = close_ff.rolling(20, min_periods=15).mean()
ma60 = close_ff.rolling(60, min_periods=40).mean()
ma250 = close_ff.rolling(250, min_periods=120).mean()

lim_row = LIM.values[None, :]  # (1, n)

for i, d in enumerate(dates):
    r = ret.iloc[i].values
    v = tradable.iloc[i].values
    a = amount.iloc[i].values
    m = v & ~np.isnan(r)
    n = m.sum()
    if n < 200:
        rows.append((d,) + (np.nan,)*19)
        continue

    rm = r[m]
    am = a[m]
    adv = int((rm > 0).sum())
    dec = int((rm < 0).sum())
    flat = int((rm == 0).sum())

    # 涨跌停
    lim_i = lim_row[0][m]
    limup = int((rm >= lim_i * 0.98).sum())
    limdn = int((rm <= -lim_i * 0.98).sum())

    # 均线站上比例（仅可交易日）
    c_ff = close_ff.iloc[i].values
    m20 = ma20.iloc[i].values
    m60 = ma60.iloc[i].values
    m250 = ma250.iloc[i].values
    h250 = high250.iloc[i].values
    l250 = low250.iloc[i].values
    ok20 = m20[~np.isnan(m20[m])] if False else m20[m]
    above20 = np.nanmean(np.where(np.isnan(ok20), np.nan, c_ff[m] > ok20)) if not np.isnan(ok20).all() else np.nan
    ok60 = m60[m]
    above60 = np.nanmean(np.where(np.isnan(ok60), np.nan, c_ff[m] > ok60)) if not np.isnan(ok60).all() else np.nan
    ok250 = m250[m]
    above250 = np.nanmean(np.where(np.isnan(ok250), np.nan, c_ff[m] > ok250)) if not np.isnan(ok250).all() else np.nan
    hh = h250[m]
    ll = l250[m]
    newhigh = np.nanmean(np.where(np.isnan(hh), np.nan, c_ff[m] >= hh * 0.999)) if not np.isnan(hh).all() else np.nan
    newlow = np.nanmean(np.where(np.isnan(ll), np.nan, c_ff[m] <= ll * 1.001)) if not np.isnan(ll).all() else np.nan

    # 成交额集中度：前 10% 个股（按成交额）占总成交额比例
    tot_amt = am.sum()
    if tot_amt > 0:
        k = max(1, int(n * 0.10))
        top_share = np.sort(am)[-k:].sum() / tot_amt
        hhi = ((am / tot_amt) ** 2).sum() * 1e4   # ×1e4 便于阅读
    else:
        top_share, hhi = np.nan, np.nan

    # 20 日个股收益中位数与正收益占比（用 ffill 后 20 日收益）
    rows.append((
        d,
        n,
        tot_amt,
        adv / max(dec, 1),
        adv / n,
        limup,
        limdn,
        np.median(rm),
        rm.std(),
        above20, above60, above250,
        newhigh, newlow,
        top_share, hhi,
        np.nan, np.nan, np.nan, np.nan,
    ))

cols = ["date", "n_valid", "amount_total", "ad_ratio", "pct_adv", "limit_up", "limit_down",
        "ret_median", "dispersion", "above_ma20", "above_ma60", "above_ma250",
        "new_high_pct", "new_low_pct", "top10_amt_share", "hhi",
        "r20_positive", "r20_median", "dd20_pct", "turnover_z"]
df = pd.DataFrame(rows, columns=cols).set_index("date")
df.index = pd.to_datetime(df.index)

# 20 日维度的赚钱效应（向量化，避免循环里算）
print("    补算 20 日赚钱效应 ...", flush=True)
r20 = close.pct_change(20, fill_method=None).where(tradable)
df["r20_positive"] = (r20 > 0).sum(axis=1) / r20.notna().sum(axis=1)
df["r20_median"] = r20.median(axis=1)
df["dd20_pct"] = (r20 < -0.20).sum(axis=1) / r20.notna().sum(axis=1)

# 基准：等权全市场
df["eq_ret"] = eq_ret
df["eq_nav"] = eq_nav
df["eq_vol20"] = eq_ret.rolling(20).std() * np.sqrt(252)

# 成交额标准化：每股化，消除库内股票数量增长带来的水平漂移
df["amt_per_stock"] = df["amount_total"] / df["n_valid"]
df["amt_ma20"] = df["amount_total"].rolling(20).mean()
df["amt_ratio20"] = df["amount_total"] / df["amt_ma20"]
df["amt_z60"] = (df["amount_total"] - df["amount_total"].rolling(60).mean()) / df["amount_total"].rolling(60).std()

# 滚动 3 年分位（过去 750 交易日，含当日；严格无未来）
W = 750
def roll_pct(s, w=W):
    return s.rolling(w, min_periods=250).apply(lambda x: (x <= x[-1]).mean(), raw=True)

PCT_COLS = ["amount_total", "amt_per_stock", "ad_ratio", "pct_adv", "limit_up", "limit_down", "dispersion",
            "above_ma20", "above_ma60", "above_ma250", "new_high_pct", "new_low_pct",
            "top10_amt_share", "hhi", "r20_positive", "r20_median", "dd20_pct",
            "amt_ratio20", "amt_z60", "eq_vol20"]
print("[4/5] 计算滚动 3 年分位 ...", flush=True)
for c in PCT_COLS:
    df[c + "_pct"] = roll_pct(df[c])

df.to_csv(f"{OUT}/panel.csv", encoding="utf-8")
print(f"[5/5] 写出 {OUT}/panel.csv  {df.shape}", flush=True)
print(df.tail(6)[["amount_total", "pct_adv", "limit_up", "limit_down", "above_ma20", "dispersion"]])
