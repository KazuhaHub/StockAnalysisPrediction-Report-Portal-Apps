#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
情绪指标有效性检验。

三个层次，逐一拆开（这是本研究的核心，不是简单看相关性）：
  L1 同期性  corr(指标_t, 当期收益_t)      —— 指标是否真的"在描述情绪"
  L2 预测性  corr(指标_t, 未来 h 日收益)    —— 指标是否有"择时价值"
  L3 赔率    极值区分组的多空收益差          —— 有交易意义吗

统计口径：
- 日频重叠样本，t 值用 Newey-West(lag=h) 修正自相关，不用裸 t。
- 同时给 t(相对0) 与 t(相对全样本基准均值)，两者分列；基准离 0 远时结论会打架。
- 事件研究把连续触发日合并为一个"事件簇"，用簇均值算 t，避免把一次信号数成 30 次。
"""
import numpy as np
import pandas as pd
from scipy import stats

BASE = "/opt/daily-tasks/workspace/analysis/out/sentiment"
d = pd.read_csv(f"{BASE}/panel.csv", index_col=0, parse_dates=True)

HORIZONS = [5, 20, 60]
NAV = d["eq_nav"]
fwd = {h: (NAV.shift(-h) / NAV - 1) for h in HORIZONS}
ret_t = d["eq_ret"]

IND = {
    "amt_per_stock":      "每股成交额",
    "amount_total":       "全市场成交额",
    "amt_ratio20":        "成交额/20日均",
    "amt_z60":            "成交额60日z",
    "pct_adv":            "上涨家数占比",
    "ad_ratio":           "涨跌家数比",
    "above_ma20":         "站上MA20比例",
    "above_ma60":         "站上MA60比例",
    "above_ma250":        "站上MA250比例",
    "new_high_pct":       "250日新高占比",
    "new_low_pct":        "250日新低占比",
    "limit_up":           "涨停家数",
    "limit_down":         "跌停家数",
    "dispersion":         "横截面离散度",
    "top10_amt_share":    "成交额前10%集中度",
    "hhi":                "成交额HHI",
    "r20_positive":       "20日正收益占比",
    "r20_median":         "20日收益中位数",
    "dd20_pct":           "20日跌超20%占比",
    "eq_vol20":           "已实现波动率",
}
GROUPS = {
    "量能":  ["amt_per_stock", "amount_total", "amt_ratio20", "amt_z60"],
    "广度":  ["pct_adv", "ad_ratio", "above_ma20", "above_ma60", "above_ma250", "new_high_pct", "new_low_pct"],
    "极端":  ["limit_up", "limit_down"],
    "结构":  ["dispersion", "top10_amt_share", "hhi"],
    "赚钱":  ["r20_positive", "r20_median", "dd20_pct"],
    "波动":  ["eq_vol20"],
}


def nw_t(x, lag):
    """单样本均值 t 值，Newey-West 修正。"""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 10:
        return np.nan, np.nan, n
    mu = x.mean()
    e = x - mu
    g0 = (e @ e) / n
    var = g0
    for L in range(1, min(lag, n - 1) + 1):
        w = 1 - L / (lag + 1)
        gl = (e[L:] @ e[:-L]) / n
        var += 2 * w * gl
    var = max(var, 1e-18)
    se = np.sqrt(var / n)
    return mu, mu / se, n


def spearman(a, b):
    m = (~np.isnan(a)) & (~np.isnan(b))
    if m.sum() < 50:
        return np.nan, 0
    return stats.spearmanr(a[m], b[m]).correlation, int(m.sum())


def clusters(mask):
    """把连续 True 合并成事件簇，返回每个簇的首日索引。"""
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return []
    out, start, prev = [idx[0]], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > 3:      # 间隔超过 3 个交易日算新事件
            out.append(i)
        prev = i
    return out


# ---------- 当前读数 ----------
CUR_DATE = d.index[-1]
cur = d.iloc[-1]
print(f"\n{'='*96}\n当前读数基准日: {CUR_DATE.date()}   (等权全市场 NAV={cur['eq_nav']:.3f})\n{'='*96}")

# ---------- L1/L2：同期 vs 预测 ----------
print(f"\n【L1+L2】同期相关性 vs 预测相关性（全样本 {d.index[0].date()}~{d.index[-1].date()}）\n")
print(f"{'指标':<18}{'分组':<6}{'L1同期IC':>10}{'L2 fwd20 IC':>13}{'IC_t(NW)':>10}{'解释力':>10}")
print("-" * 96)
res = []
for k, nm in IND.items():
    s = d[k].astype(float)
    ic1, _ = spearman(s.values, ret_t.values)
    ic20, n20 = spearman(s.values, fwd[20].values)
    # NW t：用分块均值法给 IC 的显著性（每 20 日取一个不重叠样本近似）
    x = s.values
    y = fwd[20].values
    m = (~np.isnan(x)) & (~np.isnan(y))
    sub = np.arange(len(x))[m][::20]
    if len(sub) > 20:
        rk = stats.rankdata(x[sub]); rk2 = stats.rankdata(y[sub])
        r = np.corrcoef(rk, rk2)[0, 1]
        nn = len(sub)
        tv = r * np.sqrt((nn - 2) / max(1 - r * r, 1e-12))
    else:
        tv = np.nan
    grp = next((g for g, lst in GROUPS.items() if k in lst), "-")
    ratio = abs(ic1) / max(abs(ic20), 1e-9) if not np.isnan(ic1) and not np.isnan(ic20) else np.nan
    res.append(dict(ind=k, name=nm, group=grp, ic_now=ic1, ic_f20=ic20, t_f20=tv, ratio=ratio))
    print(f"{nm:<18}{grp:<6}{ic1:>10.3f}{ic20:>13.3f}{tv:>10.1f}{ratio:>10.1f}")

R = pd.DataFrame(res)
R.to_csv(f"{BASE}/ic_table.csv", index=False)

# ---------- L3：极值区分组 ----------
print(f"\n\n【L3】按滚动3年分位分5组，各组未来20日平均收益（%）\n")
print(f"{'指标':<18}{'Q1(最冷)':>10}{'Q2':>9}{'Q3':>9}{'Q4':>9}{'Q5(最热)':>10}{'Q5-Q1':>9}{'单调性':>8}")
print("-" * 96)
qres = []
for k, nm in IND.items():
    p = d[k + "_pct"]
    row = []
    for q in range(5):
        lo, hi = q / 5, (q + 1) / 5
        m = (p > lo) & (p <= hi) if q > 0 else (p >= lo - 1e-9) & (p <= hi)
        v = fwd[20][m].mean() * 100
        row.append(v)
    spread = row[4] - row[0]
    mono = stats.spearmanr(range(5), row).correlation if not any(np.isnan(row)) else np.nan
    qres.append(dict(ind=k, name=nm, **{f"Q{i+1}": row[i] for i in range(5)}, spread=spread, mono=mono))
    print(f"{nm:<18}{row[0]:>10.2f}{row[1]:>9.2f}{row[2]:>9.2f}{row[3]:>9.2f}{row[4]:>10.2f}{spread:>9.2f}{mono:>8.2f}")

Q = pd.DataFrame(qres)
Q.to_csv(f"{BASE}/quintile_table.csv", index=False)

# ---------- 事件研究：极冷 / 极热 ----------
print(f"\n\n【事件研究】分位≤10%（极冷）与 ≥90%（极热）后，未来收益（%）")
print("簇 = 连续触发合并；t(0)=相对0，t(bench)=相对全样本基准均值\n")
base_mean = {h: fwd[h].mean() * 100 for h in HORIZONS}
print(f"全样本基准: 5日 {base_mean[5]:.2f}%  20日 {base_mean[20]:.2f}%  60日 {base_mean[60]:.2f}%\n")

ev_rows = []
hdr = f"{'指标':<16}{'方向':<6}" + "".join([f"{'fwd'+str(h):>8}{'t(0)':>7}{'t(bn)':>7}" for h in HORIZONS]) + f"{'簇数':>6}"
print(hdr); print("-" * len(hdr) * 2)
for k, nm in IND.items():
    p = d[k + "_pct"]
    for lab, mask in [("极冷", (p <= 0.10).values), ("极热", (p >= 0.90).values)]:
        cs = clusters(np.nan_to_num(mask, nan=0).astype(bool))
        if len(cs) < 4:
            continue
        line = f"{nm:<16}{lab:<6}"
        rec = dict(ind=k, name=nm, side=lab, n_cluster=len(cs))
        for h in HORIZONS:
            vals = fwd[h].values[cs]
            mu, t0, _ = nw_t(vals * 100, lag=2)
            _, tb, _ = nw_t((vals * 100) - base_mean[h], lag=2)
            rec[f"fwd{h}"] = mu; rec[f"t0_{h}"] = t0; rec[f"tb_{h}"] = tb
            line += f"{mu:>8.2f}{t0:>7.2f}{tb:>7.2f}"
        line += f"{len(cs):>6}"
        ev_rows.append(rec)
        print(line)

E = pd.DataFrame(ev_rows)
E.to_csv(f"{BASE}/event_table.csv", index=False)

# ---------- 当前读数 ----------
print(f"\n\n【当前读数】{CUR_DATE.date()} 各指标分位与原始值\n")
print(f"{'指标':<18}{'分组':<6}{'当前值':>14}{'3年分位':>10}{'历史极值(低/高)':>22}")
print("-" * 96)
cur_rows = []
for k, nm in IND.items():
    v = d[k].iloc[-1]
    pv = d[k + "_pct"].iloc[-1]
    lo, hi = d[k].quantile(0.05), d[k].quantile(0.95)
    fmt = (lambda x: f"{x:.2e}") if abs(v) > 1e6 else (lambda x: f"{x:.3f}")
    grp = next((g for g, lst in GROUPS.items() if k in lst), "-")
    cur_rows.append(dict(ind=k, name=nm, group=grp, value=v, pct3y=pv, q05=lo, q95=hi))
    print(f"{nm:<18}{grp:<6}{fmt(v):>14}{pv*100:>9.1f}%{fmt(lo)+' / '+fmt(hi):>22}")

C = pd.DataFrame(cur_rows)
C.to_csv(f"{BASE}/current.csv", index=False)

print("\n完成。输出：ic_table.csv / quintile_table.csv / event_table.csv / current.csv")
