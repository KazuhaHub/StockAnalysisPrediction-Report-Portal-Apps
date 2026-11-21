# -*- coding: utf-8 -*-
"""分年度 / 分市场状态 的动量与反转 IC —— 判断"D 结论"是结构性还是阶段性"""
import sys
sys.path.insert(0, "/opt/daily-tasks/MarketData")
import numpy as np
import pandas as pd
import market_data as md

START = "2016-01-01"
FWD = 5
close = md.panel("close", start=START)
fwd = close.shift(-FWD) / close.shift(-1) - 1.0

mkt = close.pct_change().mean(axis=1)          # 等权市场收益，做状态划分
vol20_mkt = mkt.rolling(20).std()

FACTORS = {
    "动量20": close / close.shift(20) - 1.0,
    "反转5": -(close / close.shift(5) - 1.0),
    "反转20": -(close / close.shift(20) - 1.0),
    "距离60日线": -(close / close.rolling(60).mean() - 1.0),
}

def daily_ic(factor, ret, min_n=300):
    f, r = factor.values, ret.values
    ok = ~np.isnan(f) & ~np.isnan(r)
    n = ok.sum(axis=1)
    fd = np.where(ok, f, np.nan); rd = np.where(ok, r, np.nan)
    with np.errstate(invalid="ignore"):
        fm = np.nanmean(fd, axis=1, keepdims=True)
        rm = np.nanmean(rd, axis=1, keepdims=True)
        fd = np.where(ok, f - fm, 0.0); rd = np.where(ok, r - rm, 0.0)
        num = (fd * rd).sum(axis=1)
        den = np.sqrt((fd**2).sum(axis=1) * (rd**2).sum(axis=1))
        ic = np.where(den > 0, num / den, np.nan)
    return pd.Series(np.where(n >= min_n, ic, np.nan), index=factor.index)

ics = {k: daily_ic(v, fwd) for k, v in FACTORS.items()}
df = pd.DataFrame(ics).dropna(how="all")

print("=" * 78)
print(f"{'因子':<10}", end="")
years = sorted({d.year for d in df.index})
for y in years[-8:]:
    print(f"{y:>8}", end="")
print(f"{'全样本':>9}{'IC_IR':>8}")
print("-" * 78)
for k in FACTORS:
    print(f"{k:<10}", end="")
    for y in years[-8:]:
        sub = df[k][df.index.year == y]
        print(f"{sub.mean():>+8.4f}", end="")
    print(f"{df[k].mean():>+9.4f}{df[k].mean()/df[k].std()*np.sqrt(252):>8.2f}")

print("\n" + "=" * 78)
print("分市场状态（当日之前 20 日等权市场收益 + 波动）")
print("-" * 78)
st = pd.DataFrame({"ret": mkt, "vol": vol20_mkt})
st["trend"] = np.where(st["ret"].rolling(20).sum() > 0, "上行", "下行")
st["volregime"] = np.where(st["vol"] > st["vol"].rolling(250, min_periods=60).median(), "高波动", "低波动")
for col in ["trend", "volregime"]:
    print(f"\n[{col}]")
    for state in st[col].dropna().unique():
        idx = st.index[(st[col] == state) & st[col].notna()]
        print(f"  {state:<6} n={len(idx):>5}  " + "  ".join(
            f"{k} {df[k].reindex(idx).mean():+.4f}" for k in FACTORS))
print("\ndone")
