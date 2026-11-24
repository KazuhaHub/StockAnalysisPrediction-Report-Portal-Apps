# -*- coding: utf-8 -*-
"""量化状态监控（科技主线 + 微盘）：market-monitor 的 quant 作业。

计算部分原样取自同事的面板生成器（quant-dashboard 包的 bin/build_dashboard.py，
第 1–846 行）：篮子、阈值、去重窗口、滞回、NaN 掩码、次日收盘执行与基准率回测
一律不改。改动只在输入输出与内存：
  · 行情库：读本应用的 MarketData（MD_HOME），宽表直接按年度分区读成 float32
    （market_data.panel），不先建全库长表再 pivot——长表在 2 GiB 容器里放不下；
    口径与原来的「volume>0 的长表 → pivot_table → float32」逐值一致（测试核对）。
  · 输出：不生成 HTML，DATA 写成 out/quant.json，由作业入口转成快照。
  · monitor_history.csv / monitor_runs.csv 仍写在 out/ 下（同日重跑覆盖当行）。
"""
import sys, os, json
MD_ROOT = os.environ.get("MD_HOME") or os.path.join(os.path.expanduser("~"), "MarketData")
# market_data.py 在 import 时读 MARKET_DATA_HOME 决定数据根，必须在 import 前设好。
os.environ["MARKET_DATA_HOME"] = MD_ROOT
sys.path.insert(0, MD_ROOT)
import market_data as md
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

OUT_DIR = os.environ.get("QD_OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT_DIR, exist_ok=True)

LEAD = {"300308": "中际旭创", "300502": "新易盛", "300394": "天孚通信", "002281": "光迅科技",
        "300476": "胜宏科技", "002463": "沪电股份", "600183": "生益科技", "002916": "深南电路",
        "002837": "英维克", "601138": "工业富联", "000938": "紫光股份", "000977": "浪潮信息",
        "688256": "寒武纪", "688041": "海光信息", "002049": "紫光国微"}
DEF = {"601398": "工商银行", "601939": "建设银行", "600036": "招商银行", "601288": "农业银行",
       "601318": "中国平安", "600900": "长江电力", "601088": "中国神华", "600941": "中国移动"}



from panels import load_panels  # noqa: E402

close, amount = load_panels()
dates = close.index

ma200 = close.rolling(200).mean()
valid = close.notna() & ma200.notna()
breadth = ((close > ma200) & valid).sum(axis=1) / valid.sum(axis=1) * 100
hi120, lo120 = close.rolling(120).max(), close.rolling(120).min()
nh = ((close >= hi120) & valid).sum(axis=1)
nl = ((close <= lo120) & valid).sum(axis=1)
ndr_pct = (nh - nl) / valid.sum(axis=1) * 100
del hi120, lo120  # 内存：之后不再使用

ret = close.pct_change(fill_method=None)
ew = (1 + ret.mean(axis=1).fillna(0)).cumprod()

# ===== 微盘组：20 日均成交额最低 400 只等权（剔除北交所/退市股），21 交易日调仓 =====
# 口径说明：无市值字段，用成交额横截面分位做代理；已用 2017/2024-01 微盘股灾校验过有效性
_meta = json.load(open(os.path.join(MD_ROOT, "meta.json")))["stocks"]
_DL = {k for k, v in _meta.items() if v.get("status") == "delisted"}
amt20 = amount.rolling(20).mean()
mscore = amt20.rank(axis=1, pct=True).to_numpy()
del amt20  # 内存：之后不再使用
_mcols = list(close.columns)
melig = (amount.to_numpy() > 0) & (close.notna().cumsum().to_numpy() >= 250) & ~np.isnan(mscore)
melig &= ~np.array([c in _DL for c in _mcols])[None, :]
_retv = ret.to_numpy()
_hold = np.zeros_like(_retv, dtype=bool)
for _i in range(20, len(dates), 21):
    _idx = np.where(melig[_i])[0]
    if len(_idx) < 600:
        continue
    _pick = _idx[np.argsort(mscore[_i][_idx])[:400]]
    _hold[_i:min(_i + 21, len(dates)), _pick] = True
_masked = np.where(_hold, _retv, np.nan)
_mcov = (~np.isnan(_masked)).sum(axis=1)
_micr = np.nanmean(_masked, axis=1)
_micr[_mcov < 320] = np.nan
del _masked, _retv, _hold  # 内存：之后不再使用
micro = pd.Series(np.cumprod(1 + np.nan_to_num(_micr)), index=dates) * 100
mpool = pd.DataFrame(melig & (np.nan_to_num(mscore, nan=1.0) < 0.10), index=dates, columns=_mcols)
del mscore, melig  # 内存：之后不再使用
micro_breadth = ((close > ma200) & mpool).sum(axis=1) / (mpool & ma200.notna()).sum(axis=1).replace(0, np.nan) * 100
micro_share = (amount.where(mpool).sum(axis=1) / amount.sum(axis=1) * 100).rolling(20).mean()
micro_rs = micro / ew * 100
micro_rs_ma60 = micro_rs.rolling(60).mean()
micro_dma60 = (micro / micro.rolling(60).mean() - 1) * 100

# ===== 微盘建仓阶梯（反向版）：两档 + 不对称滞回 =====
# 与主线阶梯前提相反：微盘破 MA20/MA60 是买点不是卖点（破MA60清仓年化 7.2% vs 纯持有 17.1%，2015-11 起同一区间）。
# 但「越跌越买」也不成立：−45.3% 的最大回撤来自 2017-18 结构性阴跌，不是过热崩塌 → 结构闸门必须用慢线 MA200。
# 档位只保留两档（25/100）：实测四档（25/50/75/100）更差（Calmar 0.38 vs 0.56）——
#   长期阴跌里给「破线不深」50% 等于半山腰满仓，反而吃满跌幅。抖动不是靠加档位解决，是靠滞回。
# 不对称滞回：下穿 MA200 立即到 25%；站上 MA200+5% 才回 100%；降档后 10 个交易日禁止升档。
#   切换 67→27 次、中位停留 8→62 日、<10日短命段 38→2。
# 回测（analysis/ladder_unify4.py）：年化 12.9%→12.3%、回撤 −23.0%→−20.0%、Calmar 0.56→0.61；
#   样本外（2022 起）Calmar 0.82→0.84、2026 −11.9%→−2.3%。代价：2024 少赚 11.1pp（要站上 MA200+5% 才回满）。
MIC_TC = 0.003
# 微盘指数在池子覆盖不足前是被 nan_to_num 填平的假平台（2014-06~2015-11 恒等于 100），
# 直接喂 MA200 会把均线拉低、让 2016 年的结构闸门误判；先掩回 NaN 再算均线。
_micro_src = micro.copy()
_micro_src[_mcov < 320] = np.nan
MIC_MA200 = _micro_src.rolling(200, min_periods=120).mean()
MIC_UP, MIC_HOLD = 0.05, 10

def _mic_ladder(up_band=MIC_UP, hold=MIC_HOLD):
    idx = micro.index
    dev = (micro / MIC_MA200 - 1)
    over_in = ((micro_breadth > 85) & (micro_dma60 > 10)).fillna(False)
    over_out = ((micro_breadth < 75) | (micro_dma60 < 5)).fillna(False)
    out, p_prev, last_cut, over = [], 0.25, -10 ** 9, False
    for i in range(len(idx)):
        d = dev.iloc[i]
        if over_in.iloc[i]:
            over = True
        elif over_out.iloc[i]:
            over = False
        if pd.isna(d):
            base = 0.25
        elif d < 0:
            base = 0.25
        elif d > up_band:
            base = 1.0
        else:
            base = p_prev
        if over:
            base = min(base, 0.25)
        if base < p_prev - 1e-9:
            last_cut = i
        if base > p_prev + 1e-9 and (i - last_cut) < hold:
            base = p_prev
        out.append(base)
        p_prev = base
    return pd.Series(out, index=idx)

def _segs(pos, start=None):
    """切换次数 / 中位停留天数 / <10 日短命段数——用来量化「仓位是不是在乱跳」"""
    s = pos.dropna()
    if start:
        s = s[s.index >= pd.Timestamp(start)]
    ch = s[s.diff().fillna(0) != 0]
    last, v, lens = s.index[0], s.iloc[0], []
    for d, x in s.items():
        if abs(x - v) > 1e-9:
            lens.append(max((d - last).days, 1)); last, v = d, x
    lens.append(max((s.index[-1] - last).days, 1))
    return {"sw": int(len(ch)), "med": int(np.median(lens)),
            "short": int(sum(1 for x in lens if x < 10)), "n": int(len(lens))}

_mic_pos_raw = _mic_ladder()
mic_pos = _mic_pos_raw.shift(1).fillna(1.0)          # 次日生效
MIC_DIAG = _segs(mic_pos)
_mic_ret = micro.pct_change(fill_method=None).fillna(0)
_mic_turn = mic_pos.diff().abs().fillna(0)
mic_pnl = _mic_ret * mic_pos - _mic_turn * MIC_TC     # 微盘换手 27 次，必须计成本
mic_eq = (1 + mic_pnl).cumprod()
mic_hold = (1 + _mic_ret).cumprod()

def _mstepstat(pnl, pos, a, b):
    idx = pnl.index
    mk = (idx >= pd.Timestamp(a)) & (idx <= pd.Timestamp(b))
    eq = (1 + pnl[mk]).cumprod()
    cagr = eq.iloc[-1] ** (245.0 / max(len(eq), 1)) - 1
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": round(float(cagr) * 100, 1), "dd": round(float(dd) * 100, 1),
            "calmar": round(float(cagr / abs(dd)), 2) if dd else 0,
            "pos": round(float(pos[mk].mean() * 100)), "ret": round((float(eq.iloc[-1]) - 1) * 100, 1)}

