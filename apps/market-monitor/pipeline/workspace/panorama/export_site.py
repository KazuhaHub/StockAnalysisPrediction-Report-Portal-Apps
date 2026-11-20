"""导出前端数据：列式压缩 + 数值定标，生成 site/data.js。"""
import json
import os

import numpy as np
import pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(D, "data")
SITE = os.path.join(D, "site")
os.makedirs(SITE, exist_ok=True)

m = pd.read_parquet(f"{DATA}/master_full.parquet")
V = pd.read_parquet(f"{DATA}/valuation.parquet")
for _k in V.columns:
    m["v_" + _k] = V[_k].values
m["implied_g"] = V["IMP_G"].values
meta = json.load(open(f"{DATA}/site_payload.json"))["meta"]
factors = json.load(open(f"{DATA}/site_payload.json"))["factors"]
strategies = json.load(open(f"{DATA}/site_payload.json"))["strategies"]
methods = json.load(open(f"{DATA}/site_payload.json"))["methods"]
health = json.load(open(f"{DATA}/health.json"))
market = json.load(open(f"{DATA}/market.json"))
names = {k: v["name"] for k, v in json.load(
    open(os.path.expanduser("~/MarketData/meta.json")))["stocks"].items()}
# 全市场名称兜底：本地行情库只覆盖 3,578 只，其余用 akshare 全量代码名称表补齐
_cn = pd.read_csv(f"{DATA}/code_name.csv", dtype={"code": str})
_cn["code"] = _cn["code"].str.zfill(6)
for _c, _n in zip(_cn["code"], _cn["name"]):
    if _c not in names:
        names[_c] = str(_n)
def _clean(x):
    return " ".join(str(x).replace("\u3000", " ").split()) if x else ""
m["name"] = m["symbol"].map(names).map(_clean).fillna("")
m["mktcap_yi"] = m["mktcap"] / 1e8

MID = [x["id"] for x in methods]
COLS = [
    ("symbol", "s", 0), ("name", "s", 0), ("sw1", "s", 0), ("board", "s", 0),
    ("price", "f", 2), ("mktcap_yi", "f", 1), ("pe", "f", 1), ("pb", "f", 2),
    ("ps", "f", 2), ("pcf", "f", 1), ("eps_ttm", "f", 2), ("bps", "f", 2),
    ("roe", "f", 1), ("roa", "f", 1), ("gross_margin", "f", 1), ("net_margin", "f", 1),
    ("rev_yoy", "f", 1), ("np_yoy", "f", 1), ("rev_cagr3", "f", 1), ("np_cagr3", "f", 1),
    ("payout", "f", 1), ("div_yield", "f", 2), ("ocr", "f", 2), ("div_cover", "f", 2),
    ("mom_12_1", "f", 3), ("ret_1m", "f", 3), ("ret_3m", "f", 3), ("ret_12m", "f", 3),
    ("vol_ann", "f", 3), ("beta252", "f", 2), ("ma_align", "f", 0), ("dist_high", "f", 3),
    ("turnover_20", "f", 4), ("pe_pct", "f", 3), ("pb_pct", "f", 3),
    ("pe_med", "f", 1), ("pb_med", "f", 2), ("ind_pe", "f", 1), ("ind_pb", "f", 2),
    ("ke", "f", 4), ("g1", "f", 4), ("n_methods", "f", 0), ("composite", "f", 2),
    ("upside", "f", 3), ("disp", "f", 3), ("label", "s", 0), ("quad", "s", 0),
    ("profile", "s", 0), ("resonance", "f", 1),
    ("s_value", "f", 1), ("s_growth", "f", 1), ("s_cyclical", "f", 1),
    ("s_dividend", "f", 1), ("s_momentum", "f", 1), ("s_quality", "f", 1),
    ("implied_g", "f", 1),
] + [("v_" + k, "f", 1) for k in MID]

rows = []
for _, r in m.iterrows():
    row = []
    for c, t, nd in COLS:
        v = r.get(c)
        if t == "s":
            row.append("" if (v is None or (isinstance(v, float) and not np.isfinite(v))) else str(v))
        else:
            if v is None or not np.isfinite(v) if isinstance(v, float) else (v is None):
                row.append(None)
            else:
                try:
                    row.append(round(float(v), nd) if nd else int(round(float(v))))
                except Exception:
                    row.append(None)
    rows.append(row)

# ------------------------------------------------------------------ 行业层得分
# 个股打分用的是「行业内分位」，同行业内部均值恒等于 50 分——这个口径没法比行业。
# 行业榜单独用「全市场分位」重算一遍同一套权重，才具备横向可比性。
MKP = {}
for f in factors:
    _v = pd.to_numeric(m.get(f"raw_{f['id']}"), errors="coerce")
    if f["dir"] < 0:
        _v = -_v
    MKP[f["id"]] = (_v.rank(pct=True, method="average") * 100).where(_v.notna())
