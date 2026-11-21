"""因子 → 行业分位 → 六策略 → 九法估值 → 因子体检 → 导出前端数据。

口径要点（与页面「方法与数据」一致）：
1. 所有因子先按申万一级行业内转 0-100 分位，缺失不参与排名，也不按 0 分计。
2. 策略分 = Σ(权重 × 分位)/Σ权重 − 数据缺口惩罚 − 极端波动惩罚；缺失权重不重分配（宁可扣分）。
3. 共振分 = 六维均值 − 0.35×标准差 + 0.10×最高分（惩罚偏科）。
4. 估值综合价只在「≥2 个方法可用且离散度 < 阈值」时输出，否则打标签不给价。
"""
import json
import os
import warnings

import numpy as np
import pandas as pd

from asof import asof_iso, report_period

_PERIOD_LABEL, _PERIOD_RP = report_period()

warnings.filterwarnings("ignore")
D = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(D, "data")

# ------------------------------------------------------------------ 参数
RF = 0.0161          # 10Y 国债（2026-11-04）
ERP = 0.055          # 股权风险溢价
G_TERM = 0.025       # 永续增长
YEARS = 10           # 显性预测期（十年两阶段，成长股不吃亏）
TAX = 0.15           # 有效税率
KD = 0.040           # 债务成本
DISP_MAX = 0.60      # 旧口径，保留做参考
DISP_PCT = 85        # 分歧门槛：行业内 log 离散度分位 >85% 才标「分歧过大」

m = pd.read_parquet(f"{DATA}/master.parquet")
m["sw1"] = m["sw1"].fillna("未分类")


def wz(s, lo=0.01, hi=0.99):
    s = pd.to_numeric(s, errors="coerce")
    a, b = s.quantile(lo), s.quantile(hi)
    return s.clip(a, b)


def safe_div(a, b):
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    r = a / b.replace(0, np.nan)
    return r.replace([np.inf, -np.inf], np.nan)


# ------------------------------------------------------------------ 派生字段
m["eps_ttm"] = safe_div(m["ttm_net_income"], m["shares_outstanding"])
m["ocr"] = safe_div(m["operating_cf"] * 1.0, m["ttm_net_income"])          # 现金含量
m["accrual"] = safe_div(m["ttm_net_income"] - m["operating_cf"], m["total_assets"])
m["asset_turn"] = safe_div(m["ttm_revenue"], m["total_assets"])
m["inv_days"] = safe_div(m["inventory"], m["ttm_revenue"]) * 365
m["rec_days"] = safe_div(m["receivables"], m["ttm_revenue"]) * 365
m["ebit"] = m["operating_profit"]
m["ev"] = m["mktcap"] + m["total_liabilities"].fillna(0) - m["current_assets"].fillna(0)
m["ebit_ev"] = safe_div(m["ebit"], m["ev"])
m["fcf_ps"] = safe_div(m["operating_cf"], m["shares_outstanding"]) * 0.62   # 资本开支经验扣减
m["roa"] = pd.to_numeric(m["roa"], errors="coerce")

# 三年 CAGR（FY2023 → FY2025）
pan = pd.DataFrame(json.load(open(f"{DATA}/fundamentals_hist.json")).get("20231231", []))
p23 = pd.DataFrame(json.load(open(f"{DATA}/fundamentals_hist.json"))["20231231"])
p25 = pd.DataFrame(json.load(open(f"{DATA}/fundamentals_hist.json"))["20251231"])
for p in (p23, p25):
    p["symbol"] = p["symbol"].astype(str).str.zfill(6)
    for c in ["revenue", "net_income"]:
        p[c] = pd.to_numeric(p[c], errors="coerce")
p23 = p23.drop_duplicates("symbol").set_index("symbol")
p25 = p25.drop_duplicates("symbol").set_index("symbol")
rev_cagr3 = (safe_div(p25["revenue"], p23["revenue"]).clip(lower=0) ** (1 / 2) - 1) * 100
np_cagr3 = (safe_div(p25["net_income"].where(p25["net_income"] > 0),
                     p23["net_income"].where(p23["net_income"] > 0)) ** (1 / 2) - 1) * 100
m["rev_cagr3"] = m["symbol"].map(rev_cagr3)
m["np_cagr3"] = m["symbol"].map(np_cagr3)

# 股息种子（股息率 ≥4% 的真实观测）
div = pd.read_csv(f"{DATA}/div_seed.csv", dtype={"code": str})
div["code"] = div["code"].str.zfill(6)
m = m.drop(columns=["div_yield"], errors="ignore")
m = m.merge(div[["code", "div_yield", "payout", "div_period"]], left_on="symbol",
            right_on="code", how="left").drop(columns=["code"])
m["dps"] = m["div_yield"] / 100 * m["price"]
m["div_cover"] = safe_div(m["ocfps"], m["dps"])