_mall, _mhold = _mstepstat(mic_pnl, mic_pos, "2016-01-01", str(dates[-1].date())), \
                _mstepstat(_mic_ret, pd.Series(1.0, index=dates), "2016-01-01", str(dates[-1].date()))
MICSTEP = {"all": _mall, "hold": _mhold,
           "out": _mstepstat(mic_pnl, mic_pos, "2022-01-01", str(dates[-1].date())),
           "outH": _mstepstat(_mic_ret, pd.Series(1.0, index=dates), "2022-01-01", str(dates[-1].date())),
           "y24": _mstepstat(mic_pnl, mic_pos, "2024-01-01", "2024-12-31"),
           "y24H": _mstepstat(_mic_ret, pd.Series(1.0, index=dates), "2024-01-01", "2024-12-31"),
           "y26": _mstepstat(mic_pnl, mic_pos, "2026-01-01", str(dates[-1].date())),
           "y26H": _mstepstat(_mic_ret, pd.Series(1.0, index=dates), "2026-01-01", str(dates[-1].date()))}

def ew_idx(codes, start="2026-01-05"):
    codes = [x for x in codes if x in close.columns]
    r = ret[codes].mean(axis=1)
    s = r[r.index >= start].dropna()
    return (1 + s).cumprod() * 100

leadA, defB = ew_idx(list(LEAD)), ew_idx(list(DEF))

# 阶梯回测需要长历史（主图只画 2026，故 leadA 只有 213 点）
ret_c = ret.where(ret > -0.25)          # 剔除复权断点造成的 -50% 级假跌幅
def ew_idx_full(codes, start="2014-06-01"):
    codes = [x for x in codes if x in close.columns]
    r = ret_c[codes].mean(axis=1)
    s = r[r.index >= start].fillna(0)
    return (1 + s).cumprod() * 100
leadF = ew_idx_full(list(LEAD))
del ret_c  # 内存：之后不再使用
lead_ma60 = leadA.rolling(60).mean()
lb = pd.DataFrame({f"b{n}": (close[[x for x in LEAD if x in close.columns]] >
                             close[[x for x in LEAD if x in close.columns]].rolling(n).mean()).mean(axis=1) * 100
                   for n in (20, 60, 200)})

mom = close / close.shift(60) - 1
month_ends = pd.Series(dates, index=dates).groupby([dates.year, dates.month]).last().values
lead_ret = pd.Series(0.0, index=dates)
for i in range(len(month_ends) - 1):
    d0, d1 = pd.Timestamp(month_ends[i]), pd.Timestamp(month_ends[i + 1])
    sc = mom.loc[d0].dropna()
    if len(sc) < 200:
        continue
    top = sc.nlargest(50).index
    seg = ret.loc[(dates > d0) & (dates <= d1), top]
    lead_ret.loc[seg.index] = seg.mean(axis=1).values
del mom  # 内存：之后不再使用（不改变任何数值）
leadm = (1 + lead_ret.fillna(0)).cumprod()

def dedupe(mask, gap=20):
    idx = np.where(mask.values)[0]
    out, last = [], -10**9
    for i in idx:
        if i - last >= gap:
            out.append(dates[i]); last = i
    return out

