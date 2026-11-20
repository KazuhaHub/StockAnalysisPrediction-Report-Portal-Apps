"""构建 point-in-time 面板，用于检验「融资盘抢跑螺旋」假说。

无未来函数：所有 t 时点特征只用 <= t 的数据；因变量只用 > t 的数据。
输出 analysis/out/panel.parquet（长表，每行 = 一个 股票×日期 观测）
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "out"
OUT.mkdir(parents=True, exist_ok=True)

K_LIQ = 0.578
K_CALL = 0.667
HALF = 30          # 成本估算半衰期（交易日），与 build_data.py 一致
WIN = 60           # 成本估算回看窗口
FWD = 5            # 前瞻窗口

# ---------------- 载入并对齐宽表 ----------------
m = pd.read_parquet(ROOT / "data/margin_hist.parquet")
b = pd.read_parquet(ROOT / "data/bars.parquet")
m["dt"] = pd.to_datetime(m.date, format="%Y%m%d")
b["dt"] = pd.to_datetime(b.date)
assert not m.duplicated(["dt", "code"]).any(), "两融明细有重复 (date,code)"
assert not b.duplicated(["dt", "code"]).any(), "行情有重复 (date,code)"

rz = m.pivot(index="dt", columns="code", values="rz").astype(float)
rzbuy = m.pivot(index="dt", columns="code", values="rz_buy").astype(float)
close = b.pivot(index="dt", columns="code", values="close").astype(float)
amt = b.pivot(index="dt", columns="code", values="amount").astype(float)
low = b.pivot(index="dt", columns="code", values="low").astype(float)

all_dt = close.index.union(rz.index).sort_values()
codes = rz.columns.intersection(close.columns).intersection(amt.columns).sort_values()
close = close.reindex(all_dt)[codes]
amt = amt.reindex(all_dt)[codes]
low = low.reindex(all_dt)[codes]
RZ = rz.reindex(all_dt)[codes].values
RB = rzbuy.reindex(all_dt)[codes].values
C, A, L = close.values, amt.values, low.values
N, M = C.shape
print(f"dates={len(all_dt)} {all_dt[0].date()}~{all_dt[-1].date()}  codes={len(codes)}")

# ---------------- 基础量（只依赖 <=t） ----------------
ret1 = np.full_like(C, np.nan)
ret1[1:] = C[1:] / C[:-1] - 1
zero_amt = (A == 0) | ~np.isfinite(A)      # 停牌/无成交，收益不可信
ret1[zero_amt] = np.nan

with np.errstate(all="ignore"):
    mkt_ret = np.nanmedian(ret1, axis=1)
mkt_ret = np.nan_to_num(mkt_ret, nan=0.0)
mkt_idx = np.cumprod(1 + mkt_ret)

def rmean(x, w):
    out = np.full_like(x, np.nan)
    for t in range(w - 1, x.shape[0]):
        with np.errstate(all="ignore"):
            out[t] = np.nanmean(x[t - w + 1:t + 1], axis=0)
    return out

def rstd(x, w):
    out = np.full_like(x, np.nan)
    for t in range(w - 1, x.shape[0]):
        with np.errstate(all="ignore"):
            out[t] = np.nanstd(x[t - w + 1:t + 1], axis=0, ddof=1)
    return out

def rsum(x, w):
    out = np.full_like(x, np.nan)
    v = np.nan_to_num(x, nan=0.0)
    cs = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(v, axis=0)])
    out[w - 1:] = cs[w:] - cs[:-w]
    return out

vol20 = rstd(ret1, 20)
amt20 = rmean(amt.values, 20)
amt5 = rmean(amt.values, 5)
ret20 = np.full_like(C, np.nan); ret20[20:] = C[20:] / C[:-20] - 1
ret5 = np.full_like(C, np.nan);  ret5[5:] = C[5:] / C[:-5] - 1
ret60 = np.full_like(C, np.nan); ret60[60:] = C[60:] / C[:-60] - 1

# ---------------- 成本线（指数衰减加权，只用 <=t） ----------------
decay = 0.5 ** (np.arange(WIN)[::-1].astype(float) / HALF)
cost = np.full_like(C, np.nan)
for t in range(WIN - 1, N):
    w = RB[t - WIN + 1:t + 1] * decay[:, None]
    c = C[t - WIN + 1:t + 1]
    ok = np.isfinite(c) & np.isfinite(w) & (w > 0)
    w = np.where(ok, w, 0.0)
    c0 = np.where(np.isfinite(c), c, 0.0)
    num = (w * c0).sum(axis=0)
    den = w.sum(axis=0)
    cost[t] = np.where(den > 0, num / np.maximum(den, 1e-12), np.nan)

k = C / cost
pnl = (k - 1) * 100
buf_liq = (1 - K_LIQ / k) * 100
buf_call = (1 - K_CALL / k) * 100

# ---------------- 杠杆强度（point-in-time） ----------------
lev = RZ / np.maximum(amt5, 1e-8)           # 融资余额 / 5日均额 = 杠杆沉淀天数
buy_share = rsum(RB, 5) / np.maximum(rsum(A, 5), 1e-8) * 100

# ---------------- 因变量（只用 >t） ----------------
fwd = np.full_like(C, np.nan); fwd[:-FWD] = C[FWD:] / C[:-FWD] - 1
mkt_fwd = np.full(N, np.nan); mkt_fwd[:-FWD] = mkt_idx[FWD:] / mkt_idx[:-FWD] - 1
exret5 = fwd - mkt_fwd[:, None]

fut_min = np.full_like(C, np.nan)
for t in range(N - FWD):
    with np.errstate(all="ignore"):
        fut_min[t] = np.nanmin(L[t + 1:t + FWD + 1], axis=0)
dd5 = fut_min / C - 1
mkt_dd = np.full(N, np.nan)
for t in range(N - FWD):
    with np.errstate(all="ignore"):
        mkt_dd[t] = np.nanmedian(dd5[t])
ex_dd5 = dd5 - mkt_dd[:, None]

z5 = exret5 / np.maximum(vol20 * np.sqrt(FWD), 1e-6)   # 波动率标准化

drz5 = np.full_like(RZ, np.nan)
drz5[:-FWD] = RZ[FWD:] / np.maximum(RZ[:-FWD], 1e-8) - 1

amt_fwd5 = np.full_like(A, np.nan)
amt_fwd5[:-FWD] = rsum(A, FWD)[FWD:] / FWD
vratio = amt_fwd5 / np.maximum(amt20, 1e-8)

# ---------------- 组装长表 ----------------
margin_dates = set(rz.index)
rows = []
for ti, dt in enumerate(all_dt):
    if dt not in margin_dates or ti < WIN or ti + FWD >= N:
        continue
    rows.append(pd.DataFrame({
        "code": codes,
        "date": dt,
        "ti": ti,
        "close": C[ti], "cost": cost[ti], "pnl": pnl[ti],
        "buf_liq": buf_liq[ti], "buf_call": buf_call[ti],
        "lev": lev[ti], "buy_share": buy_share[ti],
        "ret20": ret20[ti], "ret5": ret5[ti], "ret60": ret60[ti],
        "vol20": vol20[ti], "amt20": amt20[ti],
        "exret5": exret5[ti], "ex_dd5": ex_dd5[ti], "z5": z5[ti],
        "drz5": drz5[ti], "vratio": vratio[ti], "mkt_fwd5": mkt_fwd[ti],
    }))

P = pd.concat(rows, ignore_index=True).replace([np.inf, -np.inf], np.nan)
P = P[np.isfinite(P.close) & np.isfinite(P.cost) & np.isfinite(P.exret5) & np.isfinite(P.lev)]
P = P[(P.close > 0) & (P.cost > 0) & (P.amt20 > 0) & (P.lev > 0)]
P = P[P.buf_liq.between(-60, 100)]
P = P.reset_index(drop=True)
P.to_parquet(OUT / "panel.parquet", index=False)
print(f"面板: {len(P):,} 行, {P.date.nunique()} 个交易日, {P.code.nunique()} 只票")
print(f"日期范围 {P.date.min().date()} ~ {P.date.max().date()}")
print(f"buf_liq 分位: {np.nanpercentile(P.buf_liq, [1,10,25,50,75,90,99]).round(1)}")
print(f"lev 分位: {np.nanpercentile(P.lev, [1,10,25,50,75,90,99]).round(2)}")
print(f"exret5 均值 {P.exret5.mean():.3f}  中位 {P.exret5.median():.3f}")