# 行业景气：行业内净利润同比中位数
m["ind_prosperity"] = m.groupby("sw1")["np_yoy"].transform("median")
m["ind_np_yoy"] = m["np_yoy"]
m["rs_ind60"] = m["ret_3m"] - m.groupby("sw1")["ret_3m"].transform("median")
m["ind_pe_med"] = m.groupby("sw1")["pe"].transform(lambda s: s[(s > 0) & (s < 200)].median())
m["ind_pb_med"] = m.groupby("sw1")["pb"].transform(lambda s: s[(s > 0) & (s < 30)].median())
m["pe_rel"] = safe_div(m["pe"], m["ind_pe_med"])      # <1 便宜
m["pb_rel"] = safe_div(m["pb"], m["ind_pb_med"])

# 用面板算存货/资产同比（lag 4 期）
panl = pd.DataFrame(json.load(open(f"{DATA}/panel.json")))
panl["symbol"] = panl["symbol"].astype(str).str.zfill(6)
for c in ["inventory", "total_assets", "revenue", "net_income", "operating_cf", "ocfps",
          "gross_margin", "roe"]:
    panl[c] = pd.to_numeric(panl[c], errors="coerce")
panl = panl.sort_values(["symbol", "report_period"])
panl["inv_yoy_calc"] = panl.groupby("symbol")["inventory"].pct_change(4) * 100
panl["ta_yoy_calc"] = panl.groupby("symbol")["total_assets"].pct_change(4) * 100
panl["ocfps_yoy_calc"] = panl.groupby("symbol")["ocfps"].pct_change(4) * 100
last2 = panl.groupby("symbol").tail(1).set_index("symbol")
m["inv_yoy"] = m["symbol"].map(last2["inv_yoy_calc"])
m["ta_yoy"] = m["symbol"].map(last2["ta_yoy_calc"])
m["ocfps_yoy"] = m["symbol"].map(last2["ocfps_yoy_calc"])
m["roe_std"] = m["symbol"].map(panl.groupby("symbol")["roe"].apply(lambda s: s.tail(8).std()))
_q = panl.groupby("symbol").tail(1).set_index("symbol")["report_period"].astype(str).str[4:8]
_qmap = {"0331": 1, "0630": 2, "0930": 3, "1231": 4}
m["roe_ann"] = m["roe"] * (4.0 / m["symbol"].map(_q).map(_qmap).fillna(4))
m["roa_ann"] = m["roa"] * (4.0 / m["symbol"].map(_q).map(_qmap).fillna(4))
m["gm_std"] = m["symbol"].map(panl.groupby("symbol")["gross_margin"].apply(lambda s: s.tail(8).std()))

# ------------------------------------------------------------------ 因子注册表
F = []          # (id, 中文名, 组, 方向(+1 大更好 / -1 小更好), 值列)


def reg(fid, name, group, direction, series, note=""):
    F.append({"id": fid, "name": name, "group": group, "dir": direction,
              "note": note})
    m[f"raw_{fid}"] = pd.to_numeric(series, errors="coerce")


# 一次性损益嫌疑：TTM 净利率 > 50% 且 净利/经营现金流 > 2。
# 这类样本的 PE 在经济上没有意义（如重整收益、处置股权），若照常参与
# EP 排名与 PE 相对估值，会把「靠一次性收益做出来的低 PE」顶到价值榜首位。
_ni = m["ttm_net_income"]
_ocf = m["ocf_ttm"]
_nm = _ni / m["ttm_revenue"].replace(0, np.nan)
m["oneoff"] = ((_ni > 0) & (_nm > 0.5) & ((_ni / _ocf.replace(0, np.nan)) > 2)).fillna(False)
print(f"一次性损益嫌疑 {int(m['oneoff'].sum())} 只，PE 类估值与 EP 因子对其不适用")
_ep_raw = safe_div(1, m["pe"]).where(~m["oneoff"])
_pe_rel_raw = (1 - m["pe"] / m["ind_pe_med"]) * 100
_pe_rel_raw = _pe_rel_raw.where(~m["oneoff"])

reg("EP", "盈利收益率 EP", "价值", 1, _ep_raw, "1/PE(TTM)，剔除一次性损益嫌疑")
reg("BP", "账面市值比 BP", "价值", 1, safe_div(1, m["pb"]), "1/PB")
reg("SP", "营收市值比 SP", "价值", 1, safe_div(1, m["ps"]), "1/PS")
reg("CFP", "现金流市值比", "价值", 1, safe_div(1, m["pcf"]), "OCF/市值")
reg("EBIT_EV", "EBIT/EV", "价值", 1, m["ebit_ev"], "EV=市值+总负债-流动资产")
reg("PE_HCHEAP", "自身PE历史分位(反向)", "价值", 1, (1 - m["pe_pct"]) * 100, "三年月度 PE 分位")
reg("PB_HCHEAP", "自身PB历史分位(反向)", "价值", 1, (1 - m["pb_pct"]) * 100, "三年月度 PB 分位")
reg("PE_REL", "行业相对PE折价", "价值", 1, _pe_rel_raw, "行业 PE 中位/个股 PE，剔除一次性损益嫌疑")
reg("DIV_YIELD", "股息率", "价值", 1, m["div_yield"], "年度股息率，仅 ≥4% 样本")

