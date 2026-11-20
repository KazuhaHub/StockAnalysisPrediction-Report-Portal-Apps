# -*- coding: utf-8 -*-
"""
实测播客最独特的论断："风格切换时，因子权重靠每天的量价数据一点点转回来，
这个过程通常要一两周" —— 董梁，2026-11

做法：完全复刻公募量化的因子权重机制
  1. 逐日横截面 IC（因子 vs 未来 5 日收益）
  2. 因子权重 = 滚动 60 日 IC 均值（对应"过去一年的表现决定权重"的短版）
  3. 用 2026-07-01 风格切换，看权重从"偏多"转到"偏空/中性"要多少交易日
"""
import os
import sys
sys.path.insert(0, "/opt/daily-tasks/MarketData")
import numpy as np
import pandas as pd
import market_data as md

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

START = "2019-06-01"
FWD = 5
WIN = 60          # 权重回看窗口

print("loading ...", flush=True)
close = md.panel("close", start=START)
print("panel", close.shape, close.index[0], close.index[-1], flush=True)

fwd = close.shift(-FWD) / close.shift(-1) - 1.0
mom20 = close / close.shift(20) - 1.0          # 动量
rev5 = -(close / close.shift(5) - 1.0)          # 反转（取负，越大=前期跌越多）

def daily_ic(factor, ret, min_n=100):
    """逐日横截面 Pearson IC"""
    f = factor.values
    r = ret.values
    ok = ~np.isnan(f) & ~np.isnan(r)
    n = ok.sum(axis=1)
    fm = np.where(ok, f, np.nan)
    rm = np.where(ok, r, np.nan)
    with np.errstate(invalid="ignore"):
        fmean = np.nanmean(np.where(ok, f, np.nan), axis=1, keepdims=True)
        rmean = np.nanmean(np.where(ok, r, np.nan), axis=1, keepdims=True)
        fd = np.where(ok, f - fmean, 0.0)
        rd = np.where(ok, r - rmean, 0.0)
        num = (fd * rd).sum(axis=1)
        den = np.sqrt((fd ** 2).sum(axis=1) * (rd ** 2).sum(axis=1))
        ic = np.where(den > 0, num / den, np.nan)
    ic = np.where(n >= min_n, ic, np.nan)
    return pd.Series(ic, index=factor.index)

print("computing IC ...", flush=True)
ic_mom = daily_ic(mom20, fwd)
ic_rev = daily_ic(rev5, fwd)

w_mom = ic_mom.rolling(WIN, min_periods=40).mean()     # 因子权重代理
w_rev = ic_rev.rolling(WIN, min_periods=40).mean()

print(f"\nIC 均值：动量 {ic_mom.mean():+.4f}  反转 {ic_rev.mean():+.4f}"
      f"  |  IC_IR(年化)：动量 {ic_mom.mean()/ic_mom.std()*np.sqrt(252):.2f}"
      f"  反转 {ic_rev.mean()/ic_rev.std()*np.sqrt(252):.2f}")

# 切换点扫描：给一个日期，算权重多久跨越 0
def lag_days(w_series, pivot, direction="down"):
    s = w_series.dropna()
    if pivot not in s.index:
        after = s[s.index >= pivot]
        if len(after) == 0:
            return None
        pivot = after.index[0]
    v0 = s.loc[pivot]
    tail = s[s.index >= pivot]
    for dt, v in tail.items():
        if direction == "down" and v <= 0:
            return (dt - pivot).days, len(tail[:dt]) - 1, v0, v
        if direction == "up" and v >= 0:
            return (dt - pivot).days, len(tail[:dt]) - 1, v0, v
    return None

print("\n=== 风格切换点扫描（动量权重从正转负需要多少交易日）===")
rows = []
for pivot in ["2024-01-02", "2024-09-24", "2025-04-07", "2026-07-01"]:
    p = pd.Timestamp(pivot)
    res = lag_days(w_mom, p, "down")
    if res is None:
        print(f"{pivot}: 窗口内未转负（切换后动量权重始终为正）")
        rows.append(dict(pivot=pivot, lag_trading_days=None, note="未转负"))
        continue
    cal, td, v0, v1 = res
    print(f"{pivot}: 起点权重 {v0:+.4f} → 转负用 {td} 个交易日（{cal} 自然日）")
    rows.append(dict(pivot=pivot, lag_trading_days=td, cal_days=cal, w0=v0, w_at_cross=v1))

# 最近状态
print("\n=== 最近 8 周权重轨迹 ===")
tail = pd.DataFrame({"w_mom": w_mom, "w_rev": w_rev}).dropna().tail(40)
tail = tail.iloc[::5]
for dt, r in tail.iterrows():
    print(f"  {dt.date()}  动量权重 {r['w_mom']:+.4f}   反转权重 {r['w_rev']:+.4f}")

out = pd.DataFrame(rows)
os.makedirs(OUT_DIR, exist_ok=True)
out.to_csv(os.path.join(OUT_DIR, "weight_lag.csv"), index=False)
pd.DataFrame({"ic_mom": ic_mom, "ic_rev": ic_rev,
              "w_mom": w_mom, "w_rev": w_rev}).to_csv(
    os.path.join(OUT_DIR, "ic_series.csv"))
print("\nsaved weight_lag.csv / ic_series.csv")
