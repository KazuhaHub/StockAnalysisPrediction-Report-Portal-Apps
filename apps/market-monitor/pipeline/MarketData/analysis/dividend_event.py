# -*- coding: utf-8 -*-
"""
把播客里一个具体判断变成可检验命题：
  "红利指数两个月跌超 10%，过去 10 年相当少见，且都是入手机会" —— 董梁，2026-11
同时检验：这是红利特有，还是所有宽基都这样（普适的均值回归）？
方法：事件研究 + 全样本基准率 + 安慰剂（随机抽同样数量日期）
"""
import os, warnings, json
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import akshare as ak

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

IDX = {
    "000922 中证红利": "000922",
    "H30269 红利低波": "H30269",
    "000300 沪深300": "000300",
    "000905 中证500": "000905",
}
LOOKBACK = 40      # 约两个月
THRESH = -0.10
HORIZONS = [20, 60]
COOLDOWN = 40
N_PLACEBO = 20000
SEED = 20261107

def fetch(symbol):
    df = ak.index_zh_a_hist(symbol=symbol, period="daily",
                            start_date="20131201", end_date="20261106")
    df = df[["日期", "开盘", "收盘"]].copy()
    df.columns = ["date", "open", "close"]
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)

def events_of(close, lookback=LOOKBACK, thresh=THRESH):
    c = pd.Series(np.asarray(close, dtype=float))
    r = c / c.shift(lookback) - 1.0
    hit = (r <= thresh).fillna(False).values
    idx, last = [], -10**9
    for i in np.where(hit)[0]:
        if i - last >= COOLDOWN:
            idx.append(i); last = i
    return idx, r

def fwd_ret(close, openp, i, h):
    j = i + 1                      # t+1 入场
    k = i + h
    if k >= len(close) or j >= len(close):
        return np.nan
    return close[k] / openp[j] - 1.0

rng = np.random.default_rng(SEED)
results = []

for label, sym in IDX.items():
    try:
        df = fetch(sym)
    except Exception as e:
        print(f"{label}: fetch failed {e}")
        continue
    close = df["close"].values.astype(float)
    openp = df["open"].values.astype(float)
    ev, r40 = events_of(close)
    print(f"\n===== {label}  n={len(df)}  {df['date'].iloc[0].date()}~{df['date'].iloc[-1].date()} =====")
    print(f"  '{LOOKBACK}日跌幅≤{THRESH:.0%}' 触发次数 = {len(ev)}"
          + (f"，日期：{[str(df['date'].iloc[i].date()) for i in ev]}" if len(ev) <= 12 else ""))
    for h in HORIZONS:
        all_f = np.array([fwd_ret(close, openp, i, h) for i in range(len(close))])
        valid = ~np.isnan(all_f)
        base_mu = np.nanmean(all_f)
        base_win = np.nanmean(all_f[valid] > 0)
        ev_f = np.array([fwd_ret(close, openp, i, h) for i in ev])
        ev_f = ev_f[~np.isnan(ev_f)]
        if len(ev_f) == 0:
            continue
        ev_mu, ev_win = ev_f.mean(), (ev_f > 0).mean()
        # 安慰剂：随机抽同样数量、同样不重叠约束的日期
        cand = np.where(valid)[0]
        sims = np.empty(N_PLACEBO)
        for s in range(N_PLACEBO):
            pick = rng.choice(cand, size=len(ev_f), replace=True)
            sims[s] = np.nanmean(all_f[pick])
        pct = (sims < ev_mu).mean()
        excess = ev_mu - base_mu
        print(f"  h={h:>2}d | 事件后均值 {ev_mu:+.2%}  胜率 {ev_win:.0%} (n={len(ev_f)})"
              f" | 基准 {base_mu:+.2%} 胜率 {base_win:.0%}"
              f" | 超额 {excess:+.2%} | 安慰剂分位 {pct:.1%}")
        results.append(dict(index=label, horizon=h, n_events=int(len(ev_f)),
                            event_mean=ev_mu, event_win=ev_win,
                            base_mean=base_mu, base_win=base_win,
                            excess=excess, placebo_pct=pct))

os.makedirs(OUT_DIR, exist_ok=True)
pd.DataFrame(results).to_csv(
    os.path.join(OUT_DIR, "dividend_event.csv"), index=False)
print("\nsaved dividend_event.csv")