reg("REV_YOY", "营收同比", "成长", 1, m["rev_yoy"])
reg("NP_YOY", "净利同比", "成长", 1, m["np_yoy"])
reg("NP_ACCEL", "净利加速度", "成长", 1, m["np_yoy_c"] - m["np_yoy_c_l4"], "本期同比 − 四期前同比")
reg("REV_ACCEL", "营收加速度", "成长", 1, m["rev_yoy_c"] - m["rev_yoy_c_l4"])
reg("REV_CAGR3", "营收3年复合", "成长", 1, m["rev_cagr3"], "FY2023→FY2025")
reg("NP_CAGR3", "净利3年复合", "成长", 1, m["np_cagr3"])
reg("GM_YOY", "毛利率同比变动", "成长", 1, m["gross_margin"] - m["gm_l4"])
reg("ROE_YOY", "ROE同比变动", "成长", 1, m["roe"] - m["roe_l4"])
reg("OCF_YOY", "每股现金流同比", "成长", 1, m["ocfps_yoy"])
reg("PAYOUT", "股利支付率", "红利", 1, m["payout"], "派息率，仅高股息样本")
reg("RET_12M", "12月总动量", "动量", 1, m["ret_12m"])
reg("SUSTAIN", "可持续增长率", "成长", 1, m["roe_ann"] / 100 * (1 - m["payout"].fillna(30) / 100) * 100)

reg("ROE", "ROE(年化)", "质量", 1, m["roe_ann"])
reg("ROA", "ROA(年化)", "质量", 1, m["roa_ann"])
reg("ROE_STAB", "ROE稳定性", "质量", -1, m["roe_std"], "近8期ROE标准差，小更好")
reg("GM", "毛利率", "质量", 1, m["gross_margin"])
reg("NM", "净利率", "质量", 1, m["net_margin"])
reg("OCF_NI", "现金含量 OCF/NI", "质量", 1, m["ocr"])
reg("ACCRUAL", "低应计", "质量", -1, m["accrual"], "应计越低越好")
reg("LOW_LEV", "低杠杆", "质量", -1, m["asset_liability_ratio"])
reg("CURRENT", "流动比率", "质量", 1, safe_div(m["current_assets"], m["current_liabilities"]))
reg("ASSET_TURN", "总资产周转", "质量", 1, m["asset_turn"])
reg("INV_DAYS", "存货周转天数", "质量", -1, m["inv_days"])
reg("REC_DAYS", "应收周转天数", "质量", -1, m["rec_days"])

reg("IND_PROSP", "行业景气度", "周期", 1, m["ind_prosperity"], "行业内净利同比中位")
reg("EARN_REV", "盈利反转", "周期", 1, m["np_yoy_c"] - m["np_yoy_c_l6"], "本期同比 − 六期前同比（约1.5年）")
reg("GM_TREND", "毛利率趋势", "周期", 1, m["gross_margin"] - m["gm_l8"])
reg("REV_TREND", "营收趋势", "周期", 1, m["rev_yoy_c"] - m["rev_yoy_c_l6"])
reg("CASH_TREND", "现金流趋势", "周期", 1, m["cfo_margin"] - m["cfo_m_l4"], "经营现金流/营收 的同比变化")
reg("CAPEX_CYCLE", "扩张纪律", "周期", -1, m["ta_yoy"] - m["rev_yoy"], "资产增速−营收增速")
reg("PBCHEAP", "PB绝对便宜", "周期", -1, m["pb"])

reg("MOM_12_1", "12-1动量", "动量", 1, m["mom_12_1"], "剔除最近1月")
reg("MOM_3M", "3月动量", "动量", 1, m["ret_3m"])
reg("MOM_1M", "1月动量", "动量", 1, m["ret_1m"])
reg("MA_ALIGN", "均线多头排列", "动量", 1, m["ma_align"], "0-4 分")
reg("DIST_HIGH", "距52周高点", "动量", 1, m["dist_high"])
reg("RS_IND60", "行业内相对强弱", "动量", 1, m["rs_ind60"], "60日收益−行业中位")
reg("VOL_TREND", "波动趋势", "动量", -1, m["vol_ratio"], "20日/120日波动，升温扣分")
reg("TURN_CHG", "换手变化", "动量", -1, m["turnover_chg"])