br_hi120 = breadth.rolling(120).max()
# 宽度自身 250 日分位：绝对阈值会随宽度中枢漂移，分位版本跨期可比
bq = breadth.rolling(250, min_periods=120).rank(pct=True) * 100
# M1 过热：必须覆盖两种形态，否则对结构化行情永久失效
#   形态A「全面普涨」：全市场宽度 >80（2015 式，宽度 99.8% 但篮内 MA200 仅 13.3%）
#   形态B「极致窄牛」：全市场宽度极低但主线自身过热（2026 式，宽度 32.6%，篮内 MA200 80%）
# 旧版只判形态A，导致 2026-06-22 主线 60 日涨 70.7% 却不报警。
m1 = (leadm / leadm.shift(60) - 1 > 0.60) & ((breadth > 80) | (lb["b200"] > 85))
m2 = (leadm >= leadm.rolling(120).max() * 0.995) & (breadth < br_hi120 - 5)
m3 = (leadm < leadm.rolling(20).mean()) & (leadm.shift(1) >= leadm.rolling(20).mean().shift(1)) & (bq < 30)
# M3/M4 原用绝对宽度（<55 / <45），但宽度中枢从 2015 的 74.9% 降到 2026 的 32.2%，
# 「宽<55」在 2026 年 77% 的交易日都成立，条件退化为恒真。改用自身 250 日分位：
# M4 在分位<20~<40 区间是稳定平台（样本内 -16.0% / 样本外 -16.2%），取平台中心 35。
m4 = (leadm < leadm.rolling(60).mean()) & (leadm.shift(1) >= leadm.rolling(60).mean().shift(1)) & (bq < 35)
cross = (ndr_pct > 0) & (ndr_pct.shift(1) <= 0)
v3 = cross & (breadth < 20) & (breadth.diff(20) >= 5)

SIG = {"M1 过热": dedupe(m1, 30), "M2 背离": dedupe(m2, 20), "M3 破位": dedupe(m3, 15),
       "M4 二波失败": dedupe(m4, 20), "V 底部确认": dedupe(v3, 10)}

# 微盘信号：只保留「事件型」（过热顶、资金退潮）；「深跌」是持续状态，由状态卡表达，
# 否则会被误读成一串独立买点（2026-05 以来微盘宽度长期 <10%）
MSIG = {
    "微盘过热": dedupe((micro_breadth > 85) & (micro_dma60 > 10), 30),
    "资金退潮": dedupe(micro_share < micro_share.rolling(120).max() * 0.7, 60),
}

# 关键：基准率的标的必须与信号定义同源。
# M1-M4 定义在「领涨组合」上（近 60 日涨幅前 50），收益也必须用领涨组合算；
# 用全市场等权会把信号稀释成噪音（M2 从 -15.6%/胜率0% 变成 +0.2%/胜率67%）。
# V 定义在全市场宽度上，故用全市场等权。
ULEAD = {"M1 过热", "M2 背离", "M3 破位", "M4 二波失败"}
def base_stats(sig_dates, series):
    # 无条件 60 日收益中位 = 标的自身漂移。必须减掉它再谈信号好坏：
    # 「60 日动量前 50」这个标的本身长期是亏的（2015 至今 -97%），
    # 不减漂移会把「标的在跌」全部算成「信号很准」。
    allr = [(series.iloc[i + 61] / series.iloc[i + 1] - 1) * 100
            for i in range(0, len(series) - 122, 20)]
    base60 = float(np.median(allr)) if allr else 0.0
    rows = []
    for d in sig_dates:
        i = series.index.get_loc(d)
        if i + 121 >= len(series):
            continue
        e = series.iloc[i + 1]
        r60 = (series.iloc[i + 61] / e - 1) * 100
        dd = (series.iloc[i + 1:i + 61].min() / e - 1) * 100
        rows.append((r60, dd))
    if not rows:
        return {"n": 0, "base60": round(base60, 1), "exc": None}
    a = np.array(rows)
    med = float(np.median(a[:, 0]))
    return {"n": len(a), "win": round(float((a[:, 0] > 0).mean() * 100)),
            "med": round(med, 1), "exc": round(med - base60, 1),
            "base60": round(base60, 1),
            "dd10": round(float((a[:, 1] < -10).mean() * 100)),
            "meddd": round(float(np.median(a[:, 1])), 1)}

BASE = {k: base_stats(v, leadm if k in ULEAD else ew) for k, v in SIG.items()}

# ===== 建仓阶梯 v4：信号表驱动 + 四档 + 滞回 =====
# v3 的口径问题（本轮修）：规则里只接了 M2，M1/M3/M4 只画在图上、不进仓位计算。
#   实测 v3 在 M1 信号后 20 日仓位一次都没降（3/3 仍是 83%），M4 后 75% 的样本仓位没降——
#   「图上写着清主线、仓位纹丝不动」，这就是口径不一致。
# v4 把四个信号全部写成显式动作，且都「只压不抬」（防抖 + 防止用信号加仓）：
#   M1 过热 → 封顶 50%（需篮子 60 日涨幅 >25%，否则窄牛里长期误伤）
#   M2 背离 → 封顶 50%      M3 破位 → 封顶 50%      M4 二波失败 → 封顶 25%
# 档位从 5 档减到 4 档（0/25/50/100）：75% 与 50% 实盘无差别，且 50↔75 是抖动主要来源。
# 滞回：MA60 ±2% 缓冲带、连 3 日确认、降档后 10 个交易日禁止升档。
# 回测（analysis/ladder_unify4.py）：年化 22.5%→24.4%、回撤 −35.3%→−28.0%、Calmar 0.64→0.87；
#   2026 −3.1%→+15.5%；切换 141→89 次、中位停留 19→33 日、<10 日短命段 50→14。
#   唯一变差的是 2015H2（+27.6%→−1.4%）：M4 封 25% 卡住了股灾后的救市反弹，样本 1 次，接受。
STEP_CONF, STEP_M2TH = 3, 0.25
STEP_BAND, STEP_HOLD = 0.02, 10
STEP_NAME = {0: "P0 空仓", 1: "P1 出清 25%", 2: "P2 试探 50%", 3: "P3 趋势 100%"}
STEP_POS = [0.0, 0.25, 0.5, 1.0]
STEP_IDX = {0.0: 0, 0.25: 1, 0.5: 2, 1.0: 3}

ew_ret_pct = ret.mean(axis=1) * 100
vday = ((ew_ret_pct > 2.0) & (breadth.diff() > 6)).fillna(False)

