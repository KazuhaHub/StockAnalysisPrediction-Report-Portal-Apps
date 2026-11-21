"""第二层：净流入到底是"增量信息"还是"当日下跌的镜像"。
回归 fwd_h ~ 1 + 当日收益 + 当日跌幅dummy + 净流入z + 连续放量，看净流入系数还站不站得住。
"""
import json
import numpy as np
import pandas as pd

OUT = "/opt/daily-tasks/workspace/analysis/out"
D = json.load(open("/tmp/islands.json"))
Q = json.load(open(f"{OUT}/quotes.json"))

idx = pd.DataFrame(Q["sh000001"]["bars"]).set_index("date")
nf = pd.Series(D["dailyData"]["netflow"], index=D["dailyData"]["dates"], dtype=float)
nf.index = pd.to_datetime(nf.index).strftime("%Y-%m-%d")
dates = [d for d in nf.index if d in idx.index]
nf = nf.loc[dates]
df = idx.loc[dates].copy()

df["nf"] = nf
df["ret"] = df["close"].pct_change() * 100
df["nf_z"] = ((df["nf"] - df["nf"].rolling(20).mean()) / df["nf"].rolling(20).std()).replace([np.inf,-np.inf], np.nan)
df["nf_z"] = df["nf_z"].clip(-5,5)
df["nf_3d"] = df["nf"].rolling(3).sum()
df["amt_ratio"] = df["volume"] / df["volume"].rolling(20).mean()   # 全市场成交额放大倍数
for h in (1, 3, 5, 10, 20):
    df[f"fwd{h}"] = (df["close"].shift(-h) / df["open"].shift(-1) - 1) * 100

# 同期相关性：净流入 vs 当日涨跌
print("=== 相关性 ===")
print(f"nf vs 当日收益 corr = {df['nf'].corr(df['ret']):.3f}")
print(f"nf vs 当日成交额放大 corr = {df['nf'].corr(df['amt_ratio']):.3f}")
print("下跌日(<-0.5pct)净流入均值 {:.1f} 亿；上涨日(>+0.5pct)净流入均值 {:.1f} 亿".format(
    df.loc[df.ret < -0.5, "nf"].mean(), df.loc[df.ret > 0.5, "nf"].mean()))

print("\n=== 按当日涨跌分组，看未来5日收益（%） ===")
df["grp"] = pd.cut(df["ret"], [-99, -1.5, -0.5, 0.5, 1.5, 99],
                   labels=["跌>1.5%", "跌0.5-1.5%", "平", "涨0.5-1.5%", "涨>1.5%"])
g = df.groupby("grp", observed=True).agg(n=("fwd5", "size"), fwd5=("fwd5", "mean"),
                                         nf_mean=("nf", "mean"))
print(g.round(2))

print("\n=== 双重分组：当日跌幅 × 净流入 ===")
df["nfgrp"] = pd.cut(df["nf"], [-9999, 0, 50, 9999], labels=["净流出/小", "0-50亿", ">50亿"])
piv = df.pivot_table(index="grp", columns="nfgrp", values="fwd5", aggfunc=["mean", "size"], observed=True)
print(piv.round(2))


def ols(X, y):
    X = np.column_stack([np.ones(len(X)), X])
    m = np.isfinite(X).all(1) & np.isfinite(y)
    X, y = X[m], y[m]
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    n, k = X.shape
    s2 = e @ e / (n - k)
    cov = s2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    t = b / se
    r2 = 1 - (e @ e) / ((y - y.mean()) @ (y - y.mean()))
    return b, t, r2, n


print("\n=== 回归：净流入在控制当日涨跌后还有没有解释力 ===")
for h in (5, 10, 20):
    y = df[f"fwd{h}"].values
    # 模型A：只用当日收益（短期反转）
    Xa = df[["ret"]].values
    ba, ta, r2a, na = ols(Xa, y)
    # 模型B：加净流入 z
    Xb = df[["ret", "nf_z"]].values
    bb, tb, r2b, nb = ols(Xb, y)
    print(f"h={h:2d}  A: ret β={ba[1]:+.3f}(t={ta[1]:+.2f}) R²={r2a:.3f}  |  "
          f"B: +nf_z β={bb[2]:+.3f}(t={tb[2]:+.2f}) R²={r2b:.3f}  ΔR²={r2b-r2a:+.3f}")
    # 模型C：再加成交额放大
    Xc = df[["ret", "nf_z", "amt_ratio"]].values
    bc, tc, r2c, nc = ols(Xc, y)
    print(f"      C: +amt_ratio β={bc[3]:+.3f}(t={tc[3]:+.2f}) R²={r2c:.3f}  "
          f"nf_z β={bc[2]:+.3f}(t={tc[2]:+.2f})")

df.to_csv(f"{OUT}/panel2.csv", encoding="utf-8-sig")
print("\nsaved panel2.csv")
