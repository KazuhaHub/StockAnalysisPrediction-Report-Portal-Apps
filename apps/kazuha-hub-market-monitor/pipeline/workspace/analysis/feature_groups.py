"""第三层：把"国家队"这个模糊标签拆成可检验的特征，看哪一组才有前瞻性。

候选识别特征：
  A 单日大额      netflow > threshold
  B 逆势买入      当日指数下跌 且 净流入 > threshold
  C 连续买入      连续 >=3 日净流入为正，且区间累计 > threshold
  D 逆势+连续     当日跌 且 连续>=3 日为正 且 累计 > threshold
并检查事件的时间聚集度（同簇内事件不能当独立样本）。
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

FWD = {h: (px["close"].shift(-h) / px["open"].shift(-1) - 1) * 100 for h in (1, 3, 5, 10, 20)}

# 连续为正的游程长度
pos = (nf > 0).astype(int)
run = pos.groupby((pos != pos.shift()).cumsum()).cumsum()
run3_amt = nf.rolling(3).sum()

sig = {
    "A 单日>100亿": nf > 100,
    "A 单日>200亿": nf > 200,
    "B 逆势(跌>1%)+>100亿": (nf > 100) & (ret < -1),
    "B 逆势(跌>1%)+>50亿": (nf > 50) & (ret < -1),
    "C 连3日正+累计>300亿": (run >= 3) & (run3_amt > 300),
    "C 连3日正+累计>500亿": (run >= 3) & (run3_amt > 500),
    "D 逆势+连3日正+>300亿": (run >= 3) & (run3_amt > 300) & (ret < -0.5),
    "对照 逆势(跌>1%)无流入": (ret < -1) & (nf < 0),
}


def cluster_heads(pos_idx, gap):
    heads, last = [], -10**9
    for p in sorted(pos_idx):
        if p - last >= gap:
            heads.append(p)
            last = p
    return heads


rows = []
for name, m in sig.items():
    for h in (1, 3, 5, 10, 20):
        f = FWD[h]
        ev = f[m.reindex(f.index).fillna(False)].dropna()
        base = f.dropna()
        if len(ev) < 3:
            continue
        pos_list = [px.index.get_loc(d) for d in ev.index]
        heads = cluster_heads(pos_list, h)
        eh = f.iloc[heads].dropna()
        t_cl = (eh.mean() / (eh.std(ddof=1) / np.sqrt(len(eh)))
                if len(eh) > 2 else np.nan)
        rows.append({"信号": name, "h": h, "n": len(ev), "n簇": len(eh),
                     "均值%": round(ev.mean(), 2), "中位%": round(ev.median(), 2),
                     "胜率%": round((ev > 0).mean() * 100, 0),
                     "基准%": round(base.mean(), 2),
                     "超额pp": round(ev.mean() - base.mean(), 2),
                     "t_簇": round(t_cl, 2) if np.isfinite(t_cl) else None})

r = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print("=== 特征组 × 持有期（全样本 2023-10~2026-11，上证综指，T+1开盘）===")
print(r.to_string(index=False))
r.to_csv(f"{OUT}/feature_groups.csv", index=False, encoding="utf-8-sig")

# 事件时间分布：看是否高度聚集
print("\n=== 事件时间分布（按年）===")
for name, m in sig.items():
    ev = m[m].index
    if len(ev) == 0:
        continue
    yr = pd.Series(ev).groupby(pd.to_datetime(ev).year).size()
    print(f"{name:24s} n={len(ev):3d}  {dict(yr)}")

# 2024 与 2026 分开看 A、B 两组
print("\n=== 分组年度（h=5）===")
for name in ["A 单日>100亿", "B 逆势(跌>1%)+>100亿", "C 连3日正+累计>300亿"]:
    m = sig[name]
    for y in (2024, 2025, 2026):
        sel = m & (pd.to_datetime(nf.index).year == y)
        f = FWD[5]
        ev = f[sel.reindex(f.index).fillna(False)].dropna()
        b = f[pd.to_datetime(f.index).year == y].dropna()
        if len(ev):
            print(f"{name:22s} {y}: n={len(ev):2d} 均值{ev.mean():+.2f}% "
                  f"胜率{(ev>0).mean()*100:3.0f}% 超额{ev.mean()-b.mean():+.2f}pp")

# 最近这波的实时跟踪
print("\n=== 2026-10 以来：若按信号 T+1 开盘买入，到现在的结果 ===")
last_close = px["close"].iloc[-1]
last_date = px.index[-1]
for name in ["A 单日>100亿", "B 逆势(跌>1%)+>100亿"]:
    m = sig[name] & (pd.to_datetime(nf.index) >= "2026-10-01")
    for d in m[m].index:
        i = px.index.get_loc(d)
        if i + 1 >= len(px):
            continue
        ent = px["open"].iloc[i + 1]
        cur = (last_close / ent - 1) * 100
        print(f"{name} {d} 入场{ent:.1f} 现值{last_close:.1f} 浮动{cur:+.2f}%")