def _ladder(px, band=STEP_BAND, hold=STEP_HOLD, m4cap=0.25, m3cap=0.5):
    idx = px.index
    ma20 = px.rolling(20).mean(); ma60 = px.rolling(60).mean()
    mom60 = px / px.shift(60) - 1
    br_i = breadth.reindex(idx); rep_i = br_i.diff(20); vd_i = vday.reindex(idx).fillna(False)
    W = lambda s, n: s.fillna(False).rolling(n, min_periods=1).max().astype(bool).reindex(idx).fillna(False)
    sM1 = W(m1, 20) & (mom60 > STEP_M2TH)      # M1 过热
    sM2 = W(m2, 20) & (mom60 > STEP_M2TH)      # M2 背离
    sM3 = W(m3, 15)                            # M3 破位
    sM4 = W(m4, 20)                            # M4 二波失败
    a60 = ((px > ma60 * (1 + band)).rolling(STEP_CONF).sum() == STEP_CONF).fillna(False)
    b60 = ((px < ma60 * (1 - band)).rolling(STEP_CONF).sum() == STEP_CONF).fillna(False)
    a20 = ((px > ma20).rolling(STEP_CONF).sum() == STEP_CONF).fillna(False)
    lowb = (br_i < 5).fillna(False)
    fix = ((rep_i >= 5).fillna(False) | vd_i)
    p_prev, last_cut, pos, tags = 0.0, -10 ** 9, [], []
    for i in range(len(idx)):
        # 1) 趋势给基础档；缓冲带内维持上一档（滞回，避免 MA60 附近来回打脸）
        if a60.iloc[i]:
            base = 1.0
        elif b60.iloc[i]:
            base = 0.25 if (not pd.isna(ma60.iloc[i]) and px.iloc[i] < ma60.iloc[i] * 0.85) else 0.5
        else:
            base = p_prev
        # 2) 三条右侧通道，只抬不压
        if lowb.iloc[i]: base = max(base, 0.25)
        if fix.iloc[i]: base = max(base, 0.5)
        # 3) 信号否决，只压不抬
        cap, why = 1.0, None
        for nm, cond, c in (("M4", sM4, m4cap), ("M3", sM3, m3cap), ("M2", sM2, 0.5), ("M1", sM1, 0.5)):
            if cond.iloc[i] and c < cap:
                cap, why = c, nm
        t = min(base, cap)
        # 4) 降档即刻，升档要等 hold 日（不对称滞回）
        if t < p_prev - 1e-9: last_cut = i
        if t > p_prev + 1e-9 and (i - last_cut) < hold: t = p_prev
        t = round(t, 2)
        pos.append(t); tags.append((t, why if cap < base - 1e-9 else None)); p_prev = t
    return pd.Series(pos, index=idx), tags

_step_raw, _step_tags = _ladder(leadF)
_step_st = STEP_IDX[round(float(_step_raw.iloc[-1]), 2)]
_step_cap = _step_tags[-1][1]
STEP_DIAG = _segs(_step_raw.shift(1).fillna(0.0), "2016-01-01")
step_pos = _step_raw.shift(1).fillna(0.0)
lead_ret_s = leadF.pct_change(fill_method=None).fillna(0)
hold_pos = pd.Series(1.0, index=leadF.index)

STEP_TC = 0.003

def _pstat(pos, a, b, cost=STEP_TC):
    idx = pos.index
    mk = (idx >= pd.Timestamp(a)) & (idx <= pd.Timestamp(b))
    p = (pos * lead_ret_s - pos.diff().abs().fillna(0) * cost)[mk]
    eq = (1 + p).cumprod()
    cagr = eq.iloc[-1] ** (245.0 / max(len(p), 1)) - 1
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": round(cagr * 100, 1), "dd": round(dd * 100, 1),
            "calmar": round(cagr / abs(dd), 2) if dd else 0,
            "pos": round(pos[mk].mean() * 100), "ret": round((eq.iloc[-1] - 1) * 100, 1)}

STEPST = {"all": _pstat(step_pos, "2016-01-01", str(dates[-1].date())),
          "hold": _pstat(hold_pos, "2016-01-01", str(dates[-1].date()), cost=0.0),
          "out": _pstat(step_pos, "2022-01-01", str(dates[-1].date())),
          "y26": _pstat(step_pos, "2026-01-01", str(dates[-1].date())),
          "y26h": _pstat(hold_pos, "2026-01-01", str(dates[-1].date()), cost=0.0)}

asof = dates[-1]
b_now, n_now = float(breadth.iloc[-1]), float(ndr_pct.iloc[-1])
rep20 = float(breadth.diff(20).iloc[-1])
lead_dd250 = (float(leadA.iloc[-1]) / float(leadA.rolling(250, min_periods=60).max().iloc[-1]) - 1) * 100
lead_dd60 = (float(leadA.iloc[-1]) / float(leadA.rolling(60, min_periods=20).max().iloc[-1]) - 1) * 100
r60_lead = (float(leadA.iloc[-1]) / float(leadA.shift(60).iloc[-1]) - 1) * 100
r60_def = (float(defB.iloc[-1]) / float(defB.shift(60).iloc[-1]) - 1) * 100
pct_b = float((breadth < b_now).mean() * 100)
pct_n = float((ndr_pct < n_now).mean() * 100)
amtA = float(amount[[x for x in LEAD if x in amount.columns]].iloc[-5:].sum().sum() / 5 / 1e8)

def days_since(ds):
    if not ds: return 10**9
    return (asof - max(ds)).days

last = {k: (max(v) if v else None) for k, v in SIG.items()}
since = {k: days_since(v) for k, v in SIG.items()}
basket_above_ma60 = float(leadA.iloc[-1]) > float(lead_ma60.iloc[-1])

if since["V 底部确认"] <= 5:
    state, code = "确认区（右侧信号已出现）", "ok"
elif since["M2 背离"] <= 20:
    state, code = "顶部警戒（宽度背离）", "warn"
elif b_now < 15 and n_now < -40:
    state, code = "出清区（极端超卖，未确认）", "cold"
elif since["M4 二波失败"] <= 20 or (not basket_above_ma60 and b_now < 45):
    state, code = "熊市确认（主跌延续）", "bad"
elif since["M3 破位"] <= 15:
    state, code = "下跌中（主线破位）", "bad"
elif basket_above_ma60 and b_now > 40 and rep20 > 0:
    state, code = "修复中（右侧初期）", "ok"
elif b_now > 80 and r60_lead > 40:
    state, code = "过热（停止加仓）", "warn"
else:
    state, code = "常规运行", "neutral"