_volp = m["vol_ann"].rank(pct=True) * 100
for _k, _s in strategies.items():
    _num = pd.Series(0.0, index=m.index)
    _den = pd.Series(0.0, index=m.index)
    _tot = float(sum(_s["w"].values()))
    for _fid, _w in _s["w"].items():
        _col = MKP.get(_fid)
        if _col is None:
            continue
        _num = _num.add(_col.fillna(0) * _w, fill_value=0)
        _den = _den.add(_col.notna().astype(float) * _w, fill_value=0)
    _cov = _den / _tot
    _raw = _num / _den.replace(0, np.nan)
    _anchor = max(_s["w"], key=lambda x: _s["w"][x])
    if _anchor in MKP:
        _raw = _raw.where(MKP[_anchor].notna())
    _pen = 8 * (1 - _cov) + 0.06 * (_volp.fillna(50) - 75).clip(lower=0)
    m["mk_" + _k] = (_raw - _pen).round(1)

# 行业聚合
def agg(g):
    return {
        "n": int(len(g)),
        "pe": round(float(g["pe"][(g["pe"] > 0) & (g["pe"] < 200)].median()), 1) if ((g["pe"] > 0) & (g["pe"] < 200)).any() else None,
        "pb": round(float(g["pb"][(g["pb"] > 0) & (g["pb"] < 30)].median()), 2) if ((g["pb"] > 0) & (g["pb"] < 30)).any() else None,
        "s_value": round(float(g["mk_value"].mean()), 1),
        "s_growth": round(float(g["mk_growth"].mean()), 1),
        "s_cyclical": round(float(g["mk_cyclical"].mean()), 1),
        "s_dividend": round(float(g["mk_dividend"].mean()), 1),
        "s_momentum": round(float(g["mk_momentum"].mean()), 1),
        "s_quality": round(float(g["mk_quality"].mean()), 1),
        "upside": round(float(g["upside"].median()), 3) if g["upside"].notna().any() else None,
        "mktcap": round(float(g["mktcap_yi"].sum()), 0),
    }


ind_rows = []
for k, g in m.groupby("sw1"):
    if str(k) in ("未分类", "其他", "nan", "None", ""):
        continue
    ind_rows.append({"name": k, **agg(g)})
ind_rows.sort(key=lambda x: -x["n"])

# 相关性（六策略截面相关）
SC = ["s_value", "s_growth", "s_cyclical", "s_dividend", "s_momentum", "s_quality"]
corr = m[SC].corr().round(3).values.tolist()
# 交集矩阵：同时进入两策略前 10% 的股票数
R = m[SC].rank(pct=True)
inter = [[int(((R[SC[i]] > 0.9) & (R[SC[j]] > 0.9)).sum()) for j in range(6)] for i in range(6)]

# 各方法的估值水平：估值/现价 中位（解释「绝对法 vs 相对法」的分歧有多大）
for _i, _k in enumerate(MID):
    _r = (V[_k] / m["price"]).replace([np.inf, -np.inf], np.nan)
    _r = _r[(_r > 0) & (_r < 20)]
    methods[_i]["med_ratio"] = round(float(_r.median()), 2) if len(_r) else None

payload = {
    "meta": {**meta,
             "n_industries": len(ind_rows),
             "corr": corr,
             "inter": inter,
             "strategy_names": [strategies[k]["name"] for k in
                                ["value", "growth", "cyclical", "dividend", "momentum", "quality"]]},
    "factors": factors,
    "strategies": strategies,
    "methods": methods,
    "health": health,
    "market": {k: v for k, v in market.items() if k in
               ("asof", "n_stocks", "n_priced", "median_pe", "median_pb",
                "above_ma120_pct", "above_ma250_pct", "breadth_60", "breadth_250", "ew_index")},
    "industries": ind_rows,
    "cols": [c for c, _, _ in COLS],
    "types": [t for _, t, _ in COLS],
    "rows": rows,
    "pct": json.load(open(f"{DATA}/site_payload.json"))["pct"],
    "diff": (json.load(open(f"{DATA}/diff.json")) if os.path.exists(f"{DATA}/diff.json")
             else {"first": True}),
}

with open(f"{SITE}/data.js", "w", encoding="utf-8") as f:
    f.write("window.PANORAMA=")
    json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    f.write(";")

print("rows", len(rows), "cols", len(COLS),
      "data.js MB", round(os.path.getsize(f"{SITE}/data.js") / 1e6, 2))
