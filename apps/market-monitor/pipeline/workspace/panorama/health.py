"""因子体检：月度截面 Rank IC + 动量分层实测（2024-06 ~ 2026-09，共 28 个调仓点）。

只做能做的：不做行业中性后的多头组合，只看「方向对不对、单调不单调」。
"""
import json
import os
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
os.environ.setdefault("PYTHONPATH", os.path.expanduser("~/MarketData"))
import sys
sys.path.insert(0, os.path.expanduser("~/MarketData"))
import market_data as md

D = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(D, "data")
from asof import asof_iso  # noqa: E402

END = asof_iso()

# ---------------- 价格
meta = json.load(open(os.path.expanduser("~/MarketData/meta.json")))["stocks"]
codes = sorted(meta.keys())
bars = md.load(codes, start="2023-06-01", end=END)
bars["date"] = pd.to_datetime(bars["date"])
bars = bars[bars["volume"] > 0]
sys.path.insert(0, D)
from features import price_panels  # noqa: E402

# Traded prices for EP/BP; back-adjusted closes for momentum, volatility and
# forward returns, so an ex-dividend day is not counted as a loss.
px, adj = price_panels(bars)
ret = adj.pct_change()

# ---------------- 财务（按公告日生效）
pan = pd.DataFrame(json.load(open(f"{DATA}/panel.json")))
pan["symbol"] = pan["symbol"].astype(str).str.zfill(6)
for c in ["ttm_net_income", "shares_outstanding", "bps", "roe", "rev_yoy", "np_yoy",
          "gross_margin", "net_income", "operating_cf"]:
    pan[c] = pd.to_numeric(pan[c], errors="coerce")
pan["avail"] = pd.to_datetime(pan["available_at"].astype(str), errors="coerce")
pan = pan.dropna(subset=["avail"]).sort_values("avail")
q = pan["report_period"].astype(str).str[4:8].map({"0331": 1, "0630": 2, "0930": 3, "1231": 4}).fillna(4)
pan["roe_ann"] = pan["roe"] * 4 / q

# ---------------- 月度调仓点
# 每月最后一个交易日（resample 的月标签不是真实交易日，必须回到原索引取）
_last = pd.Series(px.index, index=px.index).groupby([px.index.year, px.index.month]).max()
dates = [d for d in _last.tolist() if pd.Timestamp("2024-06-30") <= d <= pd.Timestamp("2026-09-30")]

FACTORS = ["EP", "BP", "MOM_12_1", "ROE", "REV_YOY", "LOW_VOL"]
ic = {f: {"d": [], "ic20": [], "ic60": [], "ic_ind20": []} for f in FACTORS}
layer_rows = []
# 截面宽度：IC 是在"当期有价格的票"上算的，所以样本库补了多少票，直接改写每个
# 调仓点的横截面。不记录这一项，补票前后的 IC 差异就分不清是因子变了还是样本变了。
width_rows = []

# 行业（当期静态，只用于 IC 的行业内版本）
ind = pd.DataFrame(json.load(open(f"{DATA}/industry.json")))
ind["symbol"] = ind["symbol"].astype(str).str.zfill(6)
ind = ind.drop_duplicates("symbol").set_index("symbol")["industry_name"]