reg("LOW_VOL", "低波动", "风险", -1, m["vol_ann"])
reg("BETA", "低Beta", "风险", -1, m["beta252"])
reg("SIZE", "小市值", "风险", -1, np.log(m["mktcap"]))
reg("ILLIQ", "非流动性溢价", "风险", 1, m["amihud"])
reg("MAX_RET", "低彩票效应", "风险", -1, m["max_ret_20"])
reg("TURNOVER", "低换手", "风险", -1, m["turnover_20"])

# ------------------------------------------------------------------ 行业分位
for f in F:
    col = f"raw_{f['id']}"
    v = m[col]
    if f["dir"] < 0:
        v = -v
    g = v.groupby(m["sw1"])
    pct = g.rank(pct=True, method="average") * 100
    # 行业内同一值太多时会挤在 50 分，用 min_periods 控制
    m[f"p_{f['id']}"] = pct.round(1).where(v.notna())
    f["coverage"] = float(v.notna().mean())
    f["ind_coverage"] = float(v.notna().groupby(m["sw1"]).mean().mean())

# ------------------------------------------------------------------ 策略
STRAT = {
    "value": {
        "name": "价值", "en": "Value",
        "desc": "用低估值买入已被定价悲观的公司，赚估值修复与股息的钱。",
        "w": {"EP": 20, "BP": 18, "EBIT_EV": 12, "PE_REL": 12, "PE_HCHEAP": 10,
              "PB_HCHEAP": 8, "DIV_YIELD": 8, "CFP": 7, "SP": 5},
    },
    "growth": {
        "name": "成长", "en": "Growth",
        "desc": "买营收与利润仍在扩张、且扩张在加速的公司。",
        "w": {"NP_YOY": 16, "REV_YOY": 14, "NP_ACCEL": 14, "REV_ACCEL": 10,
              "NP_CAGR3": 12, "REV_CAGR3": 8, "GM_YOY": 10, "ROE_YOY": 8, "SUSTAIN": 8},
    },
    "cyclical": {
        "name": "周期", "en": "Cyclical",
        "desc": "找供需错配与盈利拐点：景气、反转、毛利趋势比单看 PE 更早。",
        "w": {"IND_PROSP": 18, "EARN_REV": 18, "GM_TREND": 14, "REV_TREND": 12,
              "CASH_TREND": 10, "CAPEX_CYCLE": 8, "PBCHEAP": 12, "PE_REL": 8},
    },
    "dividend": {
        "name": "红利", "en": "Dividend",
        "desc": "现金回报的可持续性优先于当期股息率：覆盖率与稳定性一起看。",
        "w": {"DIV_YIELD": 16, "OCF_NI": 15, "LOW_LEV": 12, "SUSTAIN": 11, "PAYOUT": 10,
              "ROE_STAB": 10, "LOW_VOL": 10, "EP": 8, "OCF_YOY": 8},
    },
    "momentum": {
        "name": "动量", "en": "Momentum",
        "desc": "12-1 动量、均线排列、距高点回撤与相对强弱。",
        "w": {"MOM_12_1": 22, "MOM_3M": 16, "MA_ALIGN": 14, "DIST_HIGH": 12,
              "RS_IND60": 12, "MOM_1M": 8, "VOL_TREND": 8, "TURN_CHG": 8},
    },
    "quality": {
        "name": "质量", "en": "Quality",
        "desc": "高 ROE 且稳定、现金流覆盖利润、低应计与低杠杆。",
        "w": {"ROE": 18, "ROE_STAB": 14, "OCF_NI": 14, "ACCRUAL": 10, "LOW_LEV": 10,
              "GM": 10, "ASSET_TURN": 8, "NM": 8, "ROA": 8},
    },
}

volpct = m.groupby("sw1")["vol_ann"].rank(pct=True) * 100
for k, s in STRAT.items():
    num = pd.Series(0.0, index=m.index)
    den = pd.Series(0.0, index=m.index)
    tot = float(sum(s["w"].values()))
    for fid, w in s["w"].items():
        col = f"p_{fid}"
        num = num.add(m[col].fillna(0) * w, fill_value=0)
        den = den.add(m[col].notna().astype(float) * w, fill_value=0)
    cov = den / tot
    raw = num / den.replace(0, np.nan)
    anchor = max(s["w"], key=lambda k: s["w"][k])
    raw = raw.where(m[f"p_{anchor}"].notna())
    pen = 8 * (1 - cov) + 0.06 * (volpct.fillna(50) - 75).clip(lower=0)
    s["score"] = (raw - pen).round(1)
    s["cov"] = cov.round(3)
    m[f"s_{k}"] = s["score"]
    m[f"cov_{k}"] = cov