# ===== 微盘状态（判据与科技主线完全不同：无叙事锚，破位是买点，风险来自流动性退潮）=====
mb_now = float(micro_breadth.iloc[-1])
ms_now = float(micro_share.iloc[-1])
ms_hi120 = float(micro_share.rolling(120, min_periods=60).max().iloc[-1])
md60_now = float(micro_dma60.iloc[-1])
# 相对强弱两个口径都要给，不能只给一个：
#   ① 60 日收益差（微盘 − 全市场等权，pp）——直白，符号就是「跑赢/跑输」
#   ② 比值相对其自身 60 日均线的偏离——二阶动量，衡量相对强弱在改善还是恶化
# 旧版只给 ② 却标成「vs 全市场 MA60」，容易被读成「vs 全市场均线」；而且 micro/ew 的
# 比值水平受两序列起点影响（micro 在 2015-11 前是填平的假平台），水平值不可跨期比较。
mrs_60d = (float(micro.iloc[-1] / micro.iloc[-61] - 1) - float(ew.iloc[-1] / ew.iloc[-61] - 1)) * 100
mrs_now = float(micro_rs.iloc[-1] / micro_rs_ma60.iloc[-1] - 1) * 100
m_dd250 = (float(micro.iloc[-1]) / float(micro.rolling(250, min_periods=60).max().iloc[-1]) - 1) * 100
m_pct = float((micro_breadth < mb_now).mean() * 100)
ms_drop = (ms_now / ms_hi120 - 1) * 100
msince = {k: days_since(v) for k, v in MSIG.items()}

# 微盘阶梯当前状态
m_bear_now = bool(micro.iloc[-1] < MIC_MA200.iloc[-1])
m_over_now = bool((micro_breadth.iloc[-1] > 85) and (micro_dma60.iloc[-1] > 10))
m_pos_now = float(_mic_pos_raw.iloc[-1]) * 100
m_dma200 = (float(micro.iloc[-1]) / float(MIC_MA200.iloc[-1]) - 1) * 100
m_below_days = int((micro < MIC_MA200).fillna(False).iloc[::-1].cumprod().sum()) if m_bear_now else 0

# 状态判定不含「资金退潮」：该信号 21 次、+120d 中位 +4.1%、胜率 65%，
# 方向未通过检验（见 signal_challenge_audit.py），只作关注度展示，不产生仓位动作。
if mb_now > 85 and md60_now > 10:
    mstate, mcode = "过热（停加仓）", "warn"
elif mb_now < 10:
    mstate, mcode = "深跌区（偏买）", "ok"
elif md60_now < -10:
    mstate, mcode = "回撤中（不追杀）", "cold"
else:
    mstate, mcode = "常规运行", "neutral"

# 深跌段的完整历史统计（全样本，不只当前窗口）：回答「偏买信号到底赚不赚」
def _fwd(series, d, n):
    i = series.index.get_loc(d)
    if i + 1 + n >= len(series):
        return None
    return (series.iloc[i + 1 + n] / series.iloc[i + 1] - 1) * 100

_dm = (micro_breadth < 10).fillna(False)
_dsegs, _s = [], None
for _d, _f in _dm.items():
    if _f and _s is None:
        _s = _d
    elif not _f and _s is not None:
        if dates.get_loc(_d) - dates.get_loc(_s) >= 5:
            _dsegs.append((_s, _d))
        _s = None
if _s is not None:
    _dsegs.append((_s, dates[-1]))
_r60 = [x for x in (_fwd(micro, a, 60) for a, b in _dsegs) if x is not None]
_r120 = [x for x in (_fwd(micro, a, 120) for a, b in _dsegs) if x is not None]
DEEPST = {
    "n": len(_dsegs), "n60": len(_r60),
    "med60": round(float(np.median(_r60)), 1), "win60": round(float((np.array(_r60) > 0).mean() * 100)),
    "med120": round(float(np.median(_r120)), 1), "win120": round(float((np.array(_r120) > 0).mean() * 100)),
    "lastStart": str(_dsegs[-1][0].date()), "lastLen": dates.get_loc(_dsegs[-1][1]) - dates.get_loc(_dsegs[-1][0]) + 1,
}

# 口径说明用的活数据：V 与「资金退潮」的样本内外表现
# 这两条是被质疑过的信号，数字必须跟脚本同步，不能写死在静态 HTML 里
def _fwdstat(ds, series, n=120):
    rows, tags = [], []
    for d in ds:
        i = series.index.get_loc(d)
        if i + 1 + n >= len(series):
            continue
        rows.append((series.iloc[i + 1 + n] / series.iloc[i + 1] - 1) * 100)
        tags.append(d)
    if not rows:
        return {"n": 0}
    a = np.array(rows)
    return {"n": len(a), "med": round(float(np.median(a)), 1),
            "win": round(float((a > 0).mean() * 100)),
            "worst": round(float(a.min()), 1), "tags": tags}


_v_all = _fwdstat(SIG["V 底部确认"], ew)
_v_out = _fwdstat([d for d in SIG["V 底部确认"] if d > pd.Timestamp("2022-12-31")], ew)
_f_all = _fwdstat(MSIG["资金退潮"], micro)
VSTAT = {"all": {k: v for k, v in _v_all.items() if k != "tags"},
         "out": {k: v for k, v in _v_out.items() if k != "tags"}}
FLOWSTAT = {k: v for k, v in _f_all.items() if k != "tags"}

# 主图 x 轴必须与所有序列共用同一索引：篮子净值从 2026-01-05 起算（215 点），
# 若 x 轴取 250 个交易日，ECharts 会把 215 点对齐到前 215 个标签，末端数据被错置到 9 月下旬。
dw = leadA.index
d_main = [str(x.date()) for x in dw]
def ser(s):
    v = s.reindex(dw)
    return [None if pd.isna(x) else round(float(x), 2) for x in v]
dbw = dates[-500:]
d_br = [str(x.date()) for x in dbw]
def ser2(s):
    v = s.reindex(dbw)
    return [None if pd.isna(x) else round(float(x), 2) for x in v]

# 信号点：投影到主图（仅保留落在篮子净值区间内的）
# 配色刻意避开主线红/防守绿/宽度蓝，保证在红线上可辨
SIGSTYLE = [("M1 过热", "#993C1D", "rect", 0, 12), ("M2 背离", "#534AB7", "triangle", 180, 16),
            ("M3 破位", "#BA7517", "circle", 0, 11),
            ("M4 二波失败", "#2C2C2A", "diamond", 0, 13), ("V 底部确认", "#3B6D11", "triangle", 0, 14)]
sigs = []
for k, col, sym, rot, size in SIGSTYLE:
    pts = [[str(d.date()), round(float(leadA.loc[d]), 2)] for d in SIG[k] if d in leadA.index]
    if pts:
        sigs.append({"name": k, "color": col, "sym": sym, "rot": rot, "size": size, "pts": pts})

# 建仓阶梯曲线（与主图共用 dw 时间轴；归一化到窗口起点=1，在 JS 里做）
step_eq = (1 + step_pos * lead_ret_s).cumprod()
hold_eq = (1 + lead_ret_s).cumprod()
_step20 = leadF.rolling(20).mean()
_step60 = leadF.rolling(60).mean()

