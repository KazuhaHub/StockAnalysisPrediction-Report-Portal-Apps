# -*- coding: utf-8 -*-
"""
池子规模对横截面判定功效的影响 —— 实测
用 ~/MarketData 全库 1521 只 vs quant-signal-research 现有 55 只池
同一批信号、同一口径、同一区间，只换标的池，看 t 值怎么变。
"""
import sys, json, os
sys.path.insert(0, "/opt/daily-tasks/MarketData")
import numpy as np
import pandas as pd
import market_data as md

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
START = "2019-01-01"
FWD = 5          # 持有期，与 registry 多数信号一致
MIN_SIG = 5      # 某日至少几只触发才算一个有效横截面日

print("loading ...", flush=True)
close = md.panel("close", start=START)
openp = md.panel("open", start=START)
print("panel", close.shape, close.index[0], close.index[-1], flush=True)

# 后复权口径；t 日收盘出信号，t+1 开盘成交
fwd = close.shift(-FWD) / openp.shift(-1) - 1.0

d = close.diff()
gain = d.clip(lower=0).rolling(14).mean()
loss = (-d.clip(upper=0)).rolling(14).mean()
rsi14 = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

hi20_prev = close.shift(1).rolling(20).max()

# 连续下跌天数
down = (d < 0).astype(np.int8)
streak = pd.DataFrame(0, index=close.index, columns=close.columns, dtype=np.int16)
arr_d = down.values
arr_s = streak.values
for i in range(1, len(arr_d)):
    cur = arr_s[i - 1] + 1
    arr_s[i] = np.where(arr_d[i] == 1, cur, 0)
streak = pd.DataFrame(arr_s, index=close.index, columns=close.columns)

vma20 = None
try:
    vol = md.panel("volume", start=START)
    vma20 = vol.rolling(20).mean()
    vr = vol / vma20
except Exception as e:
    print("volume unavailable:", e, flush=True)

SIGNALS = {
    "SIG-003 RSI14<30":        (rsi14 < 30),
    "SIG-004 收盘创20日新高":   (close >= hi20_prev),
    "SIG-006 连跌3日":          (streak >= 3),
}
if vr is not None:
    SIGNALS["SIG-009 放量突破20日新高"] = (close >= hi20_prev) & (vr > 1.5)

# 现有 55 只池
pool_path = os.path.expanduser("~/.workbuddy/skills/quant-signal-research/data/klines_ohlcv.json")
with open(pool_path) as f:
    pool_raw = json.load(f)
pool55 = sorted({k.split(".")[0] for k in pool_raw if k != "_meta"})
print("pool55 n =", len(pool55), flush=True)


def cs_test(mask, ret, min_sig=MIN_SIG):
    """同日横截面：有信号 vs 无信号 的未来收益差，逐日一条，再对序列做 t 检验"""
    mask = mask & ret.notna()
    n_sig = mask.sum(axis=1)
    ok = n_sig >= min_sig
    if ok.sum() < 20:
        return None
    m = mask.values
    r = ret.values
    valid = ~np.isnan(r)
    diffs = []
    ns = []
    for i in np.where(ok.values)[0]:
        mi = m[i] & valid[i]
        ni = (~m[i]) & valid[i]
        if mi.sum() < min_sig or ni.sum() < min_sig:
            continue
        diffs.append(r[i][mi].mean() - r[i][ni].mean())
        ns.append(mi.sum())
    if len(diffs) < 20:
        return None
    diffs = np.array(diffs)
    n = len(diffs)
    mu = diffs.mean()
    sd = diffs.std(ddof=1)
    t = mu / (sd / np.sqrt(n))
    # Newey-West (lag=5) 修正自相关
    x = diffs - mu
    g0 = (x @ x) / n
    s = g0
    for L in range(1, 6):
        gl = (x[L:] @ x[:-L]) / n
        s += 2 * (1 - L / 6) * gl
    t_nw = mu / np.sqrt(s / n) if s > 0 else np.nan
    return dict(n_days=n, mean_diff_bp=mu * 1e4, t=t, t_nw=t_nw,
                avg_n_sig=float(np.mean(ns)), win=float((diffs > 0).mean()))


rows = []
for label, universe in [("全库 1521 只", None), ("现有 55 只池", pool55)]:
    if universe is None:
        cols = [c for c in close.columns]
    else:
        cols = [c for c in close.columns if c in set(universe)]
    print(f"\n===== {label}  (n={len(cols)}) =====", flush=True)
    for name, mask in SIGNALS.items():
        r = cs_test(mask[cols], fwd[cols])
        if r is None:
            print(f"{name}: INSUFFICIENT", flush=True)
            rows.append(dict(pool=label, n_stocks=len(cols), signal=name, status="INSUFFICIENT"))
            continue
        print(f"{name}: Δ={r['mean_diff_bp']:+.1f}bp  t={r['t']:.2f}  t_NW={r['t_nw']:.2f}  "
              f"日数={r['n_days']}  日均触发={r['avg_n_sig']:.0f}只  胜率={r['win']:.1%}", flush=True)
        rows.append(dict(pool=label, n_stocks=len(cols), signal=name, status="OK", **r))

out = pd.DataFrame(rows)
os.makedirs(OUT_DIR, exist_ok=True)
out.to_csv(os.path.join(OUT_DIR, "pool_effect.csv"), index=False)
print("\nsaved pool_effect.csv")
print(out.to_string())