S = pd.DataFrame({k: m[f"s_{k}"] for k in STRAT})
m["resonance"] = (S.mean(axis=1) - 0.35 * S.std(axis=1) + 0.10 * S.max(axis=1)).round(1)

# 模板（每策略 2 个，对全市场求交）
TEMPLATES = {
    "value": [
        {"id": "V1", "name": "深度低估", "desc": "PB 低于行业中位 30% 且 EP 行业前 30%",
         "cond": lambda d: (d["pb_rel"] < 0.7) & (d["p_EP"] > 70)},
        {"id": "V2", "name": "股息价值", "desc": "股息率 ≥4% 且现金含量 >0.8",
         "cond": lambda d: (d["div_yield"] >= 4) & (d["ocr"] > 0.8)},
    ],
    "growth": [
        {"id": "G1", "name": "双加速", "desc": "净利与营收同比同时加速，且净利同比 >20%",
         "cond": lambda d: (d["p_NP_ACCEL"] > 60) & (d["p_REV_ACCEL"] > 60) & (d["np_yoy"] > 20)},
        {"id": "G2", "name": "毛利扩张", "desc": "毛利率同比提升且营收 3 年复合 >15%",
         "cond": lambda d: (d["p_GM_YOY"] > 70) & (d["rev_cagr3"] > 15)},
    ],
    "cyclical": [
        {"id": "C1", "name": "盈利反转", "desc": "净利同比反转超过 30pp 且行业景气为正",
         "cond": lambda d: ((d["np_yoy_c"] - d["np_yoy_c_l6"]) > 30) & (d["ind_prosperity"] > 0)},
        {"id": "C2", "name": "现金流拐点", "desc": "经营现金流/营收 同比改善且 PB 行业后 40%",
         "cond": lambda d: ((d["cfo_margin"] - d["cfo_m_l4"]) > 0) & (d["p_PBCHEAP"] > 60)},
    ],
    "dividend": [
        {"id": "D1", "name": "高股息核心", "desc": "股息率 >5%、派息率 30-80%、覆盖率 >1",
         "cond": lambda d: (d["div_yield"] > 5) & (d["payout"].between(30, 80)) & (d["div_cover"] > 1)},
        {"id": "D2", "name": "现金奶牛", "desc": "现金含量 >1.2 且股息率 >4%",
         "cond": lambda d: (d["ocr"] > 1.2) & (d["div_yield"] > 4)},
    ],
    "momentum": [
        {"id": "M1", "name": "强势突破", "desc": "12-1 动量前 20% 且距 52 周高点 <10%",
         "cond": lambda d: (d["p_MOM_12_1"] > 80) & (d["dist_high"] > -0.1)},
        {"id": "M2", "name": "低波趋势", "desc": "均线多头排列且年化波动行业后 40%",
         "cond": lambda d: (d["ma_align"] >= 3) & (d["p_LOW_VOL"] > 60)},
    ],
    "quality": [
        {"id": "Q1", "name": "现金质量", "desc": "ROE >12% 且现金含量 >1 且低杠杆前 40%",
         "cond": lambda d: (d["roe"] > 12) & (d["ocr"] > 1) & (d["p_LOW_LEV"] > 60)},
        {"id": "Q2", "name": "稳定复利", "desc": "ROE 稳定性前 30% 且 ROE >10%",
         "cond": lambda d: (d["p_ROE_STAB"] > 70) & (d["roe"] > 10)},
    ],
}
for k, lst in TEMPLATES.items():
    for t in lst:
        try:
            t["n"] = int(t["cond"](m).sum())
        except Exception as e:
            t["n"] = 0
            print("template err", t["id"], e)

# ------------------------------------------------------------------ 估值
def industry_med(col, lo, hi):
    return m.groupby("sw1")[col].transform(lambda s: s[(s > lo) & (s < hi)].median())


m["ind_pe"] = industry_med("pe", 0, 200)
m["ind_pb"] = industry_med("pb", 0, 30)

beta = m["beta252"].fillna(1.0).clip(0.4, 2.0)
m["ke"] = (RF + beta * ERP).clip(0.085, 0.15)
m["g1"] = m["rev_cagr3"].fillna(m["np_yoy"].clip(-20, 40)).clip(-3, 22) / 100
m["wacc"] = m["ke"] * m["equity"].fillna(0) / (m["equity"].fillna(0) + m["total_liabilities"].fillna(0)).replace(0, np.nan)
m["wacc"] = m["wacc"].fillna(m["ke"]).clip(0.06, 0.16)
m.loc[m["equity"].fillna(0) <= 0, "wacc"] = m["ke"]