# 近18个月信号
cutoff = asof - pd.Timedelta(days=540)
NAME = {"M1 过热": "过热（封顶 50%）", "M2 背离": "宽度背离（封顶 50%）", "M3 破位": "主线破位（封顶 50%）",
        "M4 二波失败": "二波失败（封顶 25%）", "V 底部确认": "底部确认（可提到 50%）"}
srows = []
for k, v in SIG.items():
    for d in v:
        if d >= cutoff:
            srows.append((str(d.date()), k, NAME[k]))
srows.sort(reverse=True)

# ===== 微盘序列（500 日窗口）=====
dmw = dates[-500:]
dmicro = [str(x.date()) for x in dmw]
def ser3(s, nd=1):
    v = s.reindex(dmw)
    return [None if pd.isna(x) else round(float(x), nd) for x in v]
rs_base = float(micro_rs.reindex(dmw).dropna().iloc[0])
rs_norm = micro_rs / rs_base * 100
# 两条指数都归一化到窗口起点=100，否则累积起点不同、量级不可比
mic_n = micro / float(micro.reindex(dmw).dropna().iloc[0]) * 100
mew_n = ew / float(ew.reindex(dmw).dropna().iloc[0]) * 100
# 微盘阶梯净值同样归一化到窗口起点（否则与指数不同量级）
_meq0 = float(mic_eq.reindex(dmw).dropna().iloc[0])
_mhd0 = float(mic_hold.reindex(dmw).dropna().iloc[0])
mic_eq_n = mic_eq / _meq0 * 100
mic_hold_n = mic_hold / _mhd0 * 100
MNAME = {"微盘过热": "过热（停加仓）", "资金退潮": "关注度回落（仅观察，不产生动作）"}
m_r60 = (float(micro.iloc[-1]) / float(micro.shift(60).iloc[-1]) - 1) * 100
msrows = []
for k, v in MSIG.items():
    for d in v:
        if d >= cutoff:
            msrows.append((str(d.date()), k, MNAME[k]))
msrows.sort(reverse=True)

# 微盘信号投影到图，且标在「它自己的指标」上：
# 过热 → 微盘指数曲线；资金退潮 → 成交额占比柱（两者都在自己的基准上才有意义）。
# 深跌是持续状态不是事件，用 markArea 阴影区间表达；混进散点会被误读成 N 个独立买点。
def _mpts(k, series, nd=2):
    return [[str(d.date()), round(float(series.loc[d]), nd)] for d in MSIG[k]
            if d in series.index and d >= dmw[0]]
msigs = []
if _mpts("微盘过热", mic_n):
    msigs.append({"name": "微盘过热", "color": "#993C1D", "sym": "rect", "rot": 0, "size": 12,
                  "pts": _mpts("微盘过热", mic_n)})
mfsigs = []
if _mpts("资金退潮", micro_share):
    mfsigs.append({"name": "资金退潮", "color": "#A32D2D", "sym": "triangle", "rot": 180, "size": 14,
                   "pts": _mpts("资金退潮", micro_share)})

# 深跌状态区间（微盘宽度 <10%），合并连续段；最后一段延伸到 asof
# 过滤 <5 个交易日的毛刺段：500 日窗口里 2-3 天只有几像素宽，看起来像污点而非区间
deep = (micro_breadth < 10).reindex(dmw).fillna(False).astype(bool)
idx = {d: i for i, d in enumerate(dmw)}
seg, areas = None, []
for d, flag in deep.items():
    if flag and seg is None:
        seg = d
    elif not flag and seg is not None:
        if idx[d] - idx[seg] >= 5:
            areas.append((str(seg.date()), str(d.date())))
        seg = None
if seg is not None:
    areas.append((str(seg.date()), str(dmw[-1].date())))
mareas = [[{"xAxis": a}, {"xAxis": b}] for a, b in areas]
deep_now = bool(deep.iloc[-1])
deep_days = int(deep.iloc[::-1].cumprod().sum()) if deep_now else 0
deep_seg = areas[-1] if (areas and deep_now) else None

# ===== 日更监测：新鲜度 / 入库覆盖 / 状态历史 =====
# 为什么放这里而不是另写一个脚本：这些判据全部依赖本脚本已经算好的横截面
# （有成交票数、宽度分位、阶梯档位）。另起一份就会得到「面板说 A、监测说 B」的两套口径。
MON_HIST = os.path.join(OUT_DIR, "monitor_history.csv")
MON_RUNS = os.path.join(OUT_DIR, "monitor_runs.csv")
MON_COLS = ["date", "state", "breadth", "bq", "ndr", "step", "stage", "mic", "mb", "md60",
            "sigs", "days", "leadpx", "micpx"]
MDROOT = MD_ROOT

# 期望交易日：优先用 daily_update.sh 传来的 QD_EXPECT（它已经查过日历，且能容忍网络失败）；
# 手跑本脚本时自己查一次，取不到就置空——宁可在面板上写「日历不可用」，也不猜。
expect = (os.environ.get("QD_EXPECT") or "").strip() or None
# 来源也要传进来：脚本侧同样有「日历不可达 → 按工作日推算」的兜底，
# 若只传日期不传来源，面板会把推算值当成交易所日历，节假日就会误标红。
expect_src = (os.environ.get("QD_EXPECT_SRC") or "").strip() or ("calendar" if expect else None)
if not expect:
    try:
        sys.path.insert(0, MDROOT)
        import trading_day as _tdmod
        expect = _tdmod.last_trading_day(str(datetime.now().date() - pd.Timedelta(days=1)))
        if expect:
            expect_src = "calendar"
    except Exception:
        expect = None
if not expect:
    # 退化口径：按工作日推算（不含法定节假日）。
    # 为什么还要留这一层：面板常常在沙箱里被自动化任务重建，那里访问不到交易日历服务，
    # 若直接留空，新鲜度闸门就永远显示「日历不可用」，等于没有监测。
    # 代价是节假日会误报「落后 1 日」——所以标记 expectSrc=weekday，界面上写清是推算值。
    _d = datetime.now().date() - timedelta(days=1)
    while _d.weekday() >= 5:
        _d -= timedelta(days=1)
    expect, expect_src = str(_d), "weekday"


def _lag_td(a, b):
    """库内交易日历上，a 之后到 b 之间还有几个交易日（0 = 已是最新）"""
    if not a or not b:
        return None
    A, B = pd.Timestamp(a), pd.Timestamp(b)
    if B <= A:
        return 0
    return int(((dates > A) & (dates <= B)).sum())


