"""主检验：融资盘「抢跑螺旋」是否存在？高风险区在哪？

识别策略：
  - 处理组 = 样本首日 lev（融资余额/5日均额）横截面前 30%，组身份全期固定
    避免「跌了→成交额萎缩→lev升高→被分到处理组」的反向因果
  - 对照组 = 首日 lev 后 30%
  - 分组变量 = buf_liq（距理论平仓线的剩余跌幅），等价于融资盘浮亏深度
  - 因变量 = 未来 5 日市场调整收益 / 快速下跌事件 / 融资余额变化 / 放量
  - 关键判据：处理组相对对照组的「额外下跌」是否在某个 buf_liq 区间出现局部峰值
    （单调全区间同号 = 只是杠杆 Beta，不是阈值抢跑）
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "out"
P = pd.read_parquet(OUT / "panel.parquet")

# ---------------- 固定分组（完全 point-in-time） ----------------
t0 = P.date.min()
snap = P[P.date == t0][["code", "lev"]].dropna()
hi_cut, lo_cut = snap.lev.quantile(0.70), snap.lev.quantile(0.30)
hi = set(snap[snap.lev >= hi_cut].code)
lo = set(snap[snap.lev <= lo_cut].code)
P = P[P.code.isin(hi | lo)].copy()
P["grp"] = np.where(P.code.isin(hi), "high", "low")
print(f"首日 {t0.date()}  lev 切点: 高>={hi_cut:.2f}天  低<={lo_cut:.2f}天")
print(f"高组 {len(hi)} 只 / 低组 {len(lo)} 只   面板 {len(P):,} 行")

# ---------------- 事件定义 ----------------
P["crash"] = (P.exret5 <= -0.08).astype(float)
P["crash_z"] = (P.z5 <= -1.5).astype(float)
P["crash_dd"] = (P.ex_dd5 <= -0.10).astype(float)

# ---------------- buf_liq 分箱 ----------------
# 主分箱：等宽 5%，覆盖样本密集区；两侧合并
edges = [-60, 0, 5, 10, 15, 20, 25, 30, 33, 36, 39, 42, 45, 100]
P["bin"] = pd.cut(P.buf_liq, edges, right=False)

def did_table(var, label):
    g = P.dropna(subset=[var]).groupby(["bin", "grp"], observed=True)[var].agg(["mean", "size"])
    out = []
    for b in P["bin"].dropna().cat.categories:
        try:
            h, l = g.loc[(b, "high")], g.loc[(b, "low")]
        except KeyError:
            continue
        out.append({
            "bin": str(b), "hi": h["mean"], "lo": l["mean"],
            "diff": h["mean"] - l["mean"], "n_hi": int(h["size"]), "n_lo": int(l["size"]),
        })
    d = pd.DataFrame(out)
    d["label"] = label
    return d

print("\n=== A. 未来 5 日市场调整超额收益（%），高融资组 − 低融资组 ===")
a = did_table("exret5", "exret5")
a[["hi", "lo", "diff"]] = (a[["hi", "lo", "diff"]] * 100).round(2)
print(a[["bin", "hi", "lo", "diff", "n_hi", "n_lo"]].to_string(index=False))

print("\n=== B. 快速下跌概率（5日超额跌>8%），高 − 低（百分点）===")
b = did_table("crash", "crash")
b[["hi", "lo", "diff"]] = (b[["hi", "lo", "diff"]] * 100).round(2)
print(b[["bin", "hi", "lo", "diff", "n_hi", "n_lo"]].to_string(index=False))

print("\n=== C. 波动率标准化后的下跌事件（z<=-1.5），高 − 低（百分点）===")
c = did_table("crash_z", "crash_z")
c[["hi", "lo", "diff"]] = (c[["hi", "lo", "diff"]] * 100).round(2)
print(c[["bin", "hi", "lo", "diff", "n_hi", "n_lo"]].to_string(index=False))

print("\n=== D. 机制：未来 5 日融资余额变化（%），高 − 低 ===")
d = did_table("drz5", "drz5")
d[["hi", "lo", "diff"]] = (d[["hi", "lo", "diff"]] * 100).round(2)
print(d[["bin", "hi", "lo", "diff", "n_hi", "n_lo"]].to_string(index=False))

print("\n=== E. 机制：未来 5 日成交额 / 过去 20 日均额（放量倍数）===")
e = did_table("vratio", "vratio")
e[["hi", "lo", "diff"]] = (e[["hi", "lo", "diff"]]).round(2)
print(e[["bin", "hi", "lo", "diff", "n_hi", "n_lo"]].to_string(index=False))

# ---------------- 保存 ----------------
for x in (a, b, c, d, e):
    pass
pd.concat([a, b, c, d, e]).to_csv(OUT / "did_table.csv", index=False)

# ---------------- 控制变量后是否仍存在（分箱内回归） ----------------
print("\n=== F. 分箱内 OLS：exret5 ~ high + ret20 + vol20 + log(amt20) + ret5 ===")
import statsmodels.api as sm
P["logamt"] = np.log(P.amt20.clip(lower=1))
P["high"] = (P.grp == "high").astype(float)
rows = []
for bn, sub in P.dropna(subset=["exret5", "ret20", "vol20", "logamt", "ret5"]).groupby("bin", observed=True):
    if len(sub) < 300:
        continue
    X = sm.add_constant(sub[["high", "ret20", "vol20", "logamt", "ret5"]])
    fit = sm.OLS(sub.exret5, X).fit(cov_type="cluster", cov_kwds={"groups": sub.date})
    rows.append({
        "bin": str(bn), "n": len(sub),
        "beta_high_%": round(fit.params["high"] * 100, 3),
        "t": round(fit.tvalues["high"], 2),
        "p": round(fit.pvalues["high"], 4),
    })
F = pd.DataFrame(rows)
print(F.to_string(index=False))
F.to_csv(OUT / "ols_bins.csv", index=False)