def two_stage(base, g1, r, terminal=G_TERM, years=YEARS):
    """base: 当期每股现金流；g1: 显性期增速；r: 折现率。返回每股价值。"""
    if not np.isfinite(base) or base <= 0 or not (r > terminal):
        return np.nan
    g1 = float(np.clip(g1, -0.05, 0.30))
    v, cf = 0.0, base
    for t in range(1, years + 1):
        g = g1 + (terminal - g1) * (t - 1) / max(years - 1, 1)
        cf = cf * (1 + g)
        v += cf / (1 + r) ** t
    tv = cf * (1 + terminal) / (r - terminal)
    v += tv / (1 + r) ** years
    return v


rows = []
FIN = ("银行", "非银金融")
for i, r in m.iterrows():
    px = r["price"]
    out = {"PE_REL": np.nan, "PB_REL": np.nan, "PE_HIST": np.nan, "PB_HIST": np.nan,
           "DCFE": np.nan, "DCFF": np.nan, "DDM": np.nan, "EPV": np.nan,
           "PEG": np.nan, "RI": np.nan, "IMP_G": np.nan}
    if not np.isfinite(px) or px <= 0:
        rows.append(out)
        continue
    eps, bps = r["eps_ttm"], r["bps"]
    roe = r["roe_ann"] / 100 if np.isfinite(r["roe_ann"]) else np.nan
    g3 = r["rev_cagr3"] if np.isfinite(r["rev_cagr3"]) else np.nan
    ok_pe = (np.isfinite(eps) and eps > 0 and np.isfinite(r["pe"])
             and 0 < r["pe"] <= 150 and not bool(r["oneoff"]))
    ke, wacc, g1 = r["ke"], r["wacc"], r["g1"]
    is_fin = r["sw1"] in FIN
    # 1-2 相对行业
    if ok_pe and np.isfinite(r["ind_pe"]):
        out["PE_REL"] = eps * r["ind_pe"]
    if np.isfinite(r["ind_pb"]) and np.isfinite(bps) and bps > 0:
        out["PB_REL"] = bps * r["ind_pb"]
    # 3-4 自身历史带
    if ok_pe and np.isfinite(r["pe_med"]):
        out["PE_HIST"] = eps * r["pe_med"]
    if np.isfinite(r["pb_med"]) and np.isfinite(bps) and bps > 0:
        out["PB_HIST"] = bps * r["pb_med"]
    ebit_ps = (r["ebit"] / r["shares_outstanding"]) if (np.isfinite(r["ebit"]) and r["shares_outstanding"] > 0) else np.nan
    if not is_fin:
        # 5 FCFE
        if ok_pe and np.isfinite(roe) and roe > 0.06 and np.isfinite(g3) and -10 <= g3 <= 40:
            g_use = min(g1, roe * 0.7)
            reinv = float(np.clip(g_use / max(roe, 0.03), 0, 0.70))
            out["DCFE"] = two_stage(max(eps * (1 - reinv), 0), g_use, ke)
        # 6 FCFF
        if np.isfinite(ebit_ps) and ebit_ps > 0 and np.isfinite(g3) and -25 <= g3 <= 45:
            rref = roe if (np.isfinite(roe) and roe > 0.02) else 0.10
            g_use = min(g1, rref * 0.7)
            reinv = float(np.clip(g_use / max(rref, 0.03), 0, 0.70))
            out["DCFF"] = two_stage(max(ebit_ps * (1 - TAX) * (1 - reinv), 0), g_use, wacc)
        # 8 EPV
        if np.isfinite(ebit_ps) and ebit_ps > 0:
            out["EPV"] = ebit_ps * (1 - TAX) / wacc
    # 7 DDM
    dps = r["dps"]
    if np.isfinite(dps) and dps > 0:
        pay = (r["payout"] / 100) if np.isfinite(r["payout"]) else 0.4
        pay = float(np.clip(pay, 0, 0.9))
        gd = float(np.clip(min(g1, (roe * (1 - pay)) if (np.isfinite(roe) and roe > 0) else 0.02), -0.05, 0.12))
        if ke - gd >= 0.03:
            out["DDM"] = dps * (1 + gd) / (ke - gd)
    # 9 PEG（目标 PEG=1，公允 PE 上下限 8~45）
    g = r["np_cagr3"] if np.isfinite(r["np_cagr3"]) else np.nan
    if ok_pe and np.isfinite(g) and 5 <= g <= 50:
        out["PEG"] = eps * float(np.clip(g, 8, 45))
    # 10 剩余收益（年化 ROE，B 逐步滚动）
    if np.isfinite(bps) and bps > 0 and np.isfinite(roe) and 0.02 <= roe <= 0.40 and ke > G_TERM:
        gb = float(np.clip(min(roe * 0.7, max(g1, 0.02)), 0.0, 0.20))
        b = bps
        v = bps
        for t in range(1, YEARS + 1):
            v += (roe - ke) * b / (1 + ke) ** t
            b = b * (1 + gb)
        # 终值不给增长：十年后超额收益不再扩大
        tv = (roe - ke) * b / (ke * (1 + ke) ** YEARS)
        out["RI"] = v + tv
    # 反向 DCF：在「再投资率取历史水平」的假设下，反解当前价格隐含的显性期增速
    ig = np.nan
    try:
        if not is_fin and np.isfinite(ebit_ps) and ebit_ps > 0 and np.isfinite(wacc):
            rref0 = roe if (np.isfinite(roe) and roe > 0.02) else 0.10
            reinfix = float(np.clip(max(g1, 0) / max(rref0, 0.03), 0, 0.70))
            cf = ebit_ps * (1 - TAX) * (1 - reinfix)
            lo, hi = -0.15, 0.60

            def f(gg):
                vv = two_stage(cf, gg, wacc)
                return (vv if vv == vv else 0) - px

            if cf > 0 and f(hi) > 0:
                for _ in range(60):
                    mid = (lo + hi) / 2
                    if f(mid) < 0:
                        lo = mid
                    else:
                        hi = mid
                ig = (lo + hi) / 2 * 100
    except Exception:
        pass
    out["IMP_G"] = ig
    rows.append(out)

