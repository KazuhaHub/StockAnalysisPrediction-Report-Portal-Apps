#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出图表用数据（JSON）到 report 的 assets 目录。"""
import json
import numpy as np
import pandas as pd

BASE = "/opt/daily-tasks/workspace/analysis/out/sentiment"
OUT = "/opt/daily-tasks/workspace/reports/market-sentiment/assets/data.json"

d = pd.read_csv(f"{BASE}/panel.csv", index_col=0, parse_dates=True)
sc = pd.read_csv(f"{BASE}/score.csv", index_col=0, parse_dates=True)
NAV = d["eq_nav"]
fwd = {h: NAV.shift(-h) / NAV - 1 for h in [5, 20, 60]}
DIMS = ["量能", "广度", "极端", "赚钱效应", "资金结构"]

out = {}

# 1) 雷达：当前 / 2018-01-31（最相似日）/ 历史中位
out["radar"] = {
    "dims": DIMS,
    "cur": [round(float(sc[d].iloc[-1]) * 100, 1) for d in DIMS],
    "near2018": [round(float(sc.loc["2018-01-31", d]) * 100, 1) for d in DIMS],
    "median": [round(float(sc[d].median()) * 100, 1) for d in DIMS],
}

# 2) IC 对比：原始 vs 组内平均
ic = pd.read_csv(f"{BASE}/ic_demean.csv")
name_map = {
    "above_ma250": "站上MA250比例", "above_ma60": "站上MA60比例", "above_ma20": "站上MA20比例",
    "pct_adv": "上涨家数占比", "new_low_pct": "250日新低占比", "r20_positive": "20日正收益占比",
    "eq_vol20": "已实现波动率", "dispersion": "横截面离散度", "limit_down": "跌停家数",
    "amt_ratio20": "成交额/20日均",
}
order = ["pct_adv", "amt_ratio20", "eq_vol20", "dispersion", "limit_down",
         "new_low_pct", "r20_positive", "above_ma20", "above_ma60", "above_ma250"]
out["ic"] = {
    "names": [name_map[k] for k in order],
    "raw": [round(float(ic.set_index("ind").loc[k, "raw"]), 3) for k in order],
    "within": [round(float(ic.set_index("ind").loc[k, "within"]), 3) for k in order],
}

# 3) 广度/集中度时序（周度降采样）
sub = d.loc["2019-01-01":]
wk = sub.resample("ME").mean()
out["ts"] = {
    "dates": [x.strftime("%Y-%m-%d") for x in wk.index],
    "above250": [None if np.isnan(v) else round(float(v) * 100, 1) for v in wk["above_ma250"]],
    "above60": [None if np.isnan(v) else round(float(v) * 100, 1) for v in wk["above_ma60"]],
    "conc": [None if np.isnan(v) else round(float(v) * 100, 1) for v in wk["top10_amt_share_pct"]],
    "amt": [None if np.isnan(v) else round(float(v) * 100, 1) for v in wk["amt_per_stock_pct"]],
}

# 4) 条件分布热力图 4×3
bins_b = [0, 0.10, 0.20, 0.35, 1.01]
bins_c = [0, 0.34, 0.67, 1.01]
lab_b = ["广度<10%", "10-20%", "20-35%", ">35%"]
lab_c = ["集中度低", "中", "高"]
conc = d["top10_amt_share_pct"]
cells = []
for i in range(4):
    for j in range(3):
        m = ((d["above_ma250"] >= bins_b[i]) & (d["above_ma250"] < bins_b[i + 1]) &
             (conc >= bins_c[j]) & (conc < bins_c[j + 1]))
        v = fwd[20][m].median() * 100
        n = int(m.sum())
        if n >= 20 and not np.isnan(v):
            cells.append([j, i, round(float(v), 2), n])
        else:
            cells.append([j, i, "-", n])
out["cond"] = {"x": lab_c, "y": lab_b, "cells": cells}

