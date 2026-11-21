"""预测力扫描：静态距线位置没用，那什么变量真能预警 5 日快速下跌？

纪律：只报描述性排序 + 时间前后半一致性，不报 t 值
（5 日重叠窗口 + 116 日 ≈ 24 个独立时间簇，按行算显著性是自欺）
"""
import numpy as np
import pandas as pd

P = pd.read_parquet("analysis/out/panel2.parquet").replace([np.inf, -np.inf], np.nan)
P["crash"] = (P.exret5 <= -0.08).astype(float)
P["crash_z"] = (P.z5 <= -1.5).astype(float)
P["logamt"] = np.log(P.amt20.clip(lower=1))

VARS = {
    "buf_liq": "距平仓线", "pnl": "融资浮盈亏", "eps_dummy": "—",
    "ret20": "20日动量", "ret5": "5日动量", "ret60": "60日动量",
    "vol20": "20日波动", "logamt": "规模(对数成交额)",
    "lev": "融资余额/成交额", "buy_share": "融资买入占比",
    "rz_chg5": "融资余额5日变化", "buy_chg5": "融资买入额5日变化",
    "drz1": "当日净偿还",
}
VARS.pop("eps_dummy")
for c in list(VARS) + ["crash", "crash_z", "exret5"]:
    if c in P.columns:
        P[c] = P[c].clip(P[c].quantile(.005), P[c].quantile(.995))

dates = np.array(sorted(P.date.unique()))
mid = dates[len(dates)//2]
HALVES = {"全样本": P, "前半": P[P.date <= mid], "后半": P[P.date > mid]}

def q_spread(d, v, y="crash"):
    s = d[[v, y]].dropna()
    if len(s) < 5000:
        return np.nan
    try:
        s["q"] = pd.qcut(s[v], 10, labels=False, duplicates="drop")
    except ValueError:
        return np.nan
    g = s.groupby("q")[y].mean()
    if len(g) < 10:
        return np.nan
    return (g.iloc[-1] - g.iloc[0]) * 100     # Q9-Q0，百分点

print("=== 各变量十分位 Q9−Q0 的快速下跌率差（百分点，正=该变量越高越易崩）===")
print(f"    时间中点 {pd.Timestamp(mid).date()}；「两半一致」要求同号且都 |差|>1pp")
print(f"{'变量':<20s}{'全样本':>10s}{'前半':>10s}{'后半':>10s}   两半一致")
rows = []
for v, lab in VARS.items():
    if v not in P.columns:
        continue
    a = q_spread(HALVES["全样本"], v)
    h1 = q_spread(HALVES["前半"], v)
    h2 = q_spread(HALVES["后半"], v)
    ok = (np.isfinite(h1) and np.isfinite(h2) and np.sign(h1) == np.sign(h2)
          and abs(h1) > 1 and abs(h2) > 1)
    rows.append((v, lab, a, h1, h2, ok))
    print(f"{lab:<20s}{a:>+10.2f}{h1:>+10.2f}{h2:>+10.2f}   {'✓' if ok else '✗'}")

print("\n=== 波动率标准化事件（z≤−1.5）的同规格复核（检验是否只是高波动替身）===")
for v, lab, a, h1, h2, ok in rows:
    if not ok:
        continue
    z1 = q_spread(HALVES["前半"], v, "crash_z")
    z2 = q_spread(HALVES["后半"], v, "crash_z")
    print(f"  {lab:<20s} 前半{z1:+.2f}pp 后半{z2:+.2f}pp  "
          f"{'两半同号' if np.sign(z1)==np.sign(z2) else '符号翻转'}")

print("\n=== 候选组合：融资买入占比高位 + 融资余额5日骤降，是否比单一变量更强 ===")
# 定义为「杠杆资金正在撤」：buy_share 前 30% 且 rz_chg5 后 30%
d = P.dropna(subset=["buy_share", "rz_chg5", "crash"]).copy()
b_hi = d.buy_share.quantile(.70); r_lo = d.rz_chg5.quantile(.30)
d["flag"] = ((d.buy_share >= b_hi) & (d.rz_chg5 <= r_lo)).astype(int)
for tag, s in [("全样本", d), ("前半", d[d.date <= mid]), ("后半", d[d.date > mid])]:
    g = s.groupby("flag").agg(crash=("crash", "mean"), exret5=("exret5", "mean"), n=("crash", "size"))
    if len(g) < 2:
        continue
    print(f"  {tag}: 命中 {int(g.loc[1,'n']):,} 行 crash {g.loc[1,'crash']*100:.2f}% "
          f"vs 其余 {g.loc[0,'crash']*100:.2f}%  差 {(g.loc[1,'crash']-g.loc[0,'crash'])*100:+.2f}pp"
          f" | 5日超额 {g.loc[1,'exret5']*100:+.2f}% vs {g.loc[0,'exret5']*100:+.2f}%")
