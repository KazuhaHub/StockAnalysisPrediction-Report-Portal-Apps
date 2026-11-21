"""最后三刀：
  (1) ε 残差：把 buf 里「纯价格」能解释的部分回归掉，看剩下的「融资进场时点信息」是否还有增量预测力
  (2) 常数安慰剂：把 0.578 换成 0.40/0.50/0.667/0.75，看所谓的「区」是否等距跟随
  (3) 纯价格成本线安慰剂：用成交量加权均价（与融资买入额无关）代替成本线，看曲线是否复现
  (4) 线性 vs 变点：buf→未来收益是否只是单调线性，没有跳变
  (5) 偿还口径预检：rz_repay 与 rz_{t-1}+rz_buy_t-rz_t 是否一致
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "out"
P = pd.read_parquet(OUT / "panel.parquet").replace([np.inf, -np.inf], np.nan)
P["logamt"] = np.log(P.amt20.clip(lower=1))
P["crash"] = (P.exret5 <= -0.08).astype(float)

t0 = P.date.min()
snap = P[P.date == t0]
hi = set(snap[snap.buy_share >= snap.buy_share.quantile(.70)].code)
lo = set(snap[snap.buy_share <= snap.buy_share.quantile(.30)].code)
Q = P[P.code.isin(hi | lo)].copy()
Q["high"] = Q.code.isin(hi).astype(float)

# ---------------- (5) 偿还口径 ----------------
print("=== (5) 偿还口径预检：rz_repay 与 rz_{t-1}+rzbuy_t-rz_t ===")
m = pd.read_parquet(ROOT / "data/margin_hist.parquet").sort_values(["code", "date"])
g = m.groupby("code", sort=False)
implied = (g.rz.shift(1) + m.rz_buy - m.rz)
rep = m.rz_repay
ok = rep.notna() & implied.notna() & (g.rz.shift(1).notna())
d = (rep[ok] - implied[ok]).abs()
rel = d / np.maximum(implied[ok].abs(), 1)
print(f"  可比 {ok.sum():,} 行；绝对差中位 {d.median():,.0f} 元，相对差中位 {rel.median():.4f}")
print(f"  相关系数 {np.corrcoef(rep[ok], implied[ok])[0,1]:.4f}")
print("  口径结论：", "rz 为本金、偿还可直接用余额差推断" if rel.median() < .25 else "需谨慎，两者不一致")

# ---------------- (1) ε 残差 ----------------
print("\n=== (1) ε 残差：逐日横截面回归 buf ~ 纯价格特征，取残差 ===")
FEATS = ["ret20", "ret60", "ret5", "vol20", "logamt"]
Q = Q.dropna(subset=["buf_liq"] + FEATS + ["exret5", "crash"])
Q = Q[np.isfinite(Q[FEATS].values).all(axis=1)]
Q["vol20"] = Q.vol20.clip(0, 0.20)
eps = np.full(len(Q), np.nan)
for dt, idx in Q.groupby("date").indices.items():
    s = Q.iloc[idx]
    X = np.column_stack([np.ones(len(s))] + [s[c].values for c in FEATS])
    y = s.buf_liq.values
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    if ok.sum() < 200:
        continue
    be = np.linalg.lstsq(X[ok], y[ok], rcond=None)[0]
    eps[idx[ok]] = y[ok] - X[ok] @ be
Q["eps"] = eps
Q = Q.dropna(subset=["eps"])
Q["epsc"] = Q.eps - Q.eps.mean()
Q["bufc"] = Q.buf_liq - Q.buf_liq.mean()
Q["epsc2"] = Q.epsc ** 2
print(f"  ε 标准差 {Q.eps.std():.2f}pp；与 buf 相关 {np.corrcoef(Q.eps, Q.buf_liq)[0,1]:.4f}（构造上应≈0）")

def dem(v, ci, di, nc, nd, it=8):
    v = np.asarray(v, float).copy()
    cc = np.bincount(ci, minlength=nc).astype(float); dc = np.bincount(di, minlength=nd).astype(float)
    for _ in range(it):
        v -= (np.bincount(ci, weights=v, minlength=nc) / np.maximum(cc, 1))[ci]
        v -= (np.bincount(di, weights=v, minlength=nd) / np.maximum(dc, 1))[di]
    return v

def fe(d, ycol, xcols):
    ci = pd.Categorical(d.code).codes; di = pd.Categorical(d.date).codes
    nc, nd = ci.max()+1, di.max()+1
    Y = dem(d[ycol].values, ci, di, nc, nd)
    X = np.column_stack([dem(d[c].values, ci, di, nc, nd) for c in xcols])
    be = np.linalg.lstsq(X, Y, rcond=None)[0]
    ss = 1 - ((Y - X@be)**2).sum() / max((Y**2).sum(), 1e-12)
    return dict(zip(xcols, be)), ss, len(d)

for ycol in ["exret5", "crash"]:
    r0, s0, _ = fe(Q, ycol, ["bufc"])
    r1, s1, _ = fe(Q, ycol, ["bufc", "epsc"])
    print(f"  {ycol:8s}: 仅buf R²={s0:.5f}  +ε 后 R²={s1:.5f}  增量={ (s1-s0)*100:.4f}pp"
          f"   ε系数={r1['epsc']:.6g}  buf系数={r1['bufc']:.6g}")

# 按 ε 分位看快速下跌率（ε 正 = 融资盘成本比纯价格推出来的更高 = 追高套牢）
Q["eq"] = pd.qcut(Q.eps, 10, labels=False)
print("\n  ε 十分位 → 快速下跌率 / 未来5日超额收益（高融资组 / 低融资组）")
for k in range(10):
    s = Q[Q["eq"] == k]
    a = s[s.high == 1]; b = s[s.high == 0]
    print(f"   Q{k}: ε中位{s.eps.median():+6.2f}pp | crash 高{a.crash.mean()*100:5.2f}% 低{b.crash.mean()*100:5.2f}%"
          f" | exret5 高{a.exret5.mean()*100:+5.2f}% 低{b.exret5.mean()*100:+5.2f}%")

# ---------------- (2) 常数安慰剂 ----------------
print("\n=== (2) 常数安慰剂：改 K 后，「高融资−低融资」差值曲线形状是否等距跟随 ===")
k_ratio = np.clip(0.578 / (1 - Q.buf_liq.values / 100), 1e-6, None)  # k = P/cost
for K in [0.40, 0.50, 0.578, 0.667, 0.75]:
    bufK = (1 - K / k_ratio) * 100
    # 用固定的「距线 20~30%」窗口，看各 K 下窗口内的 high-low 差
    win = (bufK >= 20) & (bufK < 30)
    a = Q[win & (Q.high == 1)].exret5.mean() * 100
    b = Q[win & (Q.high == 0)].exret5.mean() * 100
    # 对应的浮亏深度区间（这才是可比的物理位置）
    pl = ((K / (1 - np.array([0.20, 0.30])) - 1) * 100)
    print(f"  K={K:.3f}: 「距线20~30%」对应浮亏 {pl[0]:+.1f}%~{pl[1]:+.1f}%"
          f" | 窗口内 高{a:+.2f}% 低{b:+.2f}% 差{a-b:+.2f}pp | n={win.sum():,}")

# ---------------- (3) 纯价格成本线安慰剂 ----------------
print("\n=== (3) 纯价格成本线：用成交额加权均价代替 rzbuy 加权，重算 buf^P ===")
b = pd.read_parquet(ROOT / "data/bars.parquet")
b["dt"] = pd.to_datetime(b.date)
cl = b.pivot(index="dt", columns="code", values="close")
am = b.pivot(index="dt", columns="code", values="amount")
all_dt = cl.index.sort_values()
cl = cl.reindex(all_dt); am = am.reindex(all_dt)
codes = sorted(set(cl.columns) & set(P.code))
C = cl[codes].values; A = am[codes].values
decay = 0.5 ** (np.arange(60)[::-1] / 30.0)
costP = np.full_like(C, np.nan)
for t in range(59, len(all_dt)):
    w = A[t-59:t+1] * decay[:, None]
    c = C[t-59:t+1]
    ok = np.isfinite(c) & np.isfinite(w)
    w = np.where(ok, w, 0); c0 = np.where(np.isfinite(c), c, 0)
    den = w.sum(axis=0)
    costP[t] = np.where(den > 0, (w*c0).sum(axis=0)/np.maximum(den, 1e-12), np.nan)
kp = C / costP
bufP = (1 - 0.578 / kp) * 100
dt_idx = {d: i for i, d in enumerate(all_dt)}
ci = {c: j for j, c in enumerate(codes)}
rows = Q.date.map(dt_idx).values
cj = Q.code.map(ci).values
ok = np.isfinite(rows) & np.isfinite(cj)
vals = np.full(len(Q), np.nan)
vals[ok] = bufP[rows[ok].astype(int), cj[ok].astype(int)]
Q["bufP"] = vals
Q["bP"] = pd.cut(Q.bufP, [0,10,20,30,36,42,100], labels=False)
print("  分箱 → 快速下跌率（高融资 / 低融资），用纯价格成本线")
for k in sorted(Q.bP.dropna().unique()):
    s = Q[Q.bP == k]
    a = s[s.high == 1].crash.mean()*100; bb = s[s.high == 0].crash.mean()*100
    print(f"   bufP箱{k}: 高{a:5.2f}% 低{bb:5.2f}% 差{a-bb:+5.2f}pp  n={len(s):,}")
print(f"  buf 与 bufP 的 Spearman 相关: {Q[['buf_liq','bufP']].corr(method='spearman').iloc[0,1]:.4f}")

# ---------------- (4) 线性 vs 变点 ----------------
print("\n=== (4) buf→未来收益：线性 vs 分箱（是否值得设「区间」）===")
Q["bufc2"] = Q.bufc ** 2
Q["bb"] = pd.cut(Q.buf_liq, [0,10,15,20,25,30,33,36,39,42,45,100], labels=False)
bincols = []
for k in sorted(Q.bb.dropna().unique()):
    if k == 8: continue
    c = f"z{k}"; Q[c] = (Q.bb == k).astype(float); bincols.append(c)
for ycol in ["exret5", "crash"]:
    _, sl, n = fe(Q, ycol, ["bufc"])
    _, sq, _ = fe(Q, ycol, ["bufc", "bufc2"])
    _, sb, _ = fe(Q, ycol, bincols)
    print(f"  {ycol:8s}: 线性R²={sl:.5f}  加二次项={sq:.5f}  分箱={sb:.5f}"
          f"  分箱相对线性增益={(sb-sl)*100:.4f}pp  (n={n:,})")
print("  注：分箱参数 10 个 vs 线性 1 个，增益需远大才配称「独立的高风险区」")
