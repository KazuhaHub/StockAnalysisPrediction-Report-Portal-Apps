#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
情绪结构框架：不做"一个数字"，做五维分解 + 错位诊断。

为什么不用单一合成指数：
  单一指数把「量能 / 广度 / 极端 / 赚钱效应 / 资金结构」压成一个数，
  不同性质的悲观会被平均掉。2026-11 的情况正是例证：
  成交额在 50% 分位（中性），广度在 5% 分位（极冷）——
  合成后得到"略偏悲观"，但真实含义是"结构性出清"，两者应对完全不同。

MSASI 复现度：大摩 MSASI 五个成分（成交额、两融、技术指标、资金流向、盈利预期），
本地能复现 3 个（成交额、技术指标、两融[仅2024起]），缺资金流向（无北向逐日）与盈利预期（无一致预期快照）。
"""
import numpy as np
import pandas as pd

BASE = "/opt/daily-tasks/workspace/analysis/out/sentiment"
d = pd.read_csv(f"{BASE}/panel.csv", index_col=0, parse_dates=True)
NAV = d["eq_nav"]
fwd = {h: NAV.shift(-h) / NAV - 1 for h in [5, 20, 60]}

# 方向：+1 表示"值越大越乐观"，-1 表示"值越大越悲观"
DIMS = {
    "量能": {
        "desc": "钱还在不在场（决定仓位能否放大）",
        "items": {"amt_per_stock_pct": +1, "amt_ratio20_pct": +1, "amt_z60_pct": +1},
    },
    "广度": {
        "desc": "上涨是普涨还是少数股独舞（决定赚钱难度）",
        "items": {"above_ma20_pct": +1, "above_ma60_pct": +1, "above_ma250_pct": +1,
                  "pct_adv_pct": +1, "new_high_pct_pct": +1, "new_low_pct_pct": -1},
    },
    "极端": {
        "desc": "恐慌/亢奋的尾部强度（决定赔率）",
        "items": {"limit_up_pct": +1, "limit_down_pct": -1, "dd20_pct_pct": -1},
    },
    "赚钱效应": {
        "desc": "持有体验，决定散户是否敢加仓",
        "items": {"r20_positive_pct": +1, "r20_median_pct": +1},
    },
    "资金结构": {
        "desc": "钱是分散还是抱团（抱团=有主线，也=脆弱）",
        "items": {"top10_amt_share_pct": +1, "hhi_pct": +1},
    },
}

print("=" * 104)
print("【五维情绪诊断】各维度滚动 3 年分位合成（0=极冷 100=极热）")
print("=" * 104)

score = pd.DataFrame(index=d.index)
for dim, cfg in DIMS.items():
    vals = []
    for k, sign in cfg["items"].items():
        v = d[k] * sign if sign > 0 else (1 - d[k])
        vals.append(v)
    score[dim] = pd.concat(vals, axis=1).mean(axis=1)

# 综合（仅作对照，不作决策依据）
score["综合"] = score[list(DIMS)].mean(axis=1)

cur = score.iloc[-1]
prev5 = score.iloc[-6] if len(score) > 6 else score.iloc[0]
print(f"\n基准日 {d.index[-1].date()}\n")
print(f"{'维度':<8}{'含义':<34}{'当前分位':>10}{'5日前':>9}{'方向':>7}")
print("-" * 104)
for dim, cfg in DIMS.items():
    arrow = "↑修复" if cur[dim] > prev5[dim] + 0.02 else ("↓恶化" if cur[dim] < prev5[dim] - 0.02 else "→持平")
    print(f"{dim:<8}{cfg['desc']:<34}{cur[dim]*100:>9.0f}%{prev5[dim]*100:>8.0f}%{arrow:>9}")
print("-" * 104)
print(f"{'综合':<8}{'（会掩盖结构差异，仅供对照）':<34}{cur['综合']*100:>9.0f}%{prev5['综合']*100:>8.0f}%")

# 维度离散度 = 错位程度
disp = score[list(DIMS)].std(axis=1)
cur_disp = disp.iloc[-1]
rank_disp = (disp <= cur_disp).mean()
print(f"\n五维离散度（分位极差）: {cur_disp*100:.0f} 个百分点，处于历史 {rank_disp*100:.0f}% 分位")
print(f"  历史中位离散度 {disp.median()*100:.0f}pp，当前显著{'高于' if cur_disp > disp.median() else '低于'}常态")

# ---------- 每个维度的预测力（去 regime 后）----------
print("\n" + "=" * 104)
print("【维度有效性】逐年算 IC 再平均（组内），避免组间/组内效应抵消")
print("=" * 104)
print(f"\n{'维度':<10}{'fwd5':>9}{'fwd20':>9}{'fwd60':>9}{'同号年数':>10}{'结论':>28}")
print("-" * 104)
from scipy import stats
for dim in list(DIMS) + ["综合"]:
    out = []
    for h in [5, 20, 60]:
        ics = []
        for y in sorted(set(d.index.year)):
            m = d.index.year == y
            x = score[dim].values[m]; y_ = fwd[h].values[m]
            ok = (~np.isnan(x)) & (~np.isnan(y_))
            if ok.sum() > 100:
                ics.append(stats.spearmanr(x[ok], y_[ok]).correlation)
        out.append(np.nanmean(ics) if ics else np.nan)
    # 同号年数
    ics20 = []
    for y in sorted(set(d.index.year)):
        m = d.index.year == y
        x = score[dim].values[m]; y_ = fwd[20].values[m]
        ok = (~np.isnan(x)) & (~np.isnan(y_))
        if ok.sum() > 100:
            ics20.append(stats.spearmanr(x[ok], y_[ok]).correlation)
    same = sum(1 for v in ics20 if np.sign(v) == np.sign(np.nanmean(ics20)))
    mu = np.nanmean(ics20)
    if abs(mu) <= 0.05:
        concl = "无判别力"
    elif abs(mu) <= 0.10 or same < 9:
        concl = "弱"
    elif mu < 0:
        concl = "反向可用（均值回复）"
    else:
        concl = "顺势可用（动量延续）"
    print(f"{dim:<10}{out[0]:>9.3f}{out[1]:>9.3f}{out[2]:>9.3f}{same:>7}/{len(ics20):<3}{concl:>28}")

# ---------- 历史同类状态 ----------
print("\n" + "=" * 104)
print("【历史类比】当前五维组合画像的相似日，之后怎么走")
print("=" * 104)
TARGET = {k: cur[k] for k in DIMS}
print("\n当前画像: " + "  ".join(f"{k}={v*100:.0f}%" for k, v in TARGET.items()))
# 欧氏距离找最相似的 30 个交易日（排除未来 60 日不完整的）
_sc = score[list(DIMS)]
_ok = _sc.notna().all(axis=1) & fwd[60].notna()
diff = ((_sc.sub(pd.Series(TARGET), axis=1).pow(2).sum(axis=1)) ** 0.5)[_ok].sort_values()
nn = diff.head(40)
print(f"\n最相似 40 个交易日（距离最小），其历史日期与结果：")
print(f"{'日期':<12}{'距离':>7}{'量能':>7}{'广度':>7}{'极端':>7}{'赚钱':>7}{'结构':>7}{'fwd20':>9}{'fwd60':>9}")
print("-" * 104)
for dt in nn.index[:24]:
    s = score.loc[dt]
    print(f"{dt.strftime('%Y-%m-%d'):<12}{diff[dt]:>7.3f}"
          + "".join([f"{s[k]*100:>6.0f}%" for k in DIMS])
          + f"{fwd[20].loc[dt]*100:>8.2f}%{fwd[60].loc[dt]*100:>8.2f}%")

v20 = fwd[20].reindex(nn.index).dropna() * 100
v60 = fwd[60].reindex(nn.index).dropna() * 100
print(f"\n相似样本 fwd20: 均值 {v20.mean():.2f}%  中位 {v20.median():.2f}%  胜率 {(v20>0).mean():.0%}")
print(f"相似样本 fwd60: 均值 {v60.mean():.2f}%  中位 {v60.median():.2f}%  胜率 {(v60>0).mean():.0%}")
print(f"注意：相似样本高度集中在少数几段行情，有效独立观测远少于 40 个，胜率不可直接当概率用。")

score.to_csv(f"{BASE}/score.csv", encoding="utf-8")
print(f"\n写出 {BASE}/score.csv")
