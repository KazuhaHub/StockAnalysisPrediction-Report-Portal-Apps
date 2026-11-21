"""v2：换分组口径 + 双向固定效应 + 安慰剂

v1 的 lev = rz/amt5 与 vol20 相关 -0.328，主要识别到「低波动冷门股」而非杠杆压力。
改用三种口径交叉验证：lev / buy_share / ratio(融资余额占流通市值)
并加 code FE + date FE，剥离股票类型与全市场去杠杆共同趋势。
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "out"
P = pd.read_parquet(OUT / "panel.parquet")

# ---- 融资余额 / 流通市值（spot 反推流通股数，前复权价近似，标注为近似口径）----
spot = pd.read_parquet(ROOT / "data/spot.parquet").set_index("code")
shares = (spot.fcap / spot.price).to_dict()
m = pd.read_parquet(ROOT / "data/margin_hist.parquet")
m["dt"] = pd.to_datetime(m.date, format="%Y%m%d")
rzmap = m.set_index(["dt", "code"]).rz
idx = pd.MultiIndex.from_arrays([P.date.values, P.code.values])
P["rz_yuan"] = rzmap.reindex(idx).values
P["fcap_t"] = P.code.map(shares).values * P.close.values
P["ratio"] = P.rz_yuan / P.fcap_t * 100
del m, rzmap

P["logamt"] = np.log(P.amt20.clip(lower=1))
P["crash"] = (P.exret5 <= -0.08).astype(float)
P["crash_z"] = (P.z5 <= -1.5).astype(float)
P["crash_dd"] = (P.ex_dd5 <= -0.10).astype(float)

edges = [0, 10, 15, 20, 25, 30, 33, 36, 39, 42, 45, 100]
P["bin"] = pd.cut(P.buf_liq, edges, right=False, labels=False)
P = P[P["bin"].notna()].copy()
P["bin"] = P["bin"].astype(int)
LAB = {0: "[0,10)", 1: "[10,15)", 2: "[15,20)", 3: "[20,25)", 4: "[25,30)",
       5: "[30,33)", 6: "[33,36)", 7: "[36,39)", 8: "[39,42)", 9: "[42,45)", 10: "[45,+)"}

t0 = P.date.min()
GRPDEF = {}
for name, col in [("lev", "lev"), ("buy", "buy_share"), ("ratio", "ratio")]:
    s = P[P.date == t0][["code", col]].dropna()
    hi, lo = s[col].quantile(0.70), s[col].quantile(0.30)
    GRPDEF[name] = (set(s[s[col] >= hi].code), set(s[s[col] <= lo].code), hi, lo)
    print(f"{name:6s} 首日切点 高>={hi:.2f} 低<={lo:.2f}  (高{len(GRPDEF[name][0])}只 / 低{len(GRPDEF[name][1])}只)")

# ---------------- 双向去均值 + code 聚类稳健标准误 ----------------
def dem(v, ci, di, nc, nd, iters=8):
    v = np.asarray(v, dtype=float).copy()
    cc = np.bincount(ci, minlength=nc).astype(float)
    dc = np.bincount(di, minlength=nd).astype(float)
    for _ in range(iters):
        v -= (np.bincount(ci, weights=v, minlength=nc) / np.maximum(cc, 1))[ci]
        v -= (np.bincount(di, weights=v, minlength=nd) / np.maximum(dc, 1))[di]
    return v

def fe_fit(df, ycol, xcols, want_se=True):
    d = df.dropna(subset=[ycol] + xcols)
    if len(d) < 400:
        return None, 0
    ci = pd.Categorical(d.code).codes
    di = pd.Categorical(d.date).codes
    nc, nd = ci.max() + 1, di.max() + 1
    Y = dem(d[ycol].values, ci, di, nc, nd)
    X = np.column_stack([dem(d[c].values, ci, di, nc, nd) for c in xcols])
    XtX = X.T @ X
    beta = np.linalg.solve(XtX + np.eye(X.shape[1]) * 1e-10, X.T @ Y)
    if not want_se:
        return dict(zip(xcols, beta)), len(d)
    u = Y - X @ beta
    xu = X * u[:, None]
    order = np.argsort(ci)
    xu_s, c_s = xu[order], ci[order]
    bounds = np.flatnonzero(np.diff(c_s)) + 1
    gs = np.zeros((X.shape[1], X.shape[1]))
    for seg in np.split(xu_s, bounds):
        s = seg.sum(axis=0)
        gs += np.outer(s, s)
    XtXi = np.linalg.inv(XtX + np.eye(X.shape[1]) * 1e-10)
    se = np.sqrt(np.maximum(np.diag(XtXi @ gs @ XtXi), 0))
    return {k: (v, s) for k, v, s in zip(xcols, beta, se)}, len(d)

BASE = ["ret20", "ret5", "vol20", "logamt"]
REF = 8
BINCOLS = []
for k in sorted(P["bin"].unique()):
    if k == REF:
        continue
    c = f"b{k}"
    P[c] = (P["bin"] == k).astype(float)
    BINCOLS.append(c)

print("\n=== 双向 FE：相对 [39,42) 基准箱的未来5日超额收益差（%）===")
print("    控制 ret20/ret5/vol20/log(amt20) + 股票FE + 日期FE；括号内为 code 聚类 t 值")
res = {}
for name, (hi, lo, _, _) in GRPDEF.items():
    for g, sset in [("high", hi), ("low", lo)]:
        r, n = fe_fit(P[P.code.isin(sset)], "exret5", BINCOLS + BASE)
        res[(name, g)] = ({k: (v * 100, v / max(s, 1e-12)) for k, (v, s) in r.items()}, n)

print(f"{'bin':>10} | " + " | ".join(f"{n:^17s}" for n in GRPDEF) + " | high-low(lev)")
for k in sorted(P["bin"].unique()):
    if k == REF:
        continue
    c = f"b{k}"
    cells = []
    for name in GRPDEF:
        dh = res[(name, "high")][0][c]
        dl = res[(name, "low")][0][c]
        cells.append(f"{dh[0]:+6.2f}/{dl[0]:+6.2f}")
    dlev = res[("lev", "high")][0][c][0] - res[("lev", "low")][0][c][0]
    print(f"{LAB[k]:>10} | " + " | ".join(f"{x:^17s}" for x in cells) + f" | {dlev:+6.2f}")
print("每行格式：高组系数 / 低组系数；单位百分点")

# ---------------- 快速下跌事件：同规格 Logit 近似（线性概率 + FE） ----------------
print("\n=== 快速下跌概率（5日超额跌>8%）的 FE 系数（百分点）===")
for ycol, tt in [("crash", "crash>8%"), ("crash_z", "z<=-1.5"), ("crash_dd", "exDD>10%")]:
    line = []
    for name in GRPDEF:
        rh, _ = fe_fit(P[P.code.isin(GRPDEF[name][0])], ycol, BINCOLS + BASE)
        rl, _ = fe_fit(P[P.code.isin(GRPDEF[name][1])], ycol, BINCOLS + BASE)
        # 取贴线区 [0,20) 三箱平均作为「抢跑区」读数
        ks = [f"b{k}" for k in (0, 1, 2, 3) if f"b{k}" in BINCOLS]
        vh = np.mean([rh[c][0] for c in ks]) * 100
        vl = np.mean([rl[c][0] for c in ks]) * 100
        line.append(f"{name}: 高{vh:+.1f} 低{vl:+.1f} 差{vh-vl:+.1f}")
    print(f"  {tt:12s} [0,25)区相对基准: " + " | ".join(line))

# ---------------- 安慰剂 1：随机置换分组 ----------------
print("\n=== 安慰剂 1：随机分组 300 次，真实 high-low 差是否超随机分布 ===")
rng = np.random.default_rng(20261109)
allcodes = np.array(sorted(P.code.unique()))
n_hi, n_lo = len(GRPDEF["buy"][0]), len(GRPDEF["buy"][1])
# 用精简设定（只有 bin 哑变量 + 双向 FE）加速
KS = [f"b{k}" for k in sorted(P["bin"].unique()) if k != REF]
obs = {}
for name in GRPDEF:
    rh, _ = fe_fit(P[P.code.isin(GRPDEF[name][0])], "exret5", KS, want_se=False)
    rl, _ = fe_fit(P[P.code.isin(GRPDEF[name][1])], "exret5", KS, want_se=False)
    obs[name] = np.array([(rh[c] - rl[c]) * 100 for c in KS])

null = []
for _ in range(300):
    pick = rng.choice(allcodes, size=n_hi + n_lo, replace=False)
    h, l = set(pick[:n_hi]), set(pick[n_hi:])
    a, _ = fe_fit(P[P.code.isin(h)], "exret5", KS, want_se=False)
    b, _ = fe_fit(P[P.code.isin(l)], "exret5", KS, want_se=False)
    null.append([(a[c] - b[c]) * 100 for c in KS])
null = np.array(null)
q05, q95 = np.percentile(null, [2.5, 97.5], axis=0)
print("bin        " + "".join(f"{n:>16s}" for n in GRPDEF) + "    随机95%区间")
for j, c in enumerate(KS):
    k = int(c[1:])
    flags = []
    for name in GRPDEF:
        v = obs[name][j]
        flags.append(f"{v:+6.2f}{'*' if (v < q05[j] or v > q95[j]) else ' '}")
    print(f"{LAB[k]:>10} " + "".join(f"{f:>16s}" for f in flags)
          + f"    [{q05[j]:+.2f},{q95[j]:+.2f}]")
print("* = 超出随机分组 95% 区间")

# ---------------- 安慰剂 2：时间切分 ----------------
print("\n=== 安慰剂 2：时间前半 / 后半（buy 分组，high-low 差）===")
dates = np.array(sorted(P.date.unique()))
mid = dates[len(dates) // 2]
for tag, sub in [("前半", P[P.date <= mid]), ("后半", P[P.date > mid])]:
    rh, _ = fe_fit(sub[sub.code.isin(GRPDEF["buy"][0])], "exret5", KS, want_se=False)
    rl, _ = fe_fit(sub[sub.code.isin(GRPDEF["buy"][1])], "exret5", KS, want_se=False)
    vals = [(rh[c] - rl[c]) * 100 for c in KS]
    print(f"  {tag} (截至{mid.date()}): " + " ".join(f"{LAB[int(c[1:])]}={v:+.2f}" for c, v in zip(KS, vals)))
