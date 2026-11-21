"""事件研究：ETF 大额净流入（申赎口径）之后，指数还能不能跟着买。

执行口径：T 日盘后/次日披露净流入 -> T+1 开盘买入（保守：不给 T 日当天用信息的机会）。
持有 h 个交易日，以 T+1 开盘价入场、T+1+h-1 收盘价出场（与「开盘买、收盘计」同源）。
"""
import json
import numpy as np
import pandas as pd

OUT = "/opt/daily-tasks/workspace/analysis/out"
D = json.load(open("/tmp/islands.json"))
Q = json.load(open(f"{OUT}/quotes.json"))

# ---------- 1. 构造价格面板 ----------
def panel(code):
    bars = Q[code]["bars"]
    df = pd.DataFrame(bars).set_index("date")
    return df

idx = panel("sh000001")
nf = pd.Series(D["dailyData"]["netflow"], index=D["dailyData"]["dates"], dtype=float)
nf.index = pd.to_datetime(nf.index).strftime("%Y-%m-%d")

# 只用两者都有的交易日
common = [d for d in nf.index if d in idx.index]
nf = nf.loc[common]
idx = idx.loc[common]
print(f"对齐后 {len(common)} 个交易日 {common[0]} ~ {common[-1]}")
# 核对看板 idx 与腾讯收盘
board_idx = pd.Series(D["dailyData"]["idx"], index=D["dailyData"]["dates"], dtype=float)
board_idx.index = pd.to_datetime(board_idx.index).strftime("%Y-%m-%d")
diff = (board_idx.loc[common] - idx["close"]).abs().max()
print(f"看板 idx vs 腾讯上证收盘 最大偏差 {diff:.4f} 点")


def fwd_ret(df, h, entry="open"):
    """t+1 开盘入场，持有 h 日，返回按 t 对齐的收益序列（%）"""
    ent = df[entry].shift(-1)          # t+1 开盘
    ext = df["close"].shift(-(h))      # t+h 收盘（t+1 为第1天 -> 第 h 天是 t+h）
    return (ext / ent - 1) * 100


def clusters(dates_pos, gap, n):
    """相隔 < gap 的事件合并成簇，返回簇首位置"""
    heads = []
    last = -10**9
    for p in sorted(dates_pos):
        if p - last >= gap:
            heads.append(p)
            last = p
    return heads


def study(mask, h, label, df=None):
    df = idx if df is None else df
    r = fwd_ret(df, h)
    base = r.dropna()
    ev = r[mask].dropna()
    if len(ev) < 5:
        return None
    pos = [df.index.get_loc(d) for d in ev.index]
    heads = clusters(pos, h, len(df))
    ev_head = r.iloc[heads].dropna()
    t_all = ev.mean() / (ev.std(ddof=1) / np.sqrt(len(ev)))
    t_cl = (ev_head.mean() / (ev_head.std(ddof=1) / np.sqrt(len(ev_head)))
            if len(ev_head) > 2 else np.nan)
    return {
        "label": label, "h": h, "n_ev": len(ev), "n_cluster": len(ev_head),
        "mean": ev.mean(), "median": ev.median(), "win": (ev > 0).mean() * 100,
        "t_iid": t_all, "t_cluster": t_cl,
        "base_mean": base.mean(), "base_win": (base > 0).mean() * 100,
        "excess": ev.mean() - base.mean(),
    }


rows = []
TH = [(50, ">50亿"), (100, ">100亿"), (150, ">150亿"), (200, ">200亿"), (300, ">300亿")]
for k, lab in TH:
    m = nf > k
    for h in (1, 3, 5, 10, 20):
        s = study(m, h, f"净流入{lab}")
        if s:
            rows.append(s)

# 连续放量：3 日累计 > 300 亿
roll3 = nf.rolling(3).sum()
for h in (1, 3, 5, 10, 20):
    s = study(roll3 > 300, h, "3日累计>300亿")
    if s:
        rows.append(s)

# 净流出
for k, lab in [(-100, "<-100亿"), (-200, "<-200亿")]:
    m = nf < k
    for h in (1, 3, 5, 10, 20):
        s = study(m, h, f"净流出{lab}")
        if s:
            rows.append(s)

res = pd.DataFrame(rows)
pd.set_option("display.width", 200, "display.max_columns", 50)
print("\n=== 上证综指：T+1 开盘入场 ===")
print(res.round(2).to_string(index=False))
res.to_csv(f"{OUT}/event_study_sse.csv", index=False, encoding="utf-8-sig")

# ---------- 2. 逐事件明细（阈值 100 亿，h=5） ----------
r5 = fwd_ret(idx, 5)
r20 = fwd_ret(idx, 20)
detail = pd.DataFrame({
    "netflow": nf, "close": idx["close"],
    "ret_same_day": idx["close"].pct_change() * 100,
    "fwd5": r5, "fwd20": r20,
})
detail.to_csv(f"{OUT}/daily_panel.csv", encoding="utf-8-sig")
print("\n=== 分年度（阈值100亿，h=5） ===")
for y in (2023, 2024, 2025, 2026):
    m = (nf > 100) & (pd.to_datetime(nf.index).year == y)
    e = r5[m].dropna()
    b = r5[pd.to_datetime(r5.index).year == y].dropna()
    if len(e):
        print(f"{y}: n={len(e):2d} 事件均值{e.mean():+.2f}% 胜率{(e>0).mean()*100:.0f}% "
              f"| 同年基准{b.mean():+.2f}% 差{e.mean()-b.mean():+.2f}pp")

print("\n=== 2026-10 以来净流入 >100 亿的日期及后续 ===")
sub = detail[(nf > 100) & (nf.index >= "2026-09-01")]
print(sub.round(2).to_string())
