"""第四层：领先滞后结构。判断 ETF 申赎净流入是价格的"因"还是"果"。
若 corr(nf_t, ret_{t-k}) 在 k>0（净流入滞后于涨跌）显著为正 → 净流入是被动追随，不是预测。
"""
import json
import numpy as np
import pandas as pd

OUT = "/opt/daily-tasks/workspace/analysis/out"
D = json.load(open("/tmp/islands.json"))
Q = json.load(open(f"{OUT}/quotes.json"))

px = pd.DataFrame(Q["sh000001"]["bars"]).set_index("date")
nf = pd.Series(D["dailyData"]["netflow"], index=D["dailyData"]["dates"], dtype=float)
nf.index = pd.to_datetime(nf.index).strftime("%Y-%m-%d")
dates = [d for d in nf.index if d in px.index]
nf = nf.loc[dates]
px = px.loc[dates]
ret = px["close"].pct_change() * 100

print("=== 领先滞后相关：corr(净流入_t, 指数收益_{t+k}) ===")
print("k<0 表示净流入滞后于收益（跟随），k>0 表示净流入领先于收益（预测）")
print(f"{'区间':>12} " + " ".join(f"k={k:+d}" for k in range(-5, 6)))
for lab, sl in [("全样本", slice(None)), ("2024", slice("2024-01-01", "2024-12-31")),
                ("2025", slice("2025-01-01", "2025-12-31")),
                ("2026", slice("2026-01-01", "2026-12-31"))]:
    n2, r2 = nf.loc[sl], ret.loc[sl]
    vals = []
    for k in range(-5, 6):
        v = n2.corr(r2.shift(-k))
        vals.append(f"{v:+.2f}")
    print(f"{lab:>12} " + "  ".join(vals))

# 同期与滞后 1 日的回归系数
print("\n=== 分年度：净流入对当日收益/次日收益的解释（beta 与 t）===")


def beta_t(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    X = np.column_stack([np.ones(len(x)), x])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    s2 = e @ e / (len(x) - 2)
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    return b[1], b[1] / se[1]


for y in (2024, 2025, 2026):
    sl = slice(f"{y}-01-01", f"{y}-12-31")
    n2, r2 = nf.loc[sl], ret.loc[sl]
    b1, t1 = beta_t(r2.values, n2.values)                 # 净流入 ~ 当日收益
    b2, t2 = beta_t(r2.shift(1).values, n2.values)         # 净流入 ~ 前一日收益
    b3, t3 = beta_t(n2.values, r2.shift(-1).values)        # 次日收益 ~ 净流入
    print(f"{y}: 净流入~当日收益 β={b1:6.2f}(t={t1:+.2f}) | "
          f"净流入~前日收益 β={b2:6.2f}(t={t2:+.2f}) | "
          f"次日收益~净流入 β={b3:+.5f}(t={t3:+.2f})")

# 净流入自身的持续性：今天大额流入，明天还会流入吗
print("\n=== 净流入的自相关（持续性）===")
for y in (2024, 2025, 2026):
    sl = slice(f"{y}-01-01", f"{y}-12-31")
    n2 = nf.loc[sl]
    print(f"{y}: lag1={n2.autocorr(1):+.2f} lag2={n2.autocorr(2):+.2f} "
          f"lag5={n2.autocorr(5):+.2f}")

# 波动率/成交额环境变化
print("\n=== 市场环境：上证成交额（亿元）与20只ETF成交额 ===")
amt = pd.Series(D["dailyData"]["amount"], index=D["dailyData"]["dates"], dtype=float)
amt.index = pd.to_datetime(amt.index).strftime("%Y-%m-%d")
amt = amt.loc[dates]
q = pd.DataFrame({"idx_vol": px["volume"] / 1e8,
                  "etf_amt": amt, "nf": nf, "ret": ret})
print(q.groupby(pd.to_datetime(q.index).year).agg(
    上证成交额_亿=("idx_vol", "mean"), ETF20成交额_亿=("etf_amt", "mean"),
    nf均值=("nf", "mean"), nf标准差=("nf", "std")).round(1))
print("\nETF成交额占上证成交额比重（%）：")
print((q["etf_amt"] / q["idx_vol"] * 100).groupby(pd.to_datetime(q.index).year).mean().round(2))