lag_td = _lag_td(str(asof.date()), expect)
# 覆盖口径：当日有成交（volume>0）的票数。停牌日 volume=0，不参与横截面，
# 所以这个数字直接反映「源端今天给了多少只」——2026-11-16 缺 429 只就是这里掉下去的。
days_now = int(close.iloc[-1].notna().sum())
days_prev = int(close.iloc[-2].notna().sum())
cover = (days_now / days_prev - 1) * 100 if days_prev else 0.0


def _lockstate(fn):
    p = os.path.join(MDROOT, fn)
    if not os.path.isdir(p):
        return None
    who = ""
    for f in ("who", "pid"):
        try:
            who = open(os.path.join(p, f)).read().strip()
            if who:
                break
        except Exception:
            pass
    return who or "?"


locked = {"update": _lockstate(".update.lock"), "write": _lockstate(".mdwrite.lock")}

_sig_today = [k for k, v in SIG.items() if v and pd.Timestamp(v[-1]) == asof]
_msig_today = [k for k, v in MSIG.items() if v and pd.Timestamp(v[-1]) == asof]
_hrow = {"date": str(asof.date()), "state": state,
         "breadth": round(b_now, 1), "bq": round(float(bq.iloc[-1]), 1), "ndr": round(n_now, 1),
         "step": round(float(_step_raw.iloc[-1]) * 100), "stage": int(_step_st),
         "mic": round(float(_mic_pos_raw.iloc[-1]) * 100),
         "mb": round(mb_now, 1), "md60": round(md60_now, 1),
         "sigs": "|".join([k.replace(" ", "") for k in _sig_today + _msig_today]),
         "days": days_now, "leadpx": round(float(leadA.iloc[-1]), 2),
         "micpx": round(float(micro.iloc[-1]), 1)}

# 幂等写入：同一交易日重跑覆盖当行，不追加。手跑、定时跑、调试跑都不会把历史写乱。
if os.path.exists(MON_HIST):
    try:
        _h = pd.read_csv(MON_HIST, dtype={"sigs": str})
    except Exception:
        _h = pd.DataFrame(columns=MON_COLS)
else:
    _h = pd.DataFrame(columns=MON_COLS)
if len(_h):
    _h = _h[_h["date"].astype(str) != _hrow["date"]]
    _h = pd.concat([_h, pd.DataFrame([_hrow])], ignore_index=True)
else:
    _h = pd.DataFrame([_hrow], columns=MON_COLS)
_h = _h[MON_COLS].sort_values("date").reset_index(drop=True)
_h.to_csv(MON_HIST, index=False)


def _fnum(x, nd=1):
    try:
        v = float(x)
        return None if pd.isna(v) else round(v, nd)
    except Exception:
        return None


# 状态历史：直接从序列回算，不读 CSV。
# 理由：CSV 是「哪天跑过、结果如何」的审计记录，今天是第一次跑它只有一行；
# 而历史表要能立刻给出上下文（这个状态维持了几天、仓位什么时候换的档）。
# 回算用与今日判定完全相同的规则与输入，所以最后一行必然等于今天那一行——verify 会核对。
# 2026-11-24 从 20 日扩到 500 日：原先只能看到两周，回看「上次出清是什么时候、持续几天」全靠猜；
# 500 日覆盖主线图窗口（2026 起约 215 点）并往前多一年，且不会把 3000 日全样本塞进页面。
_HN = 500
_hdates = dates[-_HN:]
# leadA 是篮子窗口序列（起点晚于 dates），必须先 reindex 到 dates 再用位置索引，
# 否则这两天会索引越界——2026-11-22 踩到。
_basket_above_s = (leadA > lead_ma60).reindex(dates).ffill().fillna(False)
_r60lead_s = ((leadA / leadA.shift(60) - 1) * 100).reindex(dates)


def _since_series(lst):
    s = pd.Series(pd.NaT, index=dates, dtype="datetime64[ns]")
    for d in lst:
        s.loc[dates >= d] = d
    return ((dates - s) / pd.Timedelta(days=1))


_dV, _d2, _d3, _d4 = (_since_series(SIG["V 底部确认"]), _since_series(SIG["M2 背离"]),
                      _since_series(SIG["M3 破位"]), _since_series(SIG["M4 二波失败"]))


def _state_short(j):
    b = float(breadth.iloc[j]); n = float(ndr_pct.iloc[j])
    rp = float(breadth.diff(20).iloc[j]) if j - 20 >= -len(breadth) else 0.0
    ba = bool(_basket_above_s.iloc[j]); rl = float(_r60lead_s.iloc[j] or 0)
    dv, d2, d3, d4 = (float(_dV.iloc[j]), float(_d2.iloc[j]), float(_d3.iloc[j]), float(_d4.iloc[j]))
    if dv <= 5: return "确认区"
    if d2 <= 20: return "顶部警戒"
    if b < 15 and n < -40: return "出清区"
    if d4 <= 20 or (not ba and b < 45): return "熊市确认"
    if d3 <= 15: return "下跌中"
    if ba and b > 40 and rp > 0: return "修复中"
    if b > 80 and rl > 40: return "过热"
    return "常规"


_hist = []
for _i in range(len(_hdates)):
    _j = len(dates) - len(_hdates) + _i
    _d = _hdates[_i]
    _st = _state_short(_j)
    _sg = [k.replace(" ", "") for k, v in SIG.items() if v and pd.Timestamp(v[-1]) == _d]
    _sg += [k.replace(" ", "") for k, v in MSIG.items() if v and pd.Timestamp(v[-1]) == _d]
    _hist.append([str(_d.date()), _st, _fnum(breadth.iloc[_j], 1), _fnum(bq.iloc[_j], 1),
                  _fnum(ndr_pct.iloc[_j], 1),
                  _fnum(float(_step_raw.asof(_d)) * 100, 0),
                  _fnum(float(_mic_pos_raw.asof(_d)) * 100, 0), "|".join(_sg)])

# ===== 状态带 / 切换点 / 逐日读数：让主线图上任何一天都能回溯当日状态 =====
# 与历史表共用 _state_short，避免「图上和表上两套判定」——这是之前踩过的口径断层。
_state_all = pd.Series([_state_short(j) for j in range(len(dates))], index=dates)
ST_COLOR = {"出清区": "#185FA5", "确认区": "#185FA5", "熊市确认": "#A32D2D",
            "下跌中": "#A32D2D", "顶部警戒": "#854F0B", "过热": "#854F0B",
            "修复中": "#0F6E56", "常规": "#b8b5ac"}
_stband, _stmark = [], []
_cur, _s0 = None, None
for _i, _ds in enumerate(d_main):
    _sv = str(_state_all.asof(pd.Timestamp(_ds)))
    if _sv != _cur:
        if _cur is not None:
            _stband.append({"x0": d_main[_s0], "x1": d_main[_i - 1], "st": _cur,
                            "color": ST_COLOR.get(_cur, "#b8b5ac")})
        _stmark.append({"d": _ds, "st": _sv, "color": ST_COLOR.get(_sv, "#b8b5ac")})
        _cur, _s0 = _sv, _i