for d in dates:
    if d not in px.index:
        continue
    p = px.loc[d].dropna()
    if len(p) < 800:
        continue
    sub = pan[pan["avail"] <= d].groupby("symbol").tail(1).set_index("symbol")
    e = (sub["ttm_net_income"] / sub["shares_outstanding"]).reindex(p.index)
    f = pd.DataFrame({
        "EP": e / p,
        "BP": sub["bps"].reindex(p.index) / p,
        "MOM_12_1": adj.shift(21).pct_change(231).loc[:d].iloc[-1].reindex(p.index),
        "ROE": sub["roe_ann"].reindex(p.index),
        "REV_YOY": sub["rev_yoy"].reindex(p.index),
        "LOW_VOL": -ret.rolling(120).std().loc[:d].iloc[-1].reindex(p.index) * np.sqrt(252),
    })
    f["sw1"] = f.index.map(ind)
    width_rows.append({"d": str(d.date()), "n": int(len(p)),
                       "n_mom": int(f["MOM_12_1"].notna().sum()),
                       "n_ep": int(f["EP"].notna().sum())})
    # 前视收益
    idx = px.index.get_loc(d)
    f["fwd20"] = np.nan
    f["fwd60"] = np.nan
    for h in (20, 60):
        if idx + h < len(px.index):
            fw = (adj.iloc[idx + h] / adj.loc[d] - 1).reindex(p.index)
            f[f"fwd{h}"] = fw
    for fac in FACTORS:
        s = f[[fac, "fwd20", "fwd60", "sw1"]].dropna(subset=[fac])
        if len(s) < 200:
            continue
        ic[fac]["d"].append(str(d.date()))
        ic[fac]["ic20"].append(round(float(s[fac].corr(s["fwd20"], method="spearman")), 4))
        ic[fac]["ic60"].append(round(float(s[fac].corr(s["fwd60"], method="spearman")), 4))
        # 行业内 IC（去行业均值后的秩相关）
        z = s.groupby("sw1")[[fac, "fwd20"]].transform(lambda x: x.rank(pct=True))
        ic[fac]["ic_ind20"].append(round(float(z[fac].corr(z["fwd20"], method="spearman")), 4))

    # 动量五分层
    s = f[["MOM_12_1", "fwd60"]].dropna()
    if len(s) > 300:
        try:
            s["q"] = pd.qcut(s["MOM_12_1"], 5, labels=[1, 2, 3, 4, 5])
            g = s.groupby("q")["fwd60"].mean()
            layer_rows.append({"d": str(d.date()), **{f"Q{k}": round(float(v) * 100, 2)
                                                      for k, v in g.items()},
                               "n": int(len(s))})
        except Exception:
            pass

lay = pd.DataFrame(layer_rows)
health = {
    "asof": str(dates[-1].date()) if dates else None,
    "n_dates": len(dates),
    "n_codes": int(len(codes)),
    "width": width_rows,
    "factors": {k: {"dates": v["d"], "ic20": v["ic20"], "ic60": v["ic60"],
                    "ic_ind20": v["ic_ind20"],
                    # n 必须逐个因子报：EP / REV_YOY 只从 2025-04 起才有可用值
                    # （ttm_net_income / rev_yoy 在更早的报告期是空的），
                    # 而 BP / 动量有 27 期。页面统一写"27 个调仓点"是在骗人。
                    "n": len(v["d"]),
                    "ic20_mean": round(float(np.nanmean(v["ic20"])), 4) if v["ic20"] else None,
                    "ic20_win": round(float(np.mean(np.array(v["ic20"]) > 0)), 3) if v["ic20"] else None,
                    "ic60_mean": round(float(np.nanmean(v["ic60"])), 4) if v["ic60"] else None,
                    "ic60_win": round(float(np.mean(np.array(v["ic60"]) > 0)), 3) if v["ic60"] else None,
                    } for k, v in ic.items()},
    "momentum_layers": layer_rows,
    "momentum_summary": {},
}
if len(lay):
    for k in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        health["momentum_summary"][k] = round(float(lay[k].mean()), 2)
    health["momentum_summary"]["Q5_Q1"] = round(float(lay["Q5"].mean() - lay["Q1"].mean()), 2)
    health["momentum_summary"]["mono"] = bool(
        lay[["Q1", "Q2", "Q3", "Q4", "Q5"]].mean().is_monotonic_increasing)
json.dump(health, open(f"{DATA}/health.json", "w"), ensure_ascii=False)
print("dates", health["n_dates"], "layers", len(lay))
for k, v in health["factors"].items():
    print(f"  {k:10s} IC20 {v['ic20_mean']}  win {v['ic20_win']}  IC60 {v['ic60_mean']}  win60 {v['ic60_win']}")
print("momentum", health["momentum_summary"])