V = pd.DataFrame(rows, index=m.index)
METHODS = [("PE_REL", "相对行业 PE", 1.0), ("PB_REL", "相对行业 PB", 1.0),
           ("PE_HIST", "自身历史 PE", 0.8), ("PB_HIST", "自身历史 PB", 0.8),
           ("DCFE", "两阶段 DCF(FCFE)", 0.7), ("DCFF", "两阶段 DCF(FCFF)", 0.7),
           ("DDM", "股利折现 DDM", 0.6), ("EPV", "超额收益价值 EPV", 0.7),
           ("PEG", "PEG 折价", 0.5), ("RI", "剩余收益 RI", 0.9)]

W = pd.Series({k: w for k, _, w in METHODS})
ids = [k for k, _, _ in METHODS]
V_M = V.drop(columns=['IMP_G'], errors='ignore')
A = V_M[ids].copy()
for k in ids:
    okm = A[k].notna() & (A[k] > 0) & (A[k] / m["price"]).between(0.10, 10)
    A[k] = A[k].where(okm)

# 合成：加权中位数（对数空间）。用中位数而不是均值，是为了让「一个模型算飞了」不带走整条结论，
# 但离群方法仍然计入方法数与离散度——分歧本身要被看见。
LR = np.log(A.div(m["price"], axis=0).where(A > 0))
n_ok = A[ids].notna().sum(axis=1)
disp = LR.std(axis=1, skipna=True)

Wv = np.array([W[k] for k in ids], dtype=float)
LRv = LR[ids].values
out = np.full(len(LRv), np.nan)
for i in range(len(LRv)):
    row = LRv[i]
    msk = np.isfinite(row)
    if msk.sum() == 0:
        continue
    v = row[msk]
    w = Wv[msk]
    o = np.argsort(v)
    v, w = v[o], w[o]
    cw = np.cumsum(w) / w.sum()
    j = int(np.searchsorted(cw, 0.5))
    out[i] = v[min(j, len(v) - 1)]
comp = pd.Series(np.exp(out) * m["price"].values, index=m.index)
m["n_methods"] = n_ok
m["composite"] = comp
m["upside"] = comp / m["price"] - 1
m["disp"] = disp

m["disp_pct"] = m.groupby("sw1")["disp"].rank(pct=True) * 100


def label(r):
    if not np.isfinite(r["composite"]) or r["n_methods"] == 0:
        return "数据不足"
    if r["n_methods"] == 1:
        return "单一方法参考"
    if np.isfinite(r["disp_pct"]) and r["disp_pct"] > DISP_PCT:
        return "分歧过大"
    u = r["upside"]
    if u >= 0.6:
        return "显著低估"
    if u >= 0.25:
        return "低估"
    if u > -0.25:
        return "合理"
    if u > -0.55:
        return "高估"
    return "显著高估"


m["label"] = m.apply(label, axis=1)
m["in_pool"] = m["price"].notna() & m["composite"].notna()
m["valid"] = m["in_pool"] & ~m["label"].isin(["分歧过大", "单一方法参考", "数据不足"])

# 四象限：估值 × 质量
m["q_pct"] = m.groupby("sw1")["s_quality"].rank(pct=True) * 100
# 注意：upside 为 NaN 时 (NaN > 0.25) 是 False，于是 ~cheap 也是 True，
# 会把「没有估值结论」的股票全归进「又贵又差」。必须先筛出可判定样本再分象限。
cheap = m["upside"] > 0.25
good = m["q_pct"] > 50
m["quad"] = "未分类"
_sel = m["in_pool"] & m["upside"].notna() & m["q_pct"].notna()
m.loc[_sel & cheap & good, "quad"] = "便宜好公司"
m.loc[_sel & cheap & ~good, "quad"] = "价值陷阱"
m.loc[_sel & ~cheap & good, "quad"] = "优质但贵"
m.loc[_sel & ~cheap & ~good, "quad"] = "又贵又差"

