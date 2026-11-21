#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
决定性检验：情绪低点的"含金量"由资金结构决定吗？

命题：广度崩塌分两种
  A「出清型」：资金分散、成交额萎缩 → 卖压释放完毕，后续反弹强
  B「撤退型」：资金抱团、集中度极高 → 存量博弈退守少数堡垒，广度崩塌是结果而非起点

若成立，则同一个"广度极冷"读数，在两种资金结构下应给出完全不同的前瞻收益。
"""
import numpy as np
import pandas as pd
from scipy import stats

BASE = "/opt/daily-tasks/workspace/analysis/out/sentiment"
d = pd.read_csv(f"{BASE}/panel.csv", index_col=0, parse_dates=True)
NAV = d["eq_nav"]
fwd = {h: NAV.shift(-h) / NAV - 1 for h in [5, 20, 60]}


def clusters(mask, gap=3):
    idx = np.where(np.nan_to_num(mask, nan=0).astype(bool))[0]
    if len(idx) == 0:
        return []
    out, prev = [idx[0]], idx[0]
    for i in idx[1:]:
        if i - prev > gap:
            out.append(i)
        prev = i
    return out


print("=" * 100)
print("【决定性检验】广度极冷（above_ma250<15%）时，按资金集中度分组")
print("=" * 100)
base = (d["above_ma250"] < 0.15).values
cs = clusters(base)
conc = d["top10_amt_share_pct"]
rows = []
for i in cs:
    c = conc.iloc[i]
    r20 = fwd[20].iloc[i] * 100 if not np.isnan(fwd[20].iloc[i]) else np.nan
    r60 = fwd[60].iloc[i] * 100 if not np.isnan(fwd[60].iloc[i]) else np.nan
    rows.append(dict(date=d.index[i], conc_pct=c, fwd20=r20, fwd60=r60))
T = pd.DataFrame(rows)
print(f"\n{'触发日':<12}{'集中度分位':>10}{'fwd20':>9}{'fwd60':>9}   归类")
print("-" * 100)
for _, r in T.iterrows():
    tag = "B 撤退型" if r.conc_pct >= 0.75 else ("A 出清型" if r.conc_pct <= 0.5 else "中间")
    print(f"{r.date.strftime('%Y-%m-%d'):<12}{r.conc_pct*100:>9.0f}%"
          f"{r.fwd20:>9.2f}{r.fwd60:>9.2f}   {tag}")

print("\n分组统计：")
for lab, m in [("A 出清型 (集中度≤50%)", T.conc_pct <= 0.5),
               ("中间 (50-75%)", (T.conc_pct > 0.5) & (T.conc_pct < 0.75)),
               ("B 撤退型 (集中度≥75%)", T.conc_pct >= 0.75)]:
    sub = T[m]
    v20 = sub.fwd20.dropna(); v60 = sub.fwd60.dropna()
    if len(v20) == 0:
        print(f"  {lab:<26} n=0")
        continue
    print(f"  {lab:<26} n={len(v20):<3} fwd20 均值 {v20.mean():>6.2f}% 中位 {v20.median():>6.2f}% 胜率 {(v20>0).mean():>4.0%}"
          f"   | fwd60 均值 {v60.mean():>7.2f}% 中位 {v60.median():>7.2f}% 胜率 {(v60>0).mean():>4.0%}")

print("\n样本说明：n 为事件簇数，均小于 16，t 值无判别力，只能看点估计落差。")

# ---------- 全样本条件分布（不依赖事件簇，样本更大）----------
print("\n" + "=" * 100)
print("【全样本条件分布】不分簇，所有交易日按 (广度, 集中度) 二维分组，fwd20 中位收益 %")
print("=" * 100)
bins_b = [0, 0.10, 0.20, 0.35, 1.01]
bins_c = [0, 0.34, 0.67, 1.01]
lab_b = ["广度<10%", "10-20%", "20-35%", ">35%"]
lab_c = ["集中度低", "中", "集中度高"]
print(f"\n{'':<12}" + "".join([f"{c:>14}" for c in lab_c]))
print("-" * 60)
for i in range(len(bins_b) - 1):
    line = f"{lab_b[i]:<12}"
    for j in range(len(bins_c) - 1):
        m = ((d["above_ma250"] >= bins_b[i]) & (d["above_ma250"] < bins_b[i + 1]) &
             (conc >= bins_c[j]) & (conc < bins_c[j + 1]))
        v = fwd[20][m].median() * 100
        cnt = m.sum()
        line += f"{v:>9.2f}({cnt:>4})" if cnt > 20 else f"{'--':>9}({cnt:>4})"
    print(line)
print("\n括号内为交易日数（未分簇，重叠严重，仅作方向参考）")

# ---------- 当前状态落在哪一格 ----------
cur_b = d["above_ma250"].iloc[-1]
cur_c = conc.iloc[-1]
bi = max(i for i in range(len(bins_b)-1) if cur_b >= bins_b[i])
ci = max(j for j in range(len(bins_c)-1) if cur_c >= bins_c[j])
_cell = fwd[20][(d["above_ma250"]>=bins_b[bi])&(d["above_ma250"]<bins_b[bi+1])&(conc>=bins_c[ci])&(conc<bins_c[ci+1])]
print(f"\n当前: 广度 {cur_b*100:.1f}%  集中度分位 {cur_c*100:.0f}%  → 落在「{lab_b[bi]} × {lab_c[ci]}」格")
print(f"该格历史 fwd20 中位: {_cell.median()*100:+.2f}%   交易日数 {len(_cell)}  (重叠严重，仅方向参考)")

# ---------- 2017-2018 复盘：抱团瓦解用了多久 ----------
print("\n" + "=" * 100)
print("【复盘】2017-2018「漂亮50」抱团期，广度在低位停留了多久")
print("=" * 100)
seg = d.loc["2017-01-01":"2018-12-31"]
low = (seg["above_ma250"] < 0.20)
print(f"\n2017 全年 above_ma250<20% 的天数: {low.loc['2017'].sum()} / {len(low.loc['2017'])}")
print(f"2018 全年 above_ma250<20% 的天数: {low.loc['2018'].sum()} / {len(low.loc['2018'])}")
print(f"最长连续低位天数: ", end="")
mx = cur = 0
for v in low.values:
    cur = cur + 1 if v else 0
    mx = max(mx, cur)
print(mx)
print(f"区间等权收益: {(NAV.loc['2018-12-28']/NAV.loc['2017-01-03']-1)*100:.1f}%")
print(f"同期集中度分位中位: {conc.loc['2017':'2018'].median()*100:.0f}%")

# ---------- 2026 年这一段 ----------
print("\n" + "=" * 100)
print("【2026 年复盘】成交额集中度与广度")
print("=" * 100)
y26 = d.loc["2026-01-01":]
print(f"\n{'区间':<12}{'集中度分位':>10}{'HHI分位':>9}{'above250':>10}{'成交额分位':>10}{'等权收益':>10}")
print("-" * 66)
for q, (s, e) in {"2026Q1": ("2026-01-01", "2026-03-31"), "2026Q2": ("2026-04-01", "2026-06-30"),
                  "2026Q3": ("2026-07-01", "2026-09-30"), "2026Q4": ("2026-10-01", "2026-12-31")}.items():
    sub = d.loc[s:e]
    if len(sub) < 5:
        continue
    r = NAV.loc[sub.index[-1]] / NAV.loc[sub.index[0]] - 1
    print(f"{q:<12}{sub['top10_amt_share_pct'].median()*100:>9.0f}%{sub['hhi_pct'].median()*100:>8.0f}%"
          f"{sub['above_ma250'].median()*100:>9.0f}%{sub['amt_per_stock_pct'].median()*100:>9.0f}%{r*100:>9.1f}%")