# 5) 2026 季度轨迹
q = {}
for k, (s, e) in {"Q1": ("2026-01-01", "2026-03-31"), "Q2": ("2026-04-01", "2026-06-30"),
                  "Q3": ("2026-07-01", "2026-09-30"), "Q4": ("2026-10-01", "2026-12-31")}.items():
    s2 = d.loc[s:e]
    r = NAV.loc[s2.index[-1]] / NAV.loc[s2.index[0]] - 1
    q[k] = dict(conc=round(float(s2["top10_amt_share_pct"].median()) * 100, 0),
                b250=round(float(s2["above_ma250"].median()) * 100, 0),
                amt=round(float(s2["amt_per_stock_pct"].median()) * 100, 0),
                ret=round(float(r) * 100, 1))
out["q2026"] = q

# 6) PPI / CPI（ifind 实测，2024-01 起）
ppi = {"2024-01": -2.5, "2024-02": -2.7, "2024-03": -2.8, "2024-04": -2.5, "2024-05": -1.4,
       "2024-06": -0.8, "2024-07": -0.8, "2024-08": -1.8, "2024-09": -2.8, "2024-10": -2.9,
       "2024-11": -2.5, "2024-12": -2.3, "2025-01": -2.3, "2025-02": -2.2, "2025-03": -2.5,
       "2025-04": -2.7, "2025-05": -3.3, "2025-06": -3.6, "2025-07": -3.6, "2025-08": -2.9,
       "2025-09": -2.3, "2025-10": -2.1, "2025-11": -2.2, "2025-12": -1.9, "2026-01": -1.4,
       "2026-02": -0.9, "2026-03": 0.5, "2026-04": 2.8, "2026-05": 3.9, "2026-06": 4.1,
       "2026-07": 3.5, "2026-08": 3.8, "2026-09": 5.0, "2026-10": 5.7}
cpi = {"2024-01": None, "2024-02": None, "2024-03": None, "2024-04": None, "2024-05": None,
       "2024-06": None, "2024-07": None, "2024-08": None, "2024-09": None, "2024-10": None,
       "2024-11": None, "2024-12": None, "2025-01": None, "2025-02": None, "2025-03": None,
       "2025-04": None, "2025-05": None, "2025-06": None, "2025-07": None, "2025-08": None,
       "2025-09": None, "2025-10": None, "2025-11": None, "2025-12": None, "2026-01": 0.2,
       "2026-02": 1.3, "2026-03": 1.0, "2026-04": 1.2, "2026-05": 1.2, "2026-06": 1.0,
       "2026-07": 0.5, "2026-08": 0.8, "2026-09": 0.9, "2026-10": 0.7}
ks = list(ppi.keys())
out["ppi"] = {"months": ks, "ppi": [ppi[k] for k in ks], "cpi": [cpi[k] for k in ks]}

# 7) 当前事件路径 vs 历史中位路径
i0 = d.index.get_loc(pd.Timestamp("2026-10-29"))
nav0 = NAV.iloc[i0]
path = [round(float(NAV.iloc[i] / nav0 - 1) * 100, 2) for i in range(i0, min(i0 + 21, len(d)))]
# 历史中位路径：16 簇的 fwd 0..20 日中位
cs = []
m = np.nan_to_num((d["above_ma250"] < 0.15).values, nan=0).astype(bool)
idx = np.where(m)[0]
prev = None
for i in idx:
    if prev is None or i - prev > 3:
        cs.append(i)
    prev = i
cs = [i for i in cs if d.index[i] < pd.Timestamp("2026-01-01")]
med_path = []
for k in range(21):
    vals = []
    for i in cs:
        if i + k < len(NAV):
            vals.append(float(NAV.iloc[i + k] / NAV.iloc[i] - 1) * 100)
    med_path.append(round(float(np.median(vals)), 2) if vals else None)
out["path"] = {"cur": path, "hist": med_path, "days": list(range(len(path)))}

# 8) 五维当前分位（表格/条形）
out["dims"] = [{"name": dd, "cur": round(float(sc[dd].iloc[-1]) * 100, 0),
                "prev5": round(float(sc[dd].iloc[-6]) * 100, 0)} for dd in DIMS]

json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
print("写出", OUT)
print("radar:", out["radar"])
print("cond cells:", len(out["cond"]["cells"]))
print("path cur:", out["path"]["cur"])
print("path hist:", out["path"]["hist"])
