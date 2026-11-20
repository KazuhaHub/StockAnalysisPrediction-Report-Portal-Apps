#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""广合科技 001389.SZ —— 止损宽度输入（单票，近 60 有效交易日）。

口径（与 quant-signal-research / SIG-002 的**公式**一致，但样本不是 SIG-002 判定总体）：
  A     = mean_i |c[i+5]/c[i] - 1|            端点振幅，与 qsr.py:685 同式
  MAE_i = 1 - min(low[i+1:i+6]) / c[i]        期间最大不利偏移，与 qsr.py:690 同式
  k_cal = quantile(MAE_i / A, 1 - 0.20)       按 20% 触发率反解，与 qsr.py:732-733 同式
  trig  = mean(MAE_i > k*A)                   触发率校验，与 qsr.py:730 同式
  vol20 = rolling_std(ret, 20) * sqrt(244)    与 qdata.py:252 同式，用于定位分档

纪律：本结果是**单票描述统计 / 风险刻画**，不是 SIG-002 的判定产物。
      001389 于 2024-04-02 上市，被 SIG-002 检验总体
      （start=2018-01-01，min_list_years=3，cutoff=2015-01-01）剔除，
      `qsr sizing-table --target 001389` 返回「标的池里没有 001389」。
      因此 SIG-002 的 t 值 / PROMOTE / STABLE·BROAD **不背书**这里的 A 与 k。