if _cur is not None:
    _stband.append({"x0": d_main[_s0], "x1": d_main[-1], "st": _cur,
                    "color": ST_COLOR.get(_cur, "#b8b5ac")})

# 逐日读数：tooltip 用它回答「这根 K 线那天，状态和仓位是什么」
_dayinfo = []
for _ds in d_main:
    _t = pd.Timestamp(_ds)
    _sp, _mp = _step_raw.asof(_t), _mic_pos_raw.asof(_t)
    _bq = bq.asof(_t)
    _dayinfo.append([
        str(_state_all.asof(_t)),
        None if pd.isna(_sp) else round(float(_sp) * 100),
        None if pd.isna(_mp) else round(float(_mp) * 100),
        round(float(breadth.asof(_t)), 1),
        round(float(ndr_pct.asof(_t)), 1),
        None if pd.isna(_bq) else round(float(_bq)),
    ])

_prev = _hist[-2] if len(_hist) >= 2 else None
_chg = {"step": None, "mic": None, "state": None}
if _prev is not None:
    _chg = {"step": [_prev[5], _hist[-1][5]], "mic": [_prev[6], _hist[-1][6]],
            "state": [_prev[1], _hist[-1][1]]}


_runs = []
if os.path.exists(MON_RUNS):
    try:
        _rr = pd.read_csv(MON_RUNS, dtype=str).fillna("")
        _runs = _rr.tail(8).iloc[::-1].to_dict("records")
    except Exception:
        _runs = []

MON = {
    "expect": expect, "expectSrc": expect_src or "none", "lag": lag_td, "days": days_now, "prevDays": days_prev,
    "cover": round(cover, 1), "locked": locked,
    "hist": _hist, "chg": _chg, "runs": _runs,
    "today": {"sigs": _sig_today + _msig_today, "step": _hrow["step"], "mic": _hrow["mic"]},
    "tdN": int(len(dates)), "histN": int(len(_h)),
}

DATA = {
    "asof": str(asof.date()), "gen": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "mon": MON,
    "state": state, "stateCode": code,
    "b": round(b_now, 1), "bpct": round(pct_b, 1), "ndr": round(n_now, 1), "npct": round(pct_n, 1),
    "rep20": round(rep20, 1), "dd250": round(lead_dd250, 1), "dd60": round(lead_dd60, 1),
    "r60lead": round(r60_lead, 1), "r60def": round(r60_def, 1), "amt5": round(amtA),
    "since": {k: (int(v) if v < 10**6 else None) for k, v in since.items()},
    "dmain": d_main, "lead": ser(leadA), "def": ser(defB), "breadth": ser(breadth),
    "stband": _stband, "stmark": _stmark, "dayinfo": _dayinfo,
    "dbr": d_br, "breadth2": ser2(breadth), "ndr2": ser2(ndr_pct),
    "dmeta": d_main[-1],
    "bA20": ser(lb["b20"]), "bA60": ser(lb["b60"]), "bA200": ser(lb["b200"]),
    "leadX": ser(leadA),
    "sigs": sigs, "sig": srows, "base": BASE,
    "mstate": mstate, "mcode": mcode, "mb": round(mb_now, 1), "mbpct": round(m_pct, 1),
    "mshare": round(ms_now, 2), "msdrop": round(ms_drop, 1), "md60": round(md60_now, 1),
    "mrs": round(mrs_60d, 1), "mrsm": round(mrs_now, 1), "mdd250": round(m_dd250, 1), "mr60": round(m_r60, 1),
    "dmw": dmicro, "mic": ser3(mic_n), "mew": ser3(mew_n), "mbw": ser3(micro_breadth),
    "msh": ser3(micro_share, 2), "mrsn": ser3(rs_norm),
    "msig": msrows, "msigs": msigs, "mfsigs": mfsigs, "mareas": mareas,
    "deepNow": deep_now, "deepDays": deep_days, "deepSeg": deep_seg, "deepst": DEEPST,
    "mstep": {
        "stage": 1 if (m_bear_now or m_over_now) else 3,
        "pos": round(m_pos_now), "bear": m_bear_now, "over": m_over_now,
        "dma200": round(m_dma200, 1), "belowDays": m_below_days,
        "up": round(MIC_UP * 100, 1), "holdN": MIC_HOLD, "diag": MIC_DIAG,
        "px": round(float(micro.iloc[-1]), 1), "ma200": round(float(MIC_MA200.iloc[-1]), 1),
        "eq": ser3(mic_eq_n), "hold": ser3(mic_hold_n), "posa": ser3(mic_pos * 100),
        "stat": MICSTEP,
    },
    "vstat": VSTAT, "flowstat": FLOWSTAT,
    "msince": {k: (int(v) if v < 10**6 else None) for k, v in msince.items()},
    "step": {
        "stage": int(_step_st), "pos": round(float(_step_raw.iloc[-1]) * 100),
        "cap": bool(_step_cap), "capr": _step_cap or "",
        "band": round(STEP_BAND * 100, 1), "holdN": STEP_HOLD, "diag": STEP_DIAG,
        "px20": round(float(leadF.iloc[-1] / _step20.iloc[-1] - 1) * 100, 1),
        "px60": round(float(leadF.iloc[-1] / _step60.iloc[-1] - 1) * 100, 1),
        "bq": round(float(bq.iloc[-1]), 1), "rep": round(float(breadth.diff(20).iloc[-1]), 1),
        "eq": ser(step_eq), "hold": ser(hold_eq), "posa": ser(step_pos * 100),
        "stat": STEPST,
    },
}

# 退市股计数（口径说明用，原包是写死的文字）：meta 标记退市的只数，与其中
# 进入了本次宽表（有成交、非北交所）的只数。只是附加读数，不参与任何计算。
DATA["delisted"] = {"meta": len(_DL), "used": int(sum(1 for c in _mcols if c in _DL))}

# 作业入口（mm_job.py）读这份，转成 quant 快照；原包的 HTML 模板不再生成。
_tmp = os.path.join(OUT_DIR, "quant.json.tmp")
with open(_tmp, "w", encoding="utf-8") as _fh:
    json.dump(DATA, _fh, ensure_ascii=False)
os.replace(_tmp, os.path.join(OUT_DIR, "quant.json"))
print("[quant] asof=%s state=%s step=%s mic=%s" % (DATA["asof"], DATA["state"], DATA["step"]["pos"], DATA["mstep"]["pos"]))
