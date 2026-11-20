#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
稳健性检验 —— 专门用来拆掉第一轮结论里的假象。

三个必查项：
  ① 事件时间分布：极热/极冷事件是不是集中在 2015？若是，事件研究的"平均收益"是单一行情贡献。
  ② 剔除 2015-2016 后重跑：结论还在吗？
  ③ 分段 IC 稳定性：同一指标在三个时代是否同号？不同号 = 不可用。
另加：
  ④ 当前广度读数的历史类比：站上 MA250 低于 15% 之后，未来收益分布（这是最实用的部分）。
"""
import numpy as np
import pandas as pd
from scipy import stats

BASE = "/opt/daily-tasks/workspace/analysis/out/sentiment"
d = pd.read_csv(f"{BASE}/panel.csv", index_col=0, parse_dates=True)
NAV = d["eq_nav"]
fwd = {h: (NAV.shift(-h) / NAV - 1) for h in [5, 20, 60]}

IND = {
    "amt_per_stock": "每股成交额", "amt_ratio20": "成交额/20日均",
    "pct_adv": "上涨家数占比", "above_ma20": "站上MA20比例",
    "above_ma60": "站上MA60比例", "above_ma250": "站上MA250比例",
    "new_high_pct": "250日新高占比", "new_low_pct": "250日新低占比",
    "limit_up": "涨停家数", "limit_down": "跌停家数",
    "dispersion": "横截面离散度", "top10_amt_share": "成交额前10%集中度",
    "hhi": "成交额HHI", "r20_positive": "20日正收益占比",
    "r20_median": "20日收益中位数", "dd20_pct": "20日跌超20%占比",
    "eq_vol20": "已实现波动率",
}


def clusters(mask, gap=3):
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return []
    out, prev = [idx[0]], idx[0]
    for i in idx[1:]:
        if i - prev > gap:
            out.append(i)
        prev = i
    return out


print("=" * 100)
print("① 极值事件的时间分布（看结论是否被单一行情绑架）")
print("=" * 100)
print(f"\n{'指标':<16}{'方向':<6}{'簇数':>5}   年份分布（簇数）")
print("-" * 100)
for k, nm in IND.items():
    p = d[k + "_pct"]
    for lab, q in [("极冷", p <= 0.10), ("极热", p >= 0.90)]:
        cs = clusters(np.nan_to_num(q.values, nan=0).astype(bool))
        if len(cs) < 4:
            continue
        yrs = pd.Series([d.index[i].year for i in cs]).value_counts().sort_index()
        dist = "  ".join(f"{y}:{c}" for y, c in yrs.items())
        print(f"{nm:<16}{lab:<6}{len(cs):>5}   {dist}")

print("\n" + "=" * 100)
print("② 剔除 2015-2016（股灾+熔断）后，事件研究结论是否还在")
print("=" * 100)
mask_ex = np.asarray((d.index.year < 2015) | (d.index.year > 2016))
print(f"\n{'指标':<16}{'方向':<6}{'簇数':>5}{'fwd20原':>9}{'fwd20剔':>9}{'差':>8}{'t(bn)原':>9}{'t(bn)剔':>9}")
print("-" * 100)


def nw_t(x, lag=2):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    n = len(x)
    if n < 8:
        return np.nan, np.nan, n
    mu = x.mean(); e = x - mu; var = (e @ e) / n
    for L in range(1, min(lag, n - 1) + 1):
        var += 2 * (1 - L / (lag + 1)) * (e[L:] @ e[:-L]) / n
    se = np.sqrt(max(var, 1e-18) / n)
    return mu, mu / se, n


base20 = fwd[20].mean() * 100
for k, nm in IND.items():
    p = d[k + "_pct"]
    for lab, q in [("极冷", p <= 0.10), ("极热", p >= 0.90)]:
        m = np.nan_to_num(q.values, nan=0).astype(bool)
        cs = clusters(m)
        if len(cs) < 4:
            continue
        cs_ex = [i for i in cs if mask_ex[i]]
        if len(cs_ex) < 4:
            print(f"{nm:<16}{lab:<6}{len(cs_ex):>5}   —— 剔除后簇数不足，t 值无判别力")
            continue
        v1 = fwd[20].values[cs] * 100
        v2 = fwd[20].values[cs_ex] * 100
        mu1, _, _ = nw_t(v1); mu2, _, _ = nw_t(v2)
        _, t1, _ = nw_t(v1 - base20); _, t2, _ = nw_t(v2 - base20)
        print(f"{nm:<16}{lab:<6}{len(cs_ex):>5}{mu1:>9.2f}{mu2:>9.2f}{mu2-mu1:>8.2f}{t1:>9.2f}{t2:>9.2f}")

print("\n" + "=" * 100)
print("③ 分段稳定性：同一指标 fwd20 IC 在三个时代是否同号")
print("=" * 100)
SEG = [("2014-2017", 2014, 2017), ("2018-2021", 2018, 2021), ("2022-2026", 2022, 2026)]
print(f"\n{'指标':<16}" + "".join([f"{s[0]:>12}" for s in SEG]) + f"{'同号?':>8}")
print("-" * 100)
seg_rows = []
for k, nm in IND.items():
    ics = []
    for nm_s, y0, y1 in SEG:
        m = (d.index.year >= y0) & (d.index.year <= y1)
        x = d[k].values[m]; y = fwd[20].values[m]
        ok = (~np.isnan(x)) & (~np.isnan(y))
        ics.append(stats.spearmanr(x[ok], y[ok]).correlation if ok.sum() > 100 else np.nan)
    same = "是" if (np.nansum(np.sign(ics)) in (3, -3)) else "否"
    seg_rows.append(dict(ind=k, name=nm, **{s[0]: ics[i] for i, s in enumerate(SEG)}, same=same))
    print(f"{nm:<16}" + "".join([f"{v:>12.3f}" for v in ics]) + f"{same:>8}")
pd.DataFrame(seg_rows).to_csv(f"{BASE}/segment_ic.csv", index=False)

print("\n" + "=" * 100)
print("④ 当前读数类比：站上 MA250 比例 < 15% 的历史样本，之后怎么走")
print("=" * 100)
for thr in [0.12, 0.15, 0.20]:
    m = (d["above_ma250"] < thr)
    cs = clusters(np.nan_to_num(m.values, nan=0).astype(bool))
    print(f"\n阈值 above_ma250 < {thr:.0%}：触发 {m.sum()} 天 / {len(cs)} 簇")
    if len(cs) == 0:
        continue
    dates = [d.index[i] for i in cs]
    for h in [5, 20, 60]:
        v = fwd[h].values[cs] * 100
        mu, t0, n = nw_t(v)
        _, tb, _ = nw_t(v - fwd[h].mean() * 100)
        print(f"  fwd{h:>3}: 均值 {mu:>6.2f}%   t(0)={t0:>5.2f}  t(bn)={tb:>5.2f}   "
              f"胜率 {(v>0).mean():>5.1%}  区间[{np.min(v):.1f}%, {np.max(v):.1f}%]")
    print("  触发日:", ", ".join(x.strftime("%Y-%m-%d") for x in dates))

print("\n" + "=" * 100)
print("⑤ 分年度 IC：广度指标（above_ma250）的 fwd20 IC 逐年")
print("=" * 100)
yrs = sorted(set(d.index.year))
print(f"{'年份':<8}" + "".join([f"{'above250':>11}{'pctadv':>10}{'vol20':>9}" for _ in [0]]))
print("-" * 45)
for y in yrs:
    m = d.index.year == y
    if m.sum() < 100:
        continue
    out = []
    for k in ["above_ma250", "pct_adv", "eq_vol20"]:
        x = d[k].values[m]; yy = fwd[20].values[m]
        ok = (~np.isnan(x)) & (~np.isnan(yy))
        out.append(stats.spearmanr(x[ok], yy[ok]).correlation if ok.sum() > 80 else np.nan)
    print(f"{y:<8}" + "".join([f"{v:>11.3f}" if i == 0 else f"{v:>10.3f}" for i, v in enumerate(out)]))