解释器：/opt/daily-tasks/venv/bin/python3
数据源：~/MarketData/bars/*.parquet（stock-server daily_hfq，后复权），经 md.load
输出：  analysis/out/stop_width_001389.{json,txt}
"""
import sys
import os
import json

sys.path.insert(0, "/opt/daily-tasks/MarketData")
import numpy as np
import market_data as md

CODE = "001389"
H = 5                     # 5 日窗口
N_BARS = 60               # 近 60 个有效交易日
BREACH = 0.20             # 目标触发率 20%
END = "2026-11-11"
START = "2024-01-01"      # 001389 上市 2024-04-02，全历史覆盖
QSR_REG = "/opt/daily-tasks/.workbuddy/skills/quant-signal-research/registry/sizing_table.json"
QSR_SIG = "/opt/daily-tasks/.workbuddy/skills/quant-signal-research/registry/signals.json"
OUT_DIR = "/opt/daily-tasks/MarketData/analysis/out"
os.makedirs(OUT_DIR, exist_ok=True)

# ---------------------------------------------------------------- 1. 取数 + 过滤停牌零成交日
df = md.load([CODE], start=START, end=END, as_datetime=False)
df = df.sort_values("date").reset_index(drop=True)
n_raw = len(df)
zero_mask = (df["volume"] <= 0) | (df["amount"] <= 0)
n_zero_all = int(zero_mask.sum())
# 原始最后 60 根里有多少根是停牌零成交日（切片前统计，用于披露过滤量）
n_zero_in_raw_last60 = int(zero_mask.to_numpy()[-N_BARS:].sum())
df = df[~zero_mask].reset_index(drop=True)

c_all = df["close"].to_numpy(float)
lo_all = df["low"].to_numpy(float)
hi_all = df["high"].to_numpy(float)
fac_all = df["factor"].to_numpy(float)
dates_all = df["date"].tolist()
n_valid = len(df)
assert n_valid >= N_BARS, f"有效 K 线仅 {n_valid} 根，不足 {N_BARS}"

# 样本区间 = 最后 60 根有效 K 线；过滤零成交日发生在切片之前
c = c_all[-N_BARS:]
lo = lo_all[-N_BARS:]
hi = hi_all[-N_BARS:]
fac = fac_all[-N_BARS:]
dates = dates_all[-N_BARS:]
n_zero_in_window = 0                    # 切片前已过滤，窗口内为零成交日 0 根

# ---------------------------------------------------------------- 2. A、MAE、k_cal、触发率校验
n_win = N_BARS - H                      # 60 根 → 55 个完整且端点都在区间内的 5 日窗口
fwd = np.array([abs(c[i + H] / c[i] - 1.0) for i in range(n_win)])
mae = np.array([-(lo[i + 1:i + 1 + H].min() / c[i] - 1.0) for i in range(n_win)])

A = float(fwd.mean())                   # 档内均值 → 此处为「单票窗口均值」
A_median = float(np.median(fwd))
mae_mean = float(mae.mean())
ratio = mae / A
k_cal = float(np.quantile(ratio, 1 - BREACH))     # 反解：P(MAE > k*A) = 0.20
k_floor = 0.6
k_used = max(k_cal, k_floor)            # qsr.py:858 同式：0.6 只是地板
trig_cal = float((mae > k_used * A).mean())       # 触发率校验（用实际采用的 k）
trig_06 = float((mae > k_floor * A).mean())       # k=0.6 的对照触发率
S = k_used * A                          # 止损幅度
n_hit_cal = int((mae > k_used * A).sum())

# ---------------------------------------------------------------- 3. vol20（qdata 同式）与分档定位
ret = np.full(len(c_all), np.nan)
ret[1:] = c_all[1:] / c_all[:-1] - 1.0
def _roll_std(x, n):
    out = np.full(len(x), np.nan)
    w = np.lib.stride_tricks.sliding_window_view(x, n)
    out[n - 1:] = w.std(axis=1)
    return out
vol20_series = _roll_std(ret, 20) * np.sqrt(244)
vol20_last = float(vol20_series[-1])

reg = json.load(open(QSR_REG))
bins = reg["bins"]
# SIG-002 稳定性锚：只读登记表，不在本标的重测（stab 是按票重抽的横截面检验）
_sigreg = json.load(open(QSR_SIG))
_sigs = _sigreg["signals"] if isinstance(_sigreg, dict) else _sigreg
if isinstance(_sigs, dict):
    _s002 = _sigs.get("SIG-002") or next(v for k, v in _sigs.items() if v.get("id") == "SIG-002")
else:
    _s002 = next(x for x in _sigs if x.get("id") == "SIG-002")
stab = _s002.get("stability") or {}
grade = stab.get("grade")
scope = stab.get("scope")
idx = 0
for i, b in enumerate(bins):
    if (b["vol_lo"] is None or vol20_last >= b["vol_lo"]) and \
       (b["vol_hi"] is None or vol20_last < b["vol_hi"]):
        idx = i
        break
b = bins[idx]
A_pool = b["amp_pct"] / 100.0
k_pool = max(float(b["k_cal"]), float(reg.get("stop_coef") or 0.6))
S_pool = k_pool * A_pool

# ---------------------------------------------------------------- 4. 2026-11-11 真实收盘价与止损参考价
P_hfq = float(c[-1])
factor_last = float(fac[-1])
P = P_hfq / factor_last                  # 数据字典 §2.1：真实价 = close / factor
stop_px = P * (1 - S)
stop_px_pool = P * (1 - S_pool)

# 价格换算自检：真实 VWAP = amount/(volume*factor) 必须落在当日真实 [low, high] 内
amt_last = float(df["amount"].to_numpy(float)[-1])
vol_last = float(df["volume"].to_numpy(float)[-1])
real_vwap = amt_last / (vol_last * factor_last)
real_low = float(lo[-1]) / factor_last
real_high = float(hi[-1]) / factor_last
px_check = bool(real_low - 1e-6 <= real_vwap <= real_high + 1e-6
               and real_low - 1e-6 <= P <= real_high + 1e-6)

# 数据质量：窗口内复权因子变化 / 单日极端收益（数据字典瑕疵 #4）
fac_chg = int((np.abs(np.diff(fac)) > 1e-9).sum())
r_window = np.diff(c) / c[:-1]
n_extreme = int((np.abs(r_window) > 0.30).sum())

res = {
    "code": CODE, "end": END, "interpreter": sys.executable,
    "source": "~/MarketData/bars/*.parquet (md.load), stock-server daily_hfq 后复权",
    "filter": "volume>0 且 amount>0（停牌零成交日）",
    "n_raw_bars": n_raw, "n_zero_all": n_zero_all, "n_valid_bars": n_valid,
    "n_bars_in_window": N_BARS, "n_zero_in_window": n_zero_in_window,
    "n_zero_in_raw_last60": n_zero_in_raw_last60,
    "window_first_date": dates[0], "window_last_date": dates[-1],
    "n_windows": n_win, "horizon": H,
    "A_pct": round(A * 100, 4), "A_median_pct": round(A_median * 100, 4),
    "mae_mean_pct": round(mae_mean * 100, 4),
    "breach_target": BREACH, "k_cal": round(k_cal, 4),
    "k_floor": k_floor, "k_used": round(k_used, 4),
    "trigger_cal_pct": round(trig_cal * 100, 2), "n_hit_cal": n_hit_cal,
    "trigger_k06_pct": round(trig_06 * 100, 2),
    "S_pct": round(S * 100, 4),
    "vol20_annual_pct": round(vol20_last * 100, 2),
    "pool_bin_index": idx + 1, "pool_bin_label": b["label"],
    "pool_bin_vol_range": b["vol_range"],
    "pool_A_pct": round(A_pool * 100, 2), "pool_k_cal": round(k_pool, 3),
    "pool_S_pct": round(S_pool * 100, 2),
    "pool_n_stocks": reg["n_stocks"], "pool_n_points": reg["n_points"],
    "pool_generated": reg["generated"],
    "P_hfq": round(P_hfq, 4), "factor_last": round(factor_last, 6),
    "P_real": round(P, 4), "stop_px": round(stop_px, 4),
    "stop_px_pool": round(stop_px_pool, 4),
    "px_check": px_check, "real_low": round(real_low, 4),
    "real_high": round(real_high, 4), "real_vwap": round(real_vwap, 4),
    "factor_changes_in_window": fac_chg, "abs_ret_gt30pct_in_window": n_extreme,
    "sig002_status": _s002.get("status"),
    "sig002_stability": {
        "grade": grade, "scope": scope,
        "sign_agree": stab.get("sign_agree"), "sig_rate": stab.get("sig_rate"),
        "full_t": stab.get("full_t"), "n_stocks": stab.get("n_stocks"),
        "n_boot": stab.get("n_boot"), "checked_at": stab.get("checked_at"),
        "retested_here": False,
    },
}

with open(os.path.join(OUT_DIR, "stop_width_001389.json"), "w") as f:
    json.dump(res, f, ensure_ascii=False, indent=2)

L = []
L.append(f"[1] 样本 {dates[0]} ~ {dates[-1]}｜全history {n_raw} 根，过滤零成交 {n_zero_all} 根，有效 {n_valid} 根；取最后 {N_BARS} 根 → {n_win} 个重叠 {H} 日窗口")
L.append(f"[2] A = mean_i |c[i+{H}]/c[i]-1| = {A*100:.4f}%  (median {A_median*100:.4f}%, MAE均值 {mae_mean*100:.4f}%)")
L.append(f"[3] k_cal = quantile(MAE_i/A, {1-BREACH:.2f}) = {k_cal:.4f}; k_used=max(k_cal,{k_floor})={k_used:.4f}")
L.append(f"[4] 触发率校验: (MAE > k_used*A) = {n_hit_cal}/{n_win} = {trig_cal*100:.2f}% (目标 {BREACH*100:.0f}%); k=0.6 时 {trig_06*100:.2f}%")
L.append(f"[5] S = k_used*A = {S*100:.4f}%")
L.append(f"[6] vol20(年化, qdata同式) = {vol20_last*100:.2f}% → 池分档 第{idx+1}档 {b['label']} ({b['vol_range']})")
L.append(f"[7] 池校准参照(sizing_table {reg['generated']}, {reg['n_stocks']}只/{reg['n_points']:,}点): A={A_pool*100:.2f}%, k_cal={k_pool:.3f}, S={S_pool*100:.2f}%")
L.append(f"[8] 2026-11-11: 后复权close {P_hfq:.4f} / factor {factor_last:.6f} → 真实收盘 P = {P:.4f} 元")
L.append(f"[8b] 换算自检: 真实low {real_low:.4f} ≤ 真实VWAP(amount/(volume*factor)) {real_vwap:.4f} ≤ 真实high {real_high:.4f}，且 low ≤ P ≤ high → {px_check}")
L.append(f"[9] 止损参考价 = P*(1-S) = {P:.4f}*(1-{S*100:.4f}%) = {stop_px:.4f} 元；池校准口径 {stop_px_pool:.4f} 元")
L.append(f"[10] 窗口内 factor 变动 {fac_chg} 次；|单日收益|>30% 共 {n_extreme} 根")
L.append(f"[11] SIG-002 stability 锚(只读登记表, 未在本标的重测): grade={grade} scope={scope}, "
         f"sign_agree={stab.get('sign_agree')}, sig_rate={stab.get('sig_rate')}, "
         f"full_t={stab.get('full_t')}, n_stocks={stab.get('n_stocks')}, "
         f"n_boot={stab.get('n_boot')}, checked_at={stab.get('checked_at')}")
L.append(f"[12] S={S*100:.4f}% 与框架 S<=15% 天花板比较: {'超出' if S>0.15 else '未超出'} (差 {(S-0.15)*100:+.4f} pct)")
txt = "\n".join(L) + "\n"
with open(os.path.join(OUT_DIR, "stop_width_001389.txt"), "w") as f:
    f.write(txt)
print(txt)
print("WROTE:", os.path.join(OUT_DIR, "stop_width_001389.json"))
print("WROTE:", os.path.join(OUT_DIR, "stop_width_001389.txt"))
