"""构建主数据集：把 PIT 财务面板、行情快照、本地日线合成一张 master 表 + 量价特征 + 估值历史带。

产出：
  data/master.parquet        每票一行：财务、估值、市值、行业
  data/price_feat.parquet    每票一行：动量/波动/流动性/均线/回撤/Beta
  data/val_hist.parquet      每票：PE/PB 三年分位与中枢（月度采样）
  data/market.json           市场层 KPI 与宽度序列
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

D = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(D, "data")
from asof import asof_iso  # noqa: E402

ASOF = asof_iso()
START = "2023-06-01"

# ---------------------------------------------------------------- 财务
pan = pd.DataFrame(json.load(open(f"{DATA}/panel.json")))
pan["symbol"] = pan["symbol"].astype(str).str.zfill(6)
pan["rp"] = pan["report_period"].astype(str)
pan["avail"] = pan["available_at"].astype(str)
num_cols = ["revenue", "net_income", "operating_cf", "total_assets", "total_liabilities",
            "equity", "shares_outstanding", "eps", "bps", "ocfps", "roe", "roa",
            "gross_margin", "net_margin", "operating_margin", "asset_liability_ratio",
            "rev_yoy", "np_yoy", "ttm_net_income", "ttm_revenue", "inventory", "receivables"]
for c in num_cols:
    pan[c] = pd.to_numeric(pan[c], errors="coerce")

# 剔除退市整理板标的（名称以「退市」开头）：它们已不可投，留在池子里只会污染分位与行业均值
_nm = {}
_cn = pd.read_csv(f"{DATA}/code_name.csv", dtype={"code": str})
_cn["code"] = _cn["code"].str.zfill(6)
_nm.update(dict(zip(_cn["code"], _cn["name"].astype(str))))
_md_names = json.load(open(os.path.expanduser("~/MarketData/meta.json")))["stocks"]
_nm.update({k: str(v.get("name") or "") for k, v in _md_names.items()})
_dead = {k for k, v in _nm.items() if v.replace(" ", "").startswith("退市")}
if _dead:
    _n0 = pan["symbol"].nunique()
    pan = pan[~pan["symbol"].isin(_dead)].copy()
    print(f"剔除退市股 {_n0 - pan['symbol'].nunique()} 只")

pan = pan.sort_values(["symbol", "rp"])


def lag(series, n):
    return series.groupby(pan["symbol"]).shift(n)


# 自算同比（源端 yoy 只覆盖最近几期，滞后 8 期会全空），口径：同一季度同比
pan["rev_yoy_c"] = pan.groupby("symbol")["revenue"].pct_change(4) * 100
pan["np_yoy_c"] = pan.groupby("symbol")["net_income"].pct_change(4) * 100
pan["cfo_margin"] = pan["operating_cf"] / pan["revenue"].replace(0, np.nan) * 100

for n in (4, 6, 8):
    pan[f"np_yoy_l{n}"] = lag(pan["np_yoy_c"] if n == 8 else pan["np_yoy"], n)
    pan[f"rev_yoy_l{n}"] = lag(pan["rev_yoy_c"] if n == 8 else pan["rev_yoy"], n)
    pan[f"np_yoy_c_l{n}"] = lag(pan["np_yoy_c"], n)
    pan[f"rev_yoy_c_l{n}"] = lag(pan["rev_yoy_c"], n)
    pan[f"cfo_m_l{n}"] = lag(pan["cfo_margin"], n)
    pan[f"gm_l{n}"] = lag(pan["gross_margin"], n)
    pan[f"roe_l{n}"] = lag(pan["roe"], n)
    pan[f"fa_l{n}"] = lag(pan["total_assets"], n)

# ---------------------------------------------------------------- TTM 自算
# 数据源给的 ttm_net_income / ttm_revenue 在重整、借壳、大额非经常性损益样本上严重失真
# （000656 2026Q3 报 401 亿 TTM 净利，而同期累计利润只有 0.017 亿），
# 直接用会把 PE 顶到 0.27×，进而污染价值策略与 PE 相对估值。
# 改为自算：TTM = 本期累计 + 上年年报 − 上年同期累计；12 月期直接等于累计值。
pan["_m"] = pan["rp"].str[4:6].astype(int)
pan["_y"] = pan["rp"].str[:4].astype(int)


def _ttm_calc(col):
    key = pd.MultiIndex.from_arrays([pan["symbol"], pan["_y"], pan["_m"]])
    ser = pd.Series(pan[col].values, index=key)
    fy_key = pd.MultiIndex.from_arrays([pan["symbol"], pan["_y"] - 1, np.full(len(pan), 12)])
    sm_key = pd.MultiIndex.from_arrays([pan["symbol"], pan["_y"] - 1, pan["_m"]])
    prev_fy = ser.reindex(fy_key).values
    prev_sm = ser.reindex(sm_key).values
    calc = np.where(pan["_m"].values == 12, pan[col].values,
                    pan[col].values + prev_fy - prev_sm)
    return pd.Series(calc, index=pan.index)


for _c in ("net_income", "revenue"):
    _new = _ttm_calc(_c)
    _old = pd.to_numeric(pan[f"ttm_{_c}"], errors="coerce")
    _both = pd.DataFrame({"o": _old, "n": _new}).dropna()
    _k = len(_both)
    _med = float((_both["n"] / _both["o"].replace(0, np.nan)).median())
    _big = int(((_both["n"] - _both["o"]).abs() > (_both["n"].abs() * 0.15 + 1e7)).sum())
    print(f"TTM {_c}: 可比 {_k} 行，自算/源自 中位 {_med:.3f}，偏离 >15% 共 {_big} 行 → 采用自算值")
    pan[f"ttm_{_c}"] = _new.where(_new.notna(), _old)

# 12 月期的 TTM 每股值应与源 EPS 一致，用作量纲校验
_dec = pan[pan["_m"] == 12].copy()
_dec["eps_chk"] = _dec["ttm_net_income"] / _dec["shares_outstanding"].replace(0, np.nan)
_ok = (_dec["eps_chk"] - _dec["eps"]).abs() <= (_dec["eps"].abs() * 0.02 + 0.01)
print(f"年报期 TTM/股本 与源 EPS 一致率 {_ok.mean() * 100:.1f}%（{int(_ok.sum())}/{len(_dec)}）")

# 净资产为负时 ROE 无经济含义，置空
pan.loc[pd.to_numeric(pan["equity"], errors="coerce") <= 0, "roe"] = np.nan

# ---------------------------------------------------------------- 股本校正
# PIT 的 shares_outstanding 在少数科创板 / A+H / CDR 标的上量纲错乱
# （中芯国际差 35 倍、华虹宏力差 0.5 倍、九号公司差 10 倍），
# 会连带 eps / bps / 市值 / PE / PB 一起错。用腾讯快照的总市值反推真实股本，
# 再按「每股指标 × 老股本/新股本」等比校正，保持原始口径（归母）不变。
latest_rp = pan["rp"].max()
_tx = pd.read_csv(f"{DATA}/mktcap_tx.csv", dtype={"code": str})
_tx["code"] = _tx["code"].str.zfill(6)
_txsh = _tx.set_index("code")["tx_shares"]
_old = pan.loc[pan["rp"] == latest_rp].drop_duplicates("symbol").set_index("symbol")["shares_outstanding"]
_k = (_old / _txsh.reindex(_old.index)).replace([np.inf, -np.inf], np.nan)
_bad = _k[(_k - 1).abs() > 0.02].dropna()
print(f"股本校正 {len(_bad)} 只，倍数区间 {_bad.min():.3f} ~ {_bad.max():.2f}" if len(_bad) else "股本无需校正")
pan["_k"] = pan["symbol"].map(_k).fillna(1.0)
for _c in ("eps", "bps", "ocfps"):
    pan[_c] = pan[_c] * pan["_k"]
pan["shares_outstanding"] = pan["shares_outstanding"] / pan["_k"]
lat = pan[pan["rp"] == latest_rp].copy()          # 最新报告期横截面（2026Q3）
# 兜底：报告期缺失的票，用其最近一期
have = set(lat["symbol"])
rest = pan[~pan["symbol"].isin(have)].groupby("symbol").tail(1)
lat = pd.concat([lat, rest], ignore_index=True)
lat = lat.drop_duplicates("symbol", keep="last")

# ---------------------------------------------------------------- 行业
ind = pd.DataFrame(json.load(open(f"{DATA}/industry.json")))
ind["symbol"] = ind["symbol"].astype(str).str.zfill(6)
ind = ind.drop_duplicates("symbol")[["symbol", "industry_name", "industry_code"]]
ind.columns = ["symbol", "sw1", "sw1_code"]

# ---------------------------------------------------------------- 行情快照
q = json.load(open(f"{DATA}/quotes.json"))
qrows = []
for k, v in q.items():
    qrows.append({"symbol": str(k).zfill(6), "q_close": v.get("close"),
                  "q_amount": v.get("amount"), "q_date": str(v.get("time"))[:10]})
qt = pd.DataFrame(qrows)
qt["q_close"] = pd.to_numeric(qt["q_close"], errors="coerce")

m = lat.merge(ind, on="symbol", how="left").merge(qt, on="symbol", how="left")

# 补充最新横截面独有的科目（panel 未抓）
_fl = pd.DataFrame(json.load(open(f"{DATA}/fundamentals_latest.json")))
_fl["symbol"] = _fl["symbol"].astype(str).str.zfill(6)
_extra = ["current_assets", "current_liabilities", "fixed_assets", "inventory",
          "receivables", "operating_profit", "total_cf"]
for c in _extra:
    _fl[c] = pd.to_numeric(_fl[c], errors="coerce")
_fl = _fl.drop_duplicates("symbol")
m = m.merge(_fl[["symbol"] + _extra], on="symbol", how="left", suffixes=("", "_l"))
for c in _extra:
    if c + "_l" in m.columns:
        m[c] = m[c].fillna(m[c + "_l"])
        m.drop(columns=[c + "_l"], inplace=True)

# ---------------------------------------------------------------- 本地日线量价
import market_data as md

codes = sorted(m["symbol"].tolist())
bars = md.load(codes, start=START, end=ASOF)
bars["date"] = pd.to_datetime(bars["date"])
bars["price"] = bars["close"] / bars["factor"]        # 真实价
bars = bars[bars["volume"] > 0].copy()

px = bars.pivot(index="date", columns="code", values="price")
ret = px.pct_change()

def last_valid(s):
    return s.dropna().iloc[-1] if s.notna().any() else np.nan

feat = {}
feat["price_loc"] = px.apply(last_valid)
feat["px_nd"] = px.notna().sum()

def ret_n(n):
    return px.pct_change(n).apply(last_valid)

feat["ret_1m"] = ret_n(21)
feat["ret_3m"] = ret_n(63)
feat["ret_6m"] = ret_n(126)
feat["ret_12m"] = ret_n(252)
feat["mom_12_1"] = px.shift(21).pct_change(231).apply(last_valid)

ma20 = px.rolling(20).mean(); ma60 = px.rolling(60).mean()
ma120 = px.rolling(120).mean(); ma250 = px.rolling(250).mean()
feat["ma_align"] = ((px > ma20).astype(float) + (ma20 > ma60).astype(float)
                    + (ma60 > ma120).astype(float) + (ma120 > ma250).astype(float))
feat["ma_align"] = feat["ma_align"].apply(lambda s: s.dropna().iloc[-1] if s.notna().any() else np.nan)
feat["above_ma120"] = ((px.iloc[-1] > ma120.iloc[-1]).astype(float)).where(px.iloc[-1].notna())
feat["dist_high"] = (px.iloc[-1] / px.rolling(250, min_periods=60).max().iloc[-1] - 1)

v20 = ret.rolling(20).std(); v120 = ret.rolling(120).std(); v250 = ret.rolling(250).std()
feat["vol20"] = v20.apply(last_valid)
feat["vol120"] = v120.apply(last_valid)
feat["vol_ratio"] = (v20 / v120).apply(last_valid)
feat["vol_ann"] = v250.apply(last_valid) * np.sqrt(252)
feat["max_ret_20"] = ret.rolling(20).max().apply(last_valid)

# 换手代理：成交额 / 市值（市值用当期价×股本近似，做相对排序够用）
to = (bars.assign(turn=bars["amount"] / (bars["price"] * 1.0)))
turn = to.pivot_table(index="date", columns="code", values="turn", aggfunc="sum")
# 真实换手需要股本，这里用「成交额/价格」=成交股数，再除以总股本
sh = m.set_index("symbol")["shares_outstanding"]
turn_ratio = turn.div(sh.reindex(turn.columns), axis=1)
feat["turnover_20"] = turn_ratio.rolling(20).mean().apply(last_valid)
feat["turnover_chg"] = (turn_ratio.rolling(20).mean() / turn_ratio.rolling(120).mean()).apply(last_valid)

# 流动性：Amihud
amih = (ret.abs() / (to.pivot_table(index="date", columns="code", values="amount", aggfunc="sum") / 1e8))
feat["amihud"] = amih.rolling(60).mean().apply(last_valid)

# 自身市场（等权）Beta / 相对强弱
mkt = ret.mean(axis=1)
cov = ret.rolling(252, min_periods=120).cov(mkt)
var = mkt.rolling(252, min_periods=120).var()
beta = cov.div(var, axis=0)
feat["beta252"] = beta.apply(last_valid)
feat["rs_market_60"] = (px.pct_change(60)).apply(last_valid) - float(px.pct_change(60).apply(last_valid).median())

pf = pd.DataFrame(feat)
pf.index.name = "symbol"
pf = pf.reset_index()
pf["symbol"] = pf["symbol"].astype(str).str.zfill(6)

# ---------------------------------------------------------------- 估值历史带（月度采样）
# EPS_ttm 与 BPS 按公告日生效，向前填充到交易日
pan_eff = pan[pan["avail"].notna()].copy()
pan_eff["avail"] = pd.to_datetime(pan_eff["avail"])
pan_eff["eps_ttm"] = np.where(pan_eff["ttm_net_income"].notna() & (pan_eff["shares_outstanding"] > 0),
                              pan_eff["ttm_net_income"] / pan_eff["shares_outstanding"], np.nan)
pan_eff["eps_ttm"] = pan_eff["eps_ttm"].fillna(pan_eff["eps"].abs() * 0)  # 缺失保持 NaN
snap_dates = pd.date_range(START, ASOF, freq="ME")
snap_dates = [d for d in snap_dates if d <= pd.Timestamp(ASOF)]

rows_hist = []
for d in snap_dates:
    sub = pan_eff[pan_eff["avail"] <= d].groupby("symbol").tail(1)
    sub = sub.set_index("symbol")
    pday = px.loc[:d]
    if pday.empty:
        continue
    p = pday.iloc[-1]
    pe = p / sub["eps_ttm"].reindex(p.index)
    pb = p / (sub["bps"].reindex(p.index) / 1.0)
    df = pd.DataFrame({"date": d, "symbol": p.index, "pe": pe.values, "pb": pb.values})
    rows_hist.append(df)
hist = pd.concat(rows_hist, ignore_index=True)
hist.loc[(hist["pe"] <= 0) | (hist["pe"] > 500), "pe"] = np.nan
hist.loc[(hist["pb"] <= 0) | (hist["pb"] > 60), "pb"] = np.nan

def band(g, col):
    s = g.set_index("date")[col].dropna()
    if len(s) < 12:
        return pd.Series({col + "_now": s.iloc[-1] if len(s) else np.nan,
                          col + "_pct": np.nan, col + "_med": np.nan})
    cur = s.iloc[-1]
    return pd.Series({col + "_now": cur, col + "_pct": float((s <= cur).mean()),
                      col + "_med": float(s.median())})


vh = hist.groupby("symbol").apply(lambda g: pd.concat([band(g, "pe"), band(g, "pb")]))
vh = vh.reset_index()
vh["symbol"] = vh["symbol"].astype(str)

# ---------------------------------------------------------------- 合并
m["symbol"] = m["symbol"].astype(str).str.zfill(6)
m = m.merge(pf, on="symbol", how="left").merge(vh, on="symbol", how="left")

# 价格必须双来源：本地行情库只覆盖 3,486 只，快照覆盖 5,234 只，
# 只用 K 线会让约 1,900 只直接丢价（估值池缩水四成，且完全不报错）。
# 但混用必须校验两件事，否则「现价是今天的、涨跌幅是昨天的」会静默发生：
#   1) 快照日期 == ASOF（滞后就告警）
#   2) 同日重叠样本两边价格一致（复权断点/停牌会不一致）
_qd = pd.to_datetime(m["q_date"], errors="coerce")
_same_day = (_qd.dt.strftime("%Y-%m-%d") == ASOF).fillna(False)
_use_snap = m["q_close"].notna() & (m["q_close"] > 0) & _same_day
if os.environ.get("PANORAMA_PRICE") == "bars":
    _use_snap = _use_snap & False   # 回补历史日期时快照只有最新一天，强制走 K 线
m["price"] = m["q_close"].where(_use_snap, m["price_loc"])
m["price_src"] = np.where(_use_snap, "snap", np.where(m["price_loc"].notna(), "bar", ""))

_lag = int((_qd.notna() & (~_same_day)).sum())
if _lag:
    print(f"⚠️  快照日期不是 {ASOF} 的共 {_lag} 只 → 这些标的改走 K 线价（回补历史时属正常）")
_chk = pd.DataFrame({"bar": m["price_loc"], "snap": m["q_close"]}).dropna()
_chk = _chk[(_chk["bar"] > 0) & (_chk["snap"] > 0)]
if len(_chk):
    _dev = (_chk["snap"] / _chk["bar"] - 1).abs()
    print("价格来源：K线 %d 只 / 快照 %d 只；重叠 %d 只，中位偏差 %.3f%%，偏差 >2%% 共 %d 只"
          % (int((m["price_src"] == "bar").sum()), int((m["price_src"] == "snap").sum()),
             len(_dev), _dev.median() * 100, int((_dev > 0.02).sum())))
m["mktcap"] = m["price"] * m["shares_outstanding"]
m["float_flag"] = m["mktcap"].notna()

# TTM 口径
m["eps_ttm"] = np.where(m["shares_outstanding"] > 0, m["ttm_net_income"] / m["shares_outstanding"], np.nan)
m["pe"] = m["price"] / m["eps_ttm"]
m["pb"] = m["price"] / m["bps"]
m["ps"] = m["mktcap"] / m["ttm_revenue"]
m["ocf_ttm"] = m["ocfps"] * m["shares_outstanding"]
m["pcf"] = m["mktcap"] / m["ocf_ttm"]
m["ev"] = m["mktcap"] + m["total_liabilities"] - m["current_assets"].fillna(0)
m["ebit_ev"] = m["operating_profit"] / m["ev"]
m["div_yield"] = np.nan   # 由 seed 文件补充

m.to_parquet(f"{DATA}/master.parquet", index=False)
hist.to_parquet(f"{DATA}/val_hist.parquet", index=False)

# ---------------------------------------------------------------- 市场层
breadth = (px > ma120).astype(float)
bw = breadth.mean(axis=1)
above250 = (px > ma250).astype(float).mean(axis=1)
mkt_idx = (1 + mkt.fillna(0)).cumprod()
mk = {
    "asof": ASOF,
    "n_stocks": int(m["symbol"].nunique()),
    "n_priced": int(m["price"].notna().sum()),
    "median_pe": float(m["pe"].median()),
    "median_pb": float(m["pb"].median()),
    "above_ma120_pct": float(bw.iloc[-1] * 100),
    "above_ma250_pct": float(above250.iloc[-1] * 100),
    "breadth_60": [{"d": str(d.date()), "v": round(float(v) * 100, 2)}
                   for d, v in bw.tail(60).items()],
    "breadth_250": [{"d": str(d.date()), "v": round(float(v) * 100, 2)}
                    for d, v in above250.tail(250).items()],
    "ew_index": [{"d": str(d.date()), "v": round(float(v), 4)}
                 for d, v in mkt_idx.tail(250).items()],
    "n_local_bars": int(len(codes)),
}
json.dump(mk, open(f"{DATA}/market.json", "w"), ensure_ascii=False)
print("master rows", len(m), "priced", int(m['price'].notna().sum()))
print("median PE %.1f  PB %.2f  above120 %.1f%%" % (mk["median_pe"], mk["median_pb"], mk["above_ma120_pct"]))
