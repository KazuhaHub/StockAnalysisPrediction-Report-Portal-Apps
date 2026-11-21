"""决定性检验：螺旋的日频指纹（下跌→净偿还→再下跌）

空方硬条件：若不存在「净偿还领先加速下跌」且「反馈强度随约束收紧单调上升」，
则不应把观测到的现象归因为融资抢跑螺旋。
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "out"

m = pd.read_parquet(ROOT / "data/margin_hist.parquet")
b = pd.read_parquet(ROOT / "data/bars.parquet")
m["dt"] = pd.to_datetime(m.date, format="%Y%m%d")
b["dt"] = pd.to_datetime(b.date)
all_dt = b.dt.sort_values().unique()
codes = sorted(set(m.code) & set(b.code))

rz = m.pivot(index="dt", columns="code", values="rz").reindex(all_dt)[codes]
close = b.pivot(index="dt", columns="code", values="close").reindex(all_dt)[codes]
amt = b.pivot(index="dt", columns="code", values="amount").reindex(all_dt)[codes]
C, A, RZ = close.values, amt.values, rz.values
N, M = C.shape

ret = np.full_like(C, np.nan); ret[1:] = C[1:] / C[:-1] - 1
ret[(A == 0) | ~np.isfinite(A)] = np.nan
ret = np.clip(ret, -0.25, 0.25)          # 涨跌停外的异常值裁掉（前复权断点）
drz = np.full_like(RZ, np.nan)
drz[1:] = RZ[1:] / np.maximum(RZ[:-1], 1e-8) - 1
drz = np.clip(drz, -0.5, 0.5)

# 20 日均额（用于放量倍数）
amt20 = np.full_like(A, np.nan)
cs = np.vstack([np.zeros((1, M)), np.cumsum(np.nan_to_num(A, nan=0.0), axis=0)])
amt20[19:] = (cs[20:] - cs[:-20]) / 20
vr = A / np.maximum(amt20, 1e-8)

# 市场日收益（横截面中位数）用于剔除系统性去杠杆
with np.errstate(all="ignore"):
    mkt = np.nan_to_num(np.nanmedian(ret, axis=1), nan=0.0)
exret = ret - mkt[:, None]

# buf_liq（复用 panel 的 ti 索引，按 dt 对齐）
P = pd.read_parquet(OUT / "panel.parquet")
bl = P.pivot_table(index="date", columns="code", values="buf_liq", aggfunc="first")
bl = bl.reindex(index=all_dt, columns=codes).values

# 固定分组：首日 buy_share / ratio 前 30%、后 30%
t0 = P.date.min()
snap = P[P.date == t0]
hi = set(snap[snap.buy_share >= snap.buy_share.quantile(.70)].code)
lo = set(snap[snap.buy_share <= snap.buy_share.quantile(.30)].code)
col_idx = {c: j for j, c in enumerate(codes)}
hi_j = np.array([col_idx[c] for c in hi if c in col_idx])
lo_j = np.array([col_idx[c] for c in lo if c in col_idx])

edges = [0, 20, 25, 30, 33, 36, 39, 42, 100]
LAB = ["[0,20)", "[20,25)", "[25,30)", "[30,33)", "[33,36)", "[36,39)", "[39,42)", "[42,+)"]

def corr(a, b):
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 200:
        return np.nan, 0
    return float(np.corrcoef(a[ok], b[ok])[0, 1]), int(ok.sum())

def ols_slope(y, x, ctl):
    ok = np.isfinite(y) & np.isfinite(x) & np.isfinite(ctl)
    if ok.sum() < 300:
        return np.nan, 0
    X = np.column_stack([np.ones(ok.sum()), x[ok], ctl[ok]])
    be = np.linalg.lstsq(X, y[ok], rcond=None)[0]
    return float(be[1]), int(ok.sum())

print("=== 1. 日收益一阶自相关 corr(ret_t, ret_{t+1})，按距平仓线位置 ===")
print("    螺旋预测：贴线区应显著更负（跌了继续跌），且高融资组更负")
print(f"{'bin':>10} | {'高融资':>18s} | {'低融资':>18s} | {'高-低':>8s}")
for i in range(len(edges) - 1):
    mask = (bl >= edges[i]) & (bl < edges[i + 1])
    out = []
    for js in (hi_j, lo_j):
        sel = mask.copy(); sel[:, :] = False
        sel[:, js] = mask[:, js]
        a = exret[:-1][sel[:-1]]
        c = exret[1:][sel[1:]]
        # 需要同位置对齐
        a2 = exret[:-1].copy(); c2 = exret[1:].copy()
        m2 = sel[1:] & sel[:-1] if False else (mask[:-1][:, js], None)
        # 简化：直接在 js 列上算
        A_ = (bl[:-1][:, js] >= edges[i]) & (bl[:-1][:, js] < edges[i + 1])
        x = exret[:-1][:, js][A_]
        y = exret[1:][:, js][A_]
        out.append(corr(x, y))
    print(f"{LAB[i]:>10} | {out[0][0]:+.4f} (n={out[0][1]:>6d}) | {out[1][0]:+.4f} (n={out[1][1]:>6d}) | {out[0][0]-out[1][0]:+.4f}")

print("\n=== 2. 净偿还 → 次日收益（控制当日收益），系数 ×100 ===")
print("    螺旋预测：应为负（今日还款多 → 明日跌），且贴线区更负")
print(f"{'bin':>10} | {'高融资':>16s} | {'低融资':>16s}")
for i in range(len(edges) - 1):
    cells = []
    for js in (hi_j, lo_j):
        A_ = (bl[:-1][:, js] >= edges[i]) & (bl[:-1][:, js] < edges[i + 1])
        y = exret[1:][:, js][A_]
        x = drz[:-1][:, js][A_]
        c = exret[:-1][:, js][A_]
        s, n = ols_slope(y, x, c)
        cells.append((s * 100, n))
    print(f"{LAB[i]:>10} | {cells[0][0]:+7.3f} (n={cells[0][1]:>6d}) | {cells[1][0]:+7.3f} (n={cells[1][1]:>6d})")

print("\n=== 3. 昨日收益 → 今日净偿还，系数 ×100（反馈环前半段）===")
print("    螺旋预测：应为正（昨跌→今还款），且贴线区更强")
print(f"{'bin':>10} | {'高融资':>16s} | {'低融资':>16s}")
for i in range(len(edges) - 1):
    cells = []
    for js in (hi_j, lo_j):
        A_ = (bl[:-1][:, js] >= edges[i]) & (bl[:-1][:, js] < edges[i + 1])
        y = drz[:-1][:, js][A_]
        x = exret[:-2][:, js][A_] if False else exret[:-1][:, js][A_]
        # 用前一日收益作解释变量（lag1）
        lag = np.full_like(exret, np.nan); lag[1:] = exret[:-1]
        x = lag[:-1][:, js][A_]
        c = exret[:-1][:, js][A_]
        s, n = ols_slope(y, x, c)
        cells.append((s * 100, n))
    print(f"{LAB[i]:>10} | {cells[0][0]:+7.3f} (n={cells[0][1]:>6d}) | {cells[1][0]:+7.3f} (n={cells[1][1]:>6d})")

print("\n=== 4. 大跌日的放量倍数（当日收益 < -3% 时，成交额/20日均额）===")
print("    螺旋预测：贴线区高融资股应显著放量")
print(f"{'bin':>10} | {'高融资':>16s} | {'低融资':>16s}")
for i in range(len(edges) - 1):
    cells = []
    for js in (hi_j, lo_j):
        A_ = ((bl[:, js] >= edges[i]) & (bl[:, js] < edges[i + 1])
              & (exret[:, js] < -0.03) & np.isfinite(vr[:, js]))
        v = vr[:, js][A_]
        cells.append((float(np.median(v)) if len(v) > 50 else np.nan, len(v)))
    print(f"{LAB[i]:>10} | {cells[0][0]:7.2f} (n={cells[0][1]:>6d}) | {cells[1][0]:7.2f} (n={cells[1][1]:>6d})")
