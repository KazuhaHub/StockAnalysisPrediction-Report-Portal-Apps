#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
情绪每日监控：把五维面板变成"每天扫一眼能改变动作"的读数。

与 sentiment_score.py 的分工：
  score.py  = 研究用，算 IC、相似日、逐年稳健性，慢
  daily.py  = 监控用，只算当前状态 + 变化 + 信号持续期，快

输出：
  analysis/out/sentiment/monitor.json         完整状态（机器读）
  analysis/out/sentiment/daily_log.csv        每日一行追加（看信号持续时间）
  reports/sentiment-monitor/assets/monitor-data.js   给面板用

用法：
  python3 sentiment_daily.py               # 全量重建面板后出监控
  python3 sentiment_daily.py --skip-build  # 用已有 panel.csv，只重算监控
"""
import os
import sys
import json
import subprocess

import numpy as np
import pandas as pd

WS = "/opt/daily-tasks/workspace"
BASE = f"{WS}/analysis/out/sentiment"
REPORT = f"{WS}/reports/sentiment-monitor"
PY = os.environ.get("PY", "/opt/daily-tasks/venv/bin/python3")

os.makedirs(BASE, exist_ok=True)
os.makedirs(f"{REPORT}/assets", exist_ok=True)

# ---------- 1. 可选重建面板 ----------
if "--skip-build" not in sys.argv:
    print("[1/3] 重建情绪面板（跟随行情库最新交易日）...", flush=True)
    r = subprocess.run([PY, f"{WS}/analysis/sentiment_build.py"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        if r.returncode < 0:
            # 被信号杀掉时子进程来不及写任何东西；SIGKILL 在容器里几乎总是内存超限
            why = "被信号 %d 终止%s" % (-r.returncode, "（多半是内存超限被 OOM 杀掉）" if r.returncode == -9 else "")
        else:
            why = "退出码 %d" % r.returncode
        sys.exit("面板重建失败：sentiment_build.py " + why)
    print("    ok")
else:
    print("[1/3] 跳过重建，复用 panel.csv")

d = pd.read_csv(f"{BASE}/panel.csv", index_col=0, parse_dates=True)
ASOF = d.index[-1]
NAV = d["eq_nav"]
fwd = {h: NAV.shift(-h) / NAV - 1 for h in [5, 20, 60]}

# ---------- 2. 五维评分（与 sentiment_score.py 同源，改动需同步）----------
DIMS = {
    "量能": {"desc": "钱还在不在场（决定仓位能否放大）",
             "items": {"amt_per_stock_pct": +1, "amt_ratio20_pct": +1, "amt_z60_pct": +1}},
    "广度": {"desc": "上涨是普涨还是少数股独舞（决定赚钱难度）",
             "items": {"above_ma20_pct": +1, "above_ma60_pct": +1, "above_ma250_pct": +1,
                       "pct_adv_pct": +1, "new_high_pct_pct": +1, "new_low_pct_pct": -1}},
    "极端": {"desc": "恐慌/亢奋的尾部强度（决定赔率）",
             "items": {"limit_up_pct": +1, "limit_down_pct": -1, "dd20_pct_pct": -1}},
    "赚钱效应": {"desc": "持有体验，决定散户是否敢加仓",
                 "items": {"r20_positive_pct": +1, "r20_median_pct": +1}},
    "资金结构": {"desc": "钱是分散还是抱团（抱团=有主线，也=脆弱）",
                 "items": {"top10_amt_share_pct": +1, "hhi_pct": +1}},
}

score = pd.DataFrame(index=d.index)
for dim, cfg in DIMS.items():
    vals = [d[k] if s > 0 else (1 - d[k]) for k, s in cfg["items"].items()]
    score[dim] = pd.concat(vals, axis=1).mean(axis=1)
score["综合"] = score[list(DIMS)].mean(axis=1)
score.to_csv(f"{BASE}/score.csv", encoding="utf-8")


def at(n):
    """取倒数第 n 个交易日的评分行（n=1 即当日）"""
    return score.iloc[-n] if len(score) >= n else score.iloc[0]


cur, d1, d5, d20 = at(1), at(2), at(6), at(21)

# 维度有效性结论（研究结论，硬编码自 sentiment_score.py 逐年 IC；每年复核一次）
VERDICT = {
    "量能": "弱（IC −0.06，方向不稳）",
    "广度": "反向可用（逐年 IC 均负，去 regime 后 −0.35）",
    "极端": "弱（IC −0.08）",
    "赚钱效应": "无判别力（IC −0.03）",
    "资金结构": "无判别力（IC +0.02），但是条件变量",
}

dims_out = []
for k, cfg in DIMS.items():
    dims_out.append({
        "k": k, "desc": cfg["desc"],
        "v": round(float(cur[k]) * 100, 1),
        "d1": round(float(d1[k]) * 100, 1),
        "d5": round(float(d5[k]) * 100, 1),
        "d20": round(float(d20[k]) * 100, 1),
        "chg5": round(float(cur[k] - d5[k]) * 100, 1),
        "chg20": round(float(cur[k] - d20[k]) * 100, 1),
        "verdict": VERDICT[k],
    })

# 离散度 = 错位程度
disp = score[list(DIMS)].std(axis=1)
cur_disp = float(disp.iloc[-1])
rank_disp = float((disp <= cur_disp).mean())

# ---------- 3. 组合格：广度 × 集中度 ----------
bins_b = [0, 0.10, 0.20, 0.35, 1.01]
bins_c = [0, 0.34, 0.67, 1.01]
lab_b = ["广度<10%", "10–20%", "20–35%", ">35%"]
lab_c = ["集中度低", "中", "集中度高"]

cur_b_raw = float(d["above_ma250"].iloc[-1])       # 原始比例
conc = d["top10_amt_share_pct"]                     # 3 年分位
cur_c = float(conc.iloc[-1])


def locate(v, bins):
    return max(i for i in range(len(bins) - 1) if v >= bins[i])


bi, ci = locate(cur_b_raw, bins_b), locate(cur_c, bins_c)

grid = []
for i in range(len(bins_b) - 1):
    row = []
    for j in range(len(bins_c) - 1):
        m = ((d["above_ma250"] >= bins_b[i]) & (d["above_ma250"] < bins_b[i + 1]) &
             (conc >= bins_c[j]) & (conc < bins_c[j + 1]))
        n = int(m.sum())
        v = fwd[20][m].median() * 100
        row.append({"v": (round(float(v), 2) if n >= 20 and not np.isnan(v) else None),
                    "n": n, "cur": (i == bi and j == ci)})
    grid.append(row)

cell_mask = ((d["above_ma250"] >= bins_b[bi]) & (d["above_ma250"] < bins_b[bi + 1]) &
             (conc >= bins_c[ci]) & (conc < bins_c[ci + 1]))
cell_v = fwd[20][cell_mask].median() * 100
cell_n = int(cell_mask.sum())

# ---------- 4. 信号跟踪：广度极冷事件的持续期与进度 ----------
COLD = 0.15


def cluster_starts(mask, gap=3):
    idx = np.where(np.nan_to_num(mask, nan=0).astype(bool))[0]
    if len(idx) == 0:
        return []
    out, prev = [idx[0]], idx[0]
    for i in idx[1:]:
        if i - prev > gap:
            out.append(i)
        prev = i
    return out


sig = (d["above_ma250"] < COLD).values
starts = cluster_starts(sig)
still_in = bool(sig[-1])
last_start = starts[-1] if starts else None
days_since = int(len(d) - 1 - last_start + 1) if last_start is not None else 0
ret_since = (NAV.iloc[-1] / NAV.iloc[last_start] - 1) * 100 if last_start is not None else None

# 历史簇的前瞻路径（0..20 日累积收益），用于对照"走到第几天、还剩多少"
PATH_N = 21
paths = []
for s0 in starts[:-1] if still_in else starts:
    if s0 + PATH_N > len(NAV):
        continue
    seg = NAV.iloc[s0:s0 + PATH_N].values
    paths.append(seg / seg[0] - 1)
hist_path = (np.median(np.array(paths), axis=0) * 100) if paths else np.array([])

hist_fwd20 = []
for s0 in (starts[:-1] if still_in else starts):
    v = fwd[20].iloc[s0]
    if not np.isnan(v):
        hist_fwd20.append(v * 100)
hist_fwd20 = np.array(hist_fwd20)

signal = {
    "active": still_in,
    "n_clusters": len(starts),
    "trigger": str(d.index[last_start].date()) if last_start is not None else None,
    "trigger_val": (round(float(d["above_ma250"].iloc[last_start]) * 100, 1) if last_start is not None else None),
    "days": days_since,
    "ret_since": (round(float(ret_since), 2) if ret_since is not None else None),
    "hist_med20": (round(float(np.median(hist_fwd20)), 2) if len(hist_fwd20) else None),
    "hist_win20": (round(float((hist_fwd20 > 0).mean()) * 100, 0) if len(hist_fwd20) else None),
    "hist_n": int(len(hist_fwd20)),
    "path": [round(float(v), 2) for v in hist_path],
    "cur_path": [round(float(v), 2) for v in (NAV.iloc[last_start:len(d)] / NAV.iloc[last_start] - 1) * 100]
    if last_start is not None else [],
}
# 本轮最低点（供对照：研究报告正文用 10-29 取点，与规则簇起点不同）
_tail_start = d.index[max(0, len(d) - 60)]
_recent = d["above_ma250"].loc[_tail_start:]
if still_in and len(_recent):
    _ci = _recent.idxmin()
    _s0 = float(NAV.loc[_ci])
    signal["coldest"] = {
        "date": str(_ci.date()),
        "val": round(float(_recent.min()) * 100, 1),
        "ret": round(float(NAV.iloc[-1] / _s0 - 1) * 100, 2),
    }

# ---------- 5. 极端读数（原始值，不是分位）----------
extreme = [
    {"name": "站上 MA250", "v": f"{cur_b_raw*100:.1f}%", "pct": round(float(d['above_ma250_pct'].iloc[-1]) * 100)},
    {"name": "跌停家数", "v": f"{int(d['limit_down'].iloc[-1])}", "pct": round(float(d['limit_down_pct'].iloc[-1]) * 100)},
    {"name": "涨停家数", "v": f"{int(d['limit_up'].iloc[-1])}", "pct": round(float(d['limit_up_pct'].iloc[-1]) * 100)},
    {"name": "成交额前10%占比", "v": f"{d['top10_amt_share'].iloc[-1]*100:.1f}%", "pct": round(cur_c * 100)},
    {"name": "20日跌超20%", "v": f"{d['dd20_pct'].iloc[-1]*100:.1f}%", "pct": round(float(d['dd20_pct_pct'].iloc[-1]) * 100)},
    {"name": "每股成交额", "v": f"{d['amt_per_stock'].iloc[-1]/1e8:.2f}亿", "pct": round(float(d['amt_per_stock_pct'].iloc[-1]) * 100)},
    {"name": "已实现波动率", "v": f"{d['eq_vol20'].iloc[-1]*100:.1f}%", "pct": round(float(d['eq_vol20_pct'].iloc[-1]) * 100)},
]

# ---------- 6. 预警：规则化，每条都指向一个具体动作 ----------
alerts = []


def add(level, title, body):
    alerts.append({"level": level, "title": title, "body": body})


# 6.1 广度 × 集中度 组合格
if cell_v is None or np.isnan(cell_v):
    add("gray", "组合格样本不足", f"「{lab_b[bi]} × {lab_c[ci]}」历史交易日少于 20 个，不做统计推断。")
elif cell_v < 0:
    add("red", f"历史最差格：{lab_b[bi]} × {lab_c[ci]}",
        f"该格历史 20 日中位收益 <b>{cell_v:+.2f}%</b>（{cell_n} 个交易日）。"
        f"广度冷不等于便宜——集中度高说明资金还在少数堡垒里，没撤退完，此时抄底是接盘。")
elif cell_v < 1.5:
    add("amber", f"组合格偏弱：{lab_b[bi]} × {lab_c[ci]}",
        f"该格历史 20 日中位收益 <b>{cell_v:+.2f}%</b>（{cell_n} 个交易日）。赔率不够，等结构改善。")
else:
    add("green", f"组合格有利：{lab_b[bi]} × {lab_c[ci]}",
        f"该格历史 20 日中位收益 <b>{cell_v:+.2f}%</b>（{cell_n} 个交易日）。广度冷 + 资金分散 = 卖压释放型出清，可分批。")

# 6.2 集中度是否在松动（决定"出清"能否完成）
conc_chg20 = float(conc.iloc[-1] - conc.iloc[-21]) * 100 if len(conc) > 21 else 0.0
if cur_c >= 0.85 and conc_chg20 > -3:
    add("amber", "资金集中度仍处极热且未松动",
        f"集中度分位 <b>{cur_c*100:.0f}%</b>，20 日变化 {conc_chg20:+.0f}pp。"
        f"这是「撤退型」而非「出清型」的特征。出清的必要条件之一是集中度趋势性回落，目前没看到。")
elif cur_c >= 0.85:
    add("green", "集中度开始松动",
        f"集中度分位 {cur_c*100:.0f}%，20 日已回落 {conc_chg20:+.0f}pp。抱团解体是广度修复的前提，这个方向对了。")
else:
    add("gray", "集中度不在极热区",
        f"集中度分位 {cur_c*100:.0f}%，不构成结构性压制。")

# 6.3 信号持续期
if still_in:
    prog = signal["ret_since"]
    left = (signal["hist_med20"] - prog) if signal["hist_med20"] is not None and prog is not None else None
    _c = signal.get("coldest")
    _ctxt = (f"（若以本轮最低点 {_c['date']} 计为 {_c['ret']:+.2f}%）" if _c else "")
    add("red" if (signal["days"] >= 15 and prog is not None and prog < 0) else
        ("amber" if signal["days"] >= 20 else "green"),
        f"广度极冷信号第 {signal['days']} 个交易日",
        f"自 {signal['trigger']}（广度 {signal['trigger_val']}%）触发以来，等权组合 <b>{prog:+.2f}%</b>{_ctxt}。"
        + (f"历史 {signal['hist_n']} 个同类事件 20 日中位 {signal['hist_med20']:+.2f}%、胜率 {signal['hist_win20']:.0f}%，"
           f"按中位算剩余空间约 {left:+.2f}pp，"
           if left is not None else "")
        + f"但历史上这一形态最长持续 140 个交易日（2018）。"
        f"<b>触发即买是错的</b>：买点要等集中度回落，或广度站上 35%。")
else:
    add("gray", "广度已脱离极冷区",
        f"上一轮极冷自 {signal['trigger']} 起持续 {signal['days']} 个交易日，当前占比 {cur_b_raw*100:.1f}%（阈值 15%）。"
        f"信号解除不等于趋势反转，看广度能否站上 20–35% 才是关键。")

# 6.4 离散度：结构分化
if rank_disp >= 0.80:
    add("amber", "五维严重错位，不要看综合分",
        f"离散度 {cur_disp*100:.0f}pp，历史 {rank_disp*100:.0f}% 分位。"
        f"此时任何合成指数（含大摩 MSASI）都会把结构差异平均掉，必须分维度看。")
else:
    add("gray", "维度分歧在正常范围",
        f"离散度 {cur_disp*100:.0f}pp，历史 {rank_disp*100:.0f}% 分位。")

# 一句话结论
_ret = signal["ret_since"]
if cell_v is not None and not np.isnan(cell_v) and cell_v < 0:
    headline = "结构性出清未完成：广度冷但资金没散，不构成买点"
elif cell_v is not None and not np.isnan(cell_v) and cell_v > 3:
    headline = "广度极冷 + 资金分散，历史同类赔率最好，可分批"
elif still_in and _ret is not None and _ret < 0 and signal["days"] >= 12:
    headline = f"极冷信号第 {signal['days']} 日仍未转正，等集中度松动或广度回升确认"
else:
    headline = "情绪低位但结构未改善，等集中度回落或广度回升再动"

# ---------- 7. 近 250 日轨迹 ----------
hist = d.iloc[-250:]
traj = {
    "dates": [str(x.date()) for x in hist.index],
    "series": {k: [round(float(v) * 100, 1) if not np.isnan(v) else None
                   for v in score[k].iloc[-250:]] for k in DIMS},
}

# ---------- 8. 输出 ----------
mon = {
    "asof": str(ASOF.date()),
    "headline": headline,
    "dims": dims_out,
    "disp": {"v": round(cur_disp * 100, 0), "rank": round(rank_disp * 100, 0)},
    "cell": {"b": lab_b[bi], "c": lab_c[ci], "v": (round(float(cell_v), 2) if not np.isnan(cell_v) else None), "n": cell_n},
    "grid": {"x": lab_c, "y": lab_b, "cells": grid},
    "signal": signal,
    "extreme": extreme,
    "alerts": alerts,
    "traj": traj,
    "conclusion": {
        "v": (round(float(cur["综合"]) * 100, 1)),
        "note": "综合分仅作对照，不作决策依据——它会掩盖 30pp 级的维度错位",
    },
}

with open(f"{BASE}/monitor.json", "w", encoding="utf-8") as f:
    json.dump(mon, f, ensure_ascii=False, indent=1)

# 给面板用的 JS 变量
with open(f"{REPORT}/assets/monitor-data.js", "w", encoding="utf-8") as f:
    f.write("window.MONITOR = ")
    json.dump(mon, f, ensure_ascii=False)
    f.write(";\n")

# 每日留档（追加，不覆盖）
log_row = {"date": str(ASOF.date())}
log_row.update({k: round(float(cur[k]), 4) for k in DIMS})
log_row.update({
    "综合": round(float(cur["综合"]), 4),
    "离散度": round(cur_disp, 4),
    "above_ma250": round(cur_b_raw, 4),
    "集中度分位": round(cur_c, 4),
    "组合格": f"{lab_b[bi]}×{lab_c[ci]}",
    "该格fwd20中位": (round(float(cell_v), 2) if not np.isnan(cell_v) else None),
    "极冷信号天数": days_since if still_in else 0,
})
log_path = f"{BASE}/daily_log.csv"
log = pd.DataFrame([log_row])
if os.path.exists(log_path):
    old = pd.read_csv(log_path)
    log = pd.concat([old[old["date"] != log_row["date"]], log], ignore_index=True)
log.to_csv(log_path, index=False, encoding="utf-8")

print(f"\n基准日 {mon['asof']}  |  {headline}")
print("─" * 78)
for x in dims_out:
    arrow = "↑" if x["chg5"] > 2 else ("↓" if x["chg5"] < -2 else "→")
    print(f"  {x['k']:<5}{x['v']:>6.1f}%   5日 {x['chg5']:+5.1f}pp {arrow}   {x['verdict']}")
print("─" * 78)
print(f"  组合格 {lab_b[bi]} × {lab_c[ci]}  →  历史 fwd20 中位 "
      f"{cell_v:+.2f}%  (n={cell_n})" if not np.isnan(cell_v) else "  组合格样本不足")
print(f"  离散度 {cur_disp*100:.0f}pp (历史 {rank_disp*100:.0f}% 分位)")
print(f"\n预警 {len(alerts)} 条：")
for a in alerts:
    print(f"  [{a['level']:<5}] {a['title']}")
print(f"\n写出 {BASE}/monitor.json, daily_log.csv, {REPORT}/assets/monitor-data.js")
