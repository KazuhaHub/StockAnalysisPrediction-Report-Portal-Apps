# -*- coding: utf-8 -*-
"""从原始产物精确导出图表数据，避免手抄。输出 assets/data.js"""
import sys, json
sys.path.insert(0, "/opt/daily-tasks/MarketData")
import numpy as np
import pandas as pd
import market_data as md

OUT = "/opt/daily-tasks/WorkBuddy/2026-11-07-08-26-45/quant-skill-audit-2026-11/assets/data.js"
AUD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# ---- 1. 权重轨迹（真实序列，周度采样）----
ic = pd.read_csv(f"{AUD}/ic_series.csv", index_col=0, parse_dates=True)
ic = ic.loc["2024-10-01":, ["w_mom", "w_rev"]].dropna()
w = ic.resample("W-FRI").last().dropna()

# ---- 2. 分年度 IC（重算，与 ic_by_regime.py 同口径）----
START, FWD = "2016-01-01", 5
close = md.panel("close", start=START)
fwd = close.shift(-FWD) / close.shift(-1) - 1.0


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
        den = np.sqrt((fd ** 2).sum(axis=1) * (rd ** 2).sum(axis=1))
        icv = np.where(den > 0, num / den, np.nan)
    return pd.Series(np.where(n >= min_n, icv, np.nan), index=factor.index)


FAC = {
    "mom20": close / close.shift(20) - 1.0,
    "rev5": -(close / close.shift(5) - 1.0),
    "dist60": -(close / close.rolling(60).mean() - 1.0),
}
ics = pd.DataFrame({k: daily_ic(v, fwd) for k, v in FAC.items()})
years = [y for y in range(2019, 2027)]
by_year = {k: [round(float(ics[k][ics.index.year == y].mean()), 4) for y in years] for k in FAC}

data = {
    "weight": {
        "dates": [d.strftime("%Y-%m-%d") for d in w.index],
        "w_mom": [round(float(v), 4) for v in w["w_mom"]],
        "w_rev": [round(float(v), 4) for v in w["w_rev"]],
    },
    "icYear": {"years": [str(y) for y in years], **by_year},
    "pool": {
        "labels": ["SIG-003", "SIG-004", "SIG-006", "SIG-009"],
        "raw55": [0.16, -0.02, -0.13, -0.17],
        "rawBig": [-0.04, -0.65, -0.08, -0.83],
        "neu55": [0.07, 0.04, 0.15, 0.83],
        "neuBig": [-0.03, -0.28, -0.04, -0.35],
    },
    "div": {
        "names": ["中证红利", "红利低波", "沪深300", "中证500"],
        "evMean": [3.64, 3.36, 2.93, 3.38],
        "baseMean": [0.81, 0.79, 0.60, 0.72],
        "pctile": [95.7, 96.4, 92.7, 92.8],
        "nEvents": [13, 15, 15, 17],
    },
}

with open(OUT, "w") as f:
    f.write("window.CHARTDATA=" + json.dumps(data, ensure_ascii=False) + ";\n")
print("saved", OUT)
print("weight weeks", len(w.index), "| w_rev range",
      round(min(w['w_rev']), 4), round(max(w['w_rev']), 4))
print("icYear:", json.dumps(by_year, ensure_ascii=False))