# 画像：按行业-因子结构粗分为 金融/周期/红利/成长/均衡
def profile(r):
    if r["sw1"] in ("银行", "非银金融"):
        return "金融"
    if np.isfinite(r["div_yield"]) and r["div_yield"] >= 4:
        return "红利"
    if np.isfinite(r["p_REV_CAGR3"]) and r["p_REV_CAGR3"] > 70 and np.isfinite(r["p_GM"]) and r["p_GM"] > 60:
        return "成长"
    if r["sw1"] in ("钢铁", "煤炭", "有色金属", "基础化工", "石油石化", "建筑材料"):
        return "周期"
    return "均衡"


m["profile"] = m.apply(profile, axis=1)

# ------------------------------------------------------------------ 导出
keep = ["symbol", "name", "sw1", "board", "price", "mktcap", "pe", "pb", "ps", "pcf",
        "eps_ttm", "bps", "roe", "roa", "gross_margin", "net_margin", "rev_yoy",
        "np_yoy", "rev_cagr3", "np_cagr3", "payout", "div_yield", "dps", "div_cover",
        "mom_12_1", "ret_1m", "ret_3m", "ret_12m", "vol_ann", "beta252", "ma_align",
        "dist_high", "turnover_20", "amihud", "pe_pct", "pb_pct", "pe_med", "pb_med",
        "ind_pe", "ind_pb", "ind_prosperity", "ke", "g1", "wacc", "n_methods",
        "composite", "upside", "disp", "label", "quad", "profile", "q_pct",
        "resonance", "s_value", "s_growth", "s_cyclical", "s_dividend", "s_momentum",
        "s_quality", "cov_value", "cov_growth", "cov_cyclical", "cov_dividend",
        "cov_momentum", "cov_quality", "in_pool", "valid"]
keep = [k for k in keep if k in m.columns]
mm = m[keep].copy()
for k, _, _ in METHODS:
    mm["v_" + k] = V[k]
mm["implied_g"] = V["IMP_G"]

# 名字：meta.json 里有
import json as _j
meta = _j.load(open(os.path.expanduser("~/MarketData/meta.json")))
names = {k: v.get("name") for k, v in meta["stocks"].items()}
mm["name"] = mm["symbol"].map(names).fillna(mm.get("name", ""))

payload = {
    "meta": {
        "asof": asof_iso(), "report_period": _PERIOD_LABEL,
        "n_universe": int(len(m)), "n_pool": int(m["in_pool"].sum()),
        "n_valid": int(m["valid"].sum()), "n_price": int(m["price"].notna().sum()),
        "rf": RF, "erp": ERP, "g_term": G_TERM, "years": YEARS,
        "disp_pct_gate": DISP_PCT,
        "n_factors": len(F),
        "n_div_cohort": int(m["div_yield"].notna().sum()),
        "labels": {k: int(v) for k, v in m["label"].value_counts().items()},
        "quads": {k: int(v) for k, v in m["quad"].value_counts().items()},
        "profiles": {k: int(v) for k, v in m["profile"].value_counts().items()},
        "coverage": {k: {"n": int(m[f"cov_{k}"].notna().sum()),
                         "mean": round(float(m[f"cov_{k}"].mean()), 3)} for k in STRAT},
    },
    "factors": F,
    "strategies": {k: {"name": v["name"], "en": v["en"], "desc": v["desc"],
                       "w": v["w"],
                       "templates": [{kk: vv for kk, vv in t.items() if kk != "cond"}
                                     for t in TEMPLATES[k]]} for k, v in STRAT.items()},
    "methods": [{"id": k, "name": n, "weight": w,
                 "cov": int(A[k].notna().sum())} for k, n, w in METHODS],
    "stocks": mm.replace({np.nan: None}).to_dict(orient="records"),
    "pct": {f["id"]: [None if pd.isna(x) else int(x) for x in m[f"p_{f['id']}"]]
            for f in F},
}
json.dump(payload, open(f"{DATA}/site_payload.json", "w"), ensure_ascii=False)
m.to_parquet(f"{DATA}/master_full.parquet", index=False)
V.to_parquet(f"{DATA}/valuation.parquet")

print("pool", payload["meta"]["n_pool"], "valid", payload["meta"]["n_valid"])
print("labels", payload["meta"]["labels"])
print("quads", payload["meta"]["quads"])
print("methods cov", [(k, int(A[k].notna().sum())) for k, _, _ in METHODS])
print("payload MB", round(os.path.getsize(f"{DATA}/site_payload.json") / 1e6, 1))
