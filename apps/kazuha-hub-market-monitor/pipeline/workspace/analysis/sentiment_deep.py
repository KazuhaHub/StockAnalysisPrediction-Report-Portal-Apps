#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深化：解决"逐年 IC 强、全样本 IC 弱"的矛盾。

假设 H：情绪指标存在组内/组间效应冲突
  - 组内（年内）：水位高 → 未来收益低（均值回复，负 IC）
  - 组间（跨年）：整体水位高 → 未来收益也高（牛熊状态延续，正相关）
  两者在全样本线性相关里互相抵消 → 指标看起来"无效"

若 H 成立，正确用法是「相对自身中枢的偏离」而不是「绝对分位」。
"""
import numpy as np
import pandas as pd
from scipy import stats

BASE = "/opt/daily-tasks/workspace/analysis/out/sentiment"
d = pd.read_csv(f"{BASE}/panel.csv", index_col=0, parse_dates=True)
NAV = d["eq_nav"]
fwd20 = NAV.shift(-20) / NAV - 1
ret_t = d["eq_ret"]

IND = ["above_ma250", "above_ma60", "above_ma20", "pct_adv", "new_low_pct",
       "r20_positive", "eq_vol20", "dispersion", "limit_down", "amt_ratio20"]


def sp(a, b):
    m = (~np.isnan(a)) & (~np.isnan(b))
    return stats.spearmanr(a[m], b[m]).correlation if m.sum() > 100 else np.nan


print("=" * 104)
print("【H 检验】原始分位 vs 去中枢偏离，对 fwd20 的 IC 对比")
print("=" * 104)
print(f"\n{'指标':<16}{'原始IC':>9}{'去250日均值':>13}{'年度去均值':>11}{'去250日分位':>13}{'组内均值IC':>11}")
print("-" * 104)
rows = []
for k in IND:
    s = d[k].astype(float)
    raw = sp(s.values, fwd20.values)
    # (a) 减 250 日均值：保留"相对近期中枢"的偏离
    dm250 = s - s.rolling(250, min_periods=120).mean()
    ic_dm = sp(dm250.values, fwd20.values)
    # (b) 年度去均值（每年减当年均值）：彻底消除 regime
    dm_y = s - s.groupby(s.index.year).transform("mean")
    ic_dy = sp(dm_y.values, fwd20.values)
    # (c) 相对 250 日均值的分位（偏离度的分位）
    pct_dm = dm250.rolling(750, min_periods=250).apply(lambda x: (x <= x[-1]).mean(), raw=True)
    ic_pd = sp(pct_dm.values, fwd20.values)
    # (d) 组内均值 IC：逐年算 IC 再平均（消除组间权重）
    ics = []
    for y in sorted(set(d.index.year)):
        m = d.index.year == y
        if m.sum() > 100:
            ics.append(sp(s.values[m], fwd20.values[m]))
    ic_within = np.nanmean(ics)
    rows.append(dict(ind=k, raw=raw, dm250=ic_dm, dm_year=ic_dy, pct_dm=ic_pd, within=ic_within))
    print(f"{k:<16}{raw:>9.3f}{ic_dm:>13.3f}{ic_dy:>11.3f}{ic_pd:>13.3f}{ic_within:>11.3f}")

pd.DataFrame(rows).to_csv(f"{BASE}/ic_demean.csv", index=False)

print("\n注：'原始IC'是把 12 年混在一起算；'组内均值IC'是逐年算再平均。两者差越大，组间/组内效应冲突越严重。")

# ---------- 簇级明细 ----------
print("\n" + "=" * 104)
print("【当前状态类比明细】站上 MA250 比例 < 15% 的 16 个事件簇，逐个看结果")
print("=" * 104)
fwd = {h: NAV.shift(-h) / NAV - 1 for h in [5, 20, 60]}
m = np.nan_to_num((d["above_ma250"] < 0.15).values, nan=0).astype(bool)
idx = np.where(m)[0]
cs, prev = [], None
for i in idx:
    if prev is None or i - prev > 3:
        cs.append(i)
    prev = i

print(f"\n{'触发日':<12}{'above250':>10}{'fwd5':>9}{'fwd20':>9}{'fwd60':>9}   备注")
print("-" * 104)
vals20, vals60 = [], []
for i in cs:
    a = d["above_ma250"].iloc[i] * 100
    v5 = fwd[5].iloc[i] * 100 if not np.isnan(fwd[5].iloc[i]) else np.nan
    v20 = fwd[20].iloc[i] * 100 if not np.isnan(fwd[20].iloc[i]) else np.nan
    v60 = fwd[60].iloc[i] * 100 if not np.isnan(fwd[60].iloc[i]) else np.nan
    if not np.isnan(v20): vals20.append(v20)
    if not np.isnan(v60): vals60.append(v60)
    note = "← 当前，进行中" if d.index[i] >= pd.Timestamp("2026-10-01") else ""
    print(f"{d.index[i].strftime('%Y-%m-%d'):<12}{a:>9.1f}%{v5:>9.2f}{v20:>9.2f}{v60:>9.2f}   {note}")

vals20, vals60 = np.array(vals20), np.array(vals60)
print(f"\n合计 {len(cs)} 簇，已成熟 {len(vals20)} 簇")
print(f"fwd20: 均值 {vals20.mean():.2f}%  中位 {np.median(vals20):.2f}%  "
      f"胜率 {(vals20>0).mean():.1%}  最差 {vals20.min():.1f}%  最好 {vals20.max():.1f}%")
print(f"fwd60: 均值 {vals60.mean():.2f}%  中位 {np.median(vals60):.2f}%  "
      f"胜率 {(vals60>0).mean():.1%}  最差 {vals60.min():.1f}%  最好 {vals60.max():.1f}%")
# 剔除 2015-2016
keep = [i for j, i in enumerate(cs) if d.index[i].year not in (2015, 2016) and not np.isnan(fwd[20].iloc[i])]
v = np.array([fwd[20].iloc[i] * 100 for i in keep])
print(f"\n剔除 2015-2016 后 {len(v)} 簇: fwd20 均值 {v.mean():.2f}%  中位 {np.median(v):.2f}%  胜率 {(v>0).mean():.1%}")

# ---------- 当前事件的实际进展 ----------
print("\n" + "=" * 104)
print("【当前事件进展】2026-10-29 触发至今")
print("=" * 104)
i0 = d.index.get_loc(pd.Timestamp("2026-10-29"))
nav0 = NAV.iloc[i0]
for i in range(i0, len(d)):
    el = i - i0
    print(f"{d.index[i].date()}  +{el:>2}d  等权指数 {NAV.iloc[i]/nav0-1:>+7.2%}  "
          f"站上MA250 {d['above_ma250'].iloc[i]*100:>5.1f}%  跌停 {int(d['limit_down'].iloc[i]):>3}  "
          f"上涨占比 {d['pct_adv'].iloc[i]*100:>5.1f}%")

# ---------- 结构错位：多指标联合 ----------
print("\n" + "=" * 104)
print("【结构错位】广度极冷 + 成交额中性的组合，历史上后面怎么走")
print("=" * 104)
cond = (d["above_ma250"] < 0.20) & (d["amt_per_stock_pct"].between(0.3, 0.7))
cs2 = []
idx2 = np.where(np.nan_to_num(cond.values, nan=0).astype(bool))[0]
prev = None
for i in idx2:
    if prev is None or i - prev > 3:
        cs2.append(i)
    prev = i
print(f"触发 {cond.sum()} 天 / {len(cs2)} 簇")
if cs2:
    for h in [5, 20, 60]:
        v = np.array([fwd[h].iloc[i] * 100 for i in cs2 if not np.isnan(fwd[h].iloc[i])])
        if len(v) > 2:
            print(f"  fwd{h:>3}: 均值 {v.mean():>6.2f}%  中位 {np.median(v):>6.2f}%  胜率 {(v>0).mean():>5.1%}  n={len(v)}")
    print("  触发日:", ", ".join(d.index[i].strftime("%Y-%m-%d") for i in cs2))
