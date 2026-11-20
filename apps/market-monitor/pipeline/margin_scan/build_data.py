#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
两融（融资盘）压力扫描 —— 指标计算层

核心口径与假设（全部显式声明，不藏在代码里）：
  1. 拥挤度     融资余额 / 流通市值。绝对余额大的是权重股，占比高的才是杠杆拥挤的交易品种。
  2. 加杠杆速度 20 日 Δ(融资余额/流通市值)。同样 8% 的占比，一个月内从 3% 拉到 8% 的
                风险远高于常年稳定在 8%——原文按静态占比排序，缺这一维。
  3. 建仓成本   以「融资买入额 × 半衰期 30 个交易日的指数衰减权重」加权收盘价。
                融资盘是滚动换手而非长期持有，简单等权 120 日均价会系统性低估近期高位加仓。
  4. 距追保线   按融资保证金比例 80%（现行最低）反推：初始维持担保比例 = (1+0.8)/0.8 = 225%。
                追保线取 150% → 触发价 = 0.6667 × 成本；平仓线 130% → 触发价 = 0.5778 × 成本。
                该指标只对"纯单票满杠杆"成立，是压力上限估计，非精确值。
  5. 流通市值还原 由流通股本底表按日线推算 fcap_T = fcap_base × close_T / close_base
                （用比值而非 float_shares × close_T，可对抗复权基准整体缩放），
                历史值再按 close_t/close_T 比例还原。流通股本是慢变量、低频校准，
                日更不再依赖全市场快照。

解释器：/opt/daily-tasks/venv/bin/python3
"""
import json
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
OUT = BASE / "out"

HALF_LIFE = 30.0          # 融资买入额衰减半衰期（交易日）
MARGIN_RATIO_INIT = 0.80  # 融资保证金比例（现行最低）
RATIO_CALL = 1.50         # 追保线
RATIO_LIQ = 1.30          # 平仓线

# 由保证金比例反推的触发价 / 成本 比例
INIT_GUARANTEE = (1 + MARGIN_RATIO_INIT) / MARGIN_RATIO_INIT   # 2.25
K_CALL = RATIO_CALL / INIT_GUARANTEE                            # 0.6667
K_LIQ = RATIO_LIQ / INIT_GUARANTEE                              # 0.5778


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def is_stock(code: str) -> bool:
    """只保留 A 股股票，剔除 ETF/LOF/可转债（套利盘不会强平，纳入会污染排序）"""
    return code.startswith(("60", "68", "00", "30", "8", "4", "92"))


# GB2312 区位码拼音边界（近似，仅用于搜索辅助，不追求准确率）
_PY_BOUND = [
    (0xB0A1, "a"), (0xB0C5, "b"), (0xB2C1, "c"), (0xB4EE, "d"), (0xB6EA, "e"),
    (0xB7A2, "f"), (0xB8C1, "g"), (0xB9FE, "h"), (0xBBF7, "j"), (0xBFA6, "k"),
    (0xC0AC, "l"), (0xC2E8, "m"), (0xC4C3, "n"), (0xC5B6, "o"), (0xC5BE, "p"),
    (0xC6DA, "q"), (0xC8BB, "r"), (0xC8F6, "s"), (0xCBFA, "t"), (0xCDDA, "w"),
    (0xCEF4, "x"), (0xD1B9, "y"), (0xD4D1, "z"), (0xD7FA, None),
]


def py_init(s: str) -> str:
    """取名称的拼音首字母（GB2312 区位码近似），用于前端搜索"""
    out = []
    for ch in str(s):
        if "\u4e00" <= ch <= "\u9fff":
            try:
                b = ch.encode("gbk")
                code = (b[0] << 8) | b[1]
            except Exception:
                continue
            ini = ""
            for i in range(len(_PY_BOUND) - 1):
                if _PY_BOUND[i][0] <= code < _PY_BOUND[i + 1][0]:
                    ini = _PY_BOUND[i][1] or ""
                    break
            if ini:
                out.append(ini)
        elif ch.isalnum():
            out.append(ch.lower())
    return "".join(out)


# ---------------------------------------------------------------- 交付前质量闸门
def quality_pre_gate(bars, T, dates):
    """闸门 A：行情/两融基准日一致、基准日覆盖率、日期连续性。

    2026-11-12 事故中，日线丢 1005 只后报告照常生成（池塌到 2702 只、
    融资余额只剩 15996 亿），靠肉眼才发现。此处把这类残缺变成硬中止。
    """
    bar_dates = sorted(bars["date"].unique())
    if not bar_dates or str(bar_dates[-1]) != T:
        raise SystemExit(
            "质量闸门 A 中止：行情最新日 %s 与两融基准日 %s 不一致，拒绝生成报告"
            % (bar_dates[-1] if bar_dates else "空", T))
    cov_T = bars[bars["date"] == T]["code"].nunique()
    if len(bar_dates) >= 2:
        cov_prev = bars[bars["date"] == bar_dates[-2]]["code"].nunique()
        if cov_prev and cov_T < 0.98 * cov_prev:
            raise SystemExit(
                "质量闸门 A 中止：基准日行情覆盖 %d 只 < 前一日 %d 只的 98%%，疑似抓数残缺"
                % (cov_T, cov_prev))
    bset = set(bar_dates)
    recent = list(dates)[-20:]
    hit = sum(1 for d in recent if d in bset)
    if recent and hit < len(recent) * 0.95:
        raise SystemExit(
            "质量闸门 A 中止：最近 %d 个交易日仅 %d 天有行情，日期不连续"
            % (len(recent), hit))
    log("质量闸门 A 通过：行情/两融同为 %s，覆盖 %d 只，近 %d 日连续"
        % (T, cov_T, len(recent)))


def quality_post_gate(ov, prev, T):
    """闸门 B：池只数 / 融资余额 / 基准日，与上一版对比。

    必须在写 payload.js 之前执行 —— 一旦写出，update.sh 就会同步 src 并重建 HTML。
    """
    if not prev or not prev.get("overview"):
        log("质量闸门 B 跳过：无上一版 payload（首次运行）")
        return
    po = prev["overview"]
    bad = []
    n0, n1 = po.get("n_total"), ov["n_total"]
    if n0 and abs(n1 / n0 - 1) > 0.05:
        bad.append("股票池 %d → %d（偏离 %.1f%% > 5%%）"
                   % (n0, n1, (n1 / n0 - 1) * 100))
    r0, r1 = po.get("rz_total"), ov["rz_total"]
    if r0 and abs(r1 / r0 - 1) > 0.10:
        bad.append("融资余额 %.0f → %.0f 亿（偏离 %.1f%% > 10%%）"
                   % (r0, r1, (r1 / r0 - 1) * 100))
    p_asof = (prev.get("meta") or {}).get("as_of")
    if p_asof and T < p_asof:
        bad.append("基准日倒退 %s → %s" % (p_asof, T))
    if bad:
        raise SystemExit("质量闸门 B 中止，保住上一版成品：\n  " + "\n  ".join(bad))
    log("质量闸门 B 通过：池 %d 只、融资余额 %.0f 亿，与上一版偏离在阈值内"
        % (n1, r1))


def main():
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    bars = pd.read_parquet(DATA / "bars.parquet")
    margin = pd.read_parquet(DATA / "margin_hist.parquet")
    spot = pd.read_parquet(DATA / "spot.parquet")
    acct = pd.read_parquet(DATA / "account.parquet")
    # 上一版产物：闸门 B 的对照基准（必须在写新 payload 之前读）
    prev_path = OUT / "payload.json"
    prev = (json.loads(prev_path.read_text(encoding="utf-8"))
            if prev_path.exists() else None)

    # 统一日期口径为 YYYY-MM-DD（两融原始为 YYYYMMDD，行情为 YYYY-MM-DD，不统一会导致按行对齐失败）
    margin["date"] = pd.to_datetime(margin["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")

    T = str(margin["date"].max())                      # 基准日 = 两融明细实际最新日（T+1 披露）
    Td = T
    log("基准日 T = %s（交易日历最后一天 %s）" % (T, meta["as_of"]))

    # ---------------- 宽表：date × code
    close_w = bars.pivot(index="date", columns="code", values="close")
    amt_w = bars.pivot(index="date", columns="code", values="amount")
    rz_w = margin.pivot(index="date", columns="code", values="rz")
    rzbuy_w = margin.pivot(index="date", columns="code", values="rz_buy")
    rqvol_w = margin.pivot(index="date", columns="code", values="rq_vol")

    # 融资余额按两融明细的交易日索引（T+1 披露，最后一天即 T）
    dates = [d for d in sorted(rz_w.index)]
    dates = dates[-min(len(dates), 121):]
    rz_w = rz_w.loc[dates]
    rzbuy_w = rzbuy_w.loc[dates]
    rqvol_w = rqvol_w.loc[dates]

    # 行情对齐到同一批日期（此时已统一为 YYYY-MM-DD）
    close_all = bars.pivot(index="date", columns="code", values="close")
    amt_all = bars.pivot(index="date", columns="code", values="amount")
    close_w = close_all.reindex(dates)
    amt_w = amt_all.reindex(dates)
    close_last = close_all.iloc[-1]

    if Td not in close_w.index:
        raise SystemExit("行情缺少基准日 %s 的数据" % Td)
    close_T = close_w.loc[Td]
    quality_pre_gate(bars, Td, dates)

    # ---------------- 股票池筛选
    spot = spot[spot["code"].map(is_stock)].copy()
    spot = spot.set_index("code")
    pool = [c for c in rz_w.columns
            if is_stock(c) and c in spot.index and c in close_T.index
            and pd.notna(close_T.get(c)) and spot.loc[c, "fcap"] > 0]
    log("股票池：两融标的 %d → 有效 %d" % (len(rz_w.columns), len(pool)))

    rz_w = rz_w[pool]
    rzbuy_w = rzbuy_w[pool].reindex(dates)
    rqvol_w = rqvol_w[pool].reindex(dates)
    close_w = close_w[pool]
    amt_w = amt_w[pool]

    # ---------------- 流通市值还原（流通股本底表驱动）
    # 原式 fcap_T = fcap_spot × close_T / close_last 中，close_last 就是 bars 最后一天
    # (=T)，因此 close_T == close_last、scale 恒为 1、fcap_T 恒等于 fcap_spot ——
    # 等价于「每天必须抓到 59 页全市场快照」，这是 2026-11-12 事故的根因。
    # 改为：fcap_T = fcap_base × close_T / close_base，由日线自己算出当日流通市值。
    fcap_spot = spot.loc[pool, "fcap"].astype(float)
    fs_path = DATA / "float_shares.parquet"
    fsm_path = DATA / "float_shares.meta.json"
    if fs_path.exists() and fsm_path.exists():
        fsm = json.loads(fsm_path.read_text(encoding="utf-8"))
        base_date = fsm["base_date"]
        fs = pd.read_parquet(fs_path).set_index("code")
        if base_date not in close_all.index:
            raise SystemExit("股本底表基准日 %s 不在日线中，请重跑 analysis/build_float_shares.py"
                             % base_date)
        close_base = close_all.loc[base_date]
        fcap_base = pd.to_numeric(fs["fcap_base"], errors="coerce").reindex(pool)
        px = (close_T[pool] / close_base.reindex(pool)) \
            .replace([np.inf, -np.inf], np.nan).fillna(1.0)
        fcap_T = fcap_base * px
        miss = fcap_base.isna()
        if miss.any():
            log("  股本底表缺 %d 只，回退快照 fcap（这些票 ratio 仍有一天偏差）"
                % int(miss.sum()))
            fcap_T[miss] = fcap_spot[miss]
        log("流通市值：底表基准 %s，覆盖 %d/%d 只，fcap 已推进至 T 日"
            % (base_date, len(pool) - int(miss.sum()), len(pool)))
    else:
        fcap_T = fcap_spot
        log("警告：无股本底表，退回旧口径 fcap_T = fcap_spot（可能滞后一天）")
    # 历史流通市值 ≈ fcap_T × close_t / close_T（停牌日按前值填充，避免 ratio 与 rz 不同步）
    fcap_w = close_w.div(close_T[pool], axis=1).mul(fcap_T, axis=1).ffill()

    # ---------------- 基础指标
    # 先对分子分母分别前值填充，再相除，保证 ratio_T == rz_T / fcap_T 恒成立
    # （否则停牌股、次新股的 ratio 会与展示的 rz/fcap 对不上）
    rz_w = rz_w.ffill()
    fcap_w = fcap_w.ffill()
    ratio_w = rz_w / fcap_w * 100.0                    # 融资余额占流通市值 %
    ratio_T = ratio_w.iloc[-1]
    rz_T = rz_w.iloc[-1]
    rq_T = rqvol_w.iloc[-1] * close_T[pool]            # 融券余量(股) × 收盘价 → 融券余额(元)

    def _at(series_df, n):
        """取倒数第 n+1 行"""
        return series_df.iloc[-1 - n] if len(series_df) > n else pd.Series(np.nan, index=pool)

    ratio_20 = _at(ratio_w, 20)
    rz_5 = _at(rz_w, 5)
    rz_20 = _at(rz_w, 20)

    dratio20 = (ratio_T - ratio_20)                    # 百分点 / 20 交易日
    rz_chg5 = (rz_T / rz_5 - 1) * 100
    rz_chg20 = (rz_T / rz_20 - 1) * 100

    # 融资买入额占成交额（近 5 日）
    buy5 = rzbuy_w.iloc[-5:].sum()
    amt5 = amt_w.iloc[-5:].sum()
    buy_share5 = (buy5 / amt5 * 100).replace([np.inf, -np.inf], np.nan)
    # 杠杆沉淀天数：融资余额相当于多少天的成交额
    amt5_avg = amt5 / 5.0
    rz_days = (rz_T / amt5_avg).replace([np.inf, -np.inf], np.nan)

    # ---------------- 估算建仓成本（指数衰减加权）
    n = len(dates)
    age = np.arange(n)[::-1].astype(float)             # 最新为 0
    decay = 0.5 ** (age / HALF_LIFE)
    W = rzbuy_w.values * decay[:, None]
    C = close_w.values
    valid = np.isfinite(C) & np.isfinite(W)
    W = np.where(valid, W, 0.0)
    C0 = np.where(np.isfinite(C), C, 0.0)
    num = (W * C0).sum(axis=0)
    den = W.sum(axis=0)
    cost = np.where(den > 0, num / np.maximum(den, 1e-12), np.nan)
    cost = pd.Series(cost, index=pool)
    pnl = (close_T[pool] / cost - 1) * 100              # 融资盘整体浮盈亏 %

    # ---------------- 距追保 / 平仓线剩余跌幅
    k = close_T[pool] / cost
    buf_call = (1 - K_CALL / k) * 100                   # 再跌多少触发追保线（负=已过线）
    buf_liq = (1 - K_LIQ / k) * 100

    # ---------------- 位置与动量
    pos120 = (close_T[pool] / close_w.iloc[-min(120, n):].max() - 1) * 100
    ret20 = (close_T[pool] / _at(close_w, 20) - 1) * 100
    ret5 = (close_T[pool] / _at(close_w, 5) - 1) * 100
    hi120 = close_w.iloc[-min(120, n):].max()

    df = pd.DataFrame({
        "code": pool,
        "name": [spot.loc[c, "name"] for c in pool],
        "price": close_T[pool].values,
        "chg": (close_w.iloc[-1] / close_w.iloc[-2] - 1).values * 100,   # 基准日涨跌幅
        "fcap": fcap_T.values / 1e8,                    # 亿元
        "rz": rz_T.values / 1e8,                        # 亿元
        "ratio": ratio_T.values,
        "dratio20": dratio20.values,
        "rz_chg5": rz_chg5.values,
        "rz_chg20": rz_chg20.values,
        "buy_share5": buy_share5.values,
        "rz_days": rz_days.values,
        "rq": rq_T.values / 1e8,
        "cost": cost.values,
        "pnl": pnl.values,
        "buf_call": buf_call.values,
        "buf_liq": buf_liq.values,
        "pos120": pos120.values,
        "ret20": ret20.values,
        "ret5": ret5.values,
        "turn5": (amt5 / fcap_T / 5 * 100).values,      # 近 5 日日均换手（额/流通市值）
    })
    df = df.set_index("code", drop=False)

    # ---------------- 动态风险维度：波动率与成交异动 ----------------
    # 静态成本线只说明「杠杆压在哪个价位」；经验检验里，未来 5 日快速下跌的
    # 主导变量是波动率与成交状态，而非距理论线的距离。这里并列给出，供对照阅读。
    ret_w = close_w.pct_change().where(amt_w > 0)       # 停牌日不计入波动
    vol20 = ret_w.iloc[-20:].std(ddof=1) * 100          # 日波动率 %
    amt20 = amt_w.iloc[-20:].mean()
    amt_vr = amt_w.iloc[-1] / amt20.replace(0, np.nan)
    df["vol20"] = vol20.reindex(df.index).values
    df["amt_vr"] = amt_vr.reindex(df.index).values
    df["vol_pct"] = df["vol20"].rank(pct=True) * 100    # 全市场横截面分位

    # ---------------- 持仓结构层：把别的"被动卖出机制"也算成成本线
    import structure as st
    price_s = pd.Series(close_T[pool].values, index=pool)
    fcap_yuan = pd.Series(fcap_T.values, index=pool)
    sd = pd.DataFrame(index=pool)
    try:
        sd = st.build(price_s, fcap_yuan, Td)
        add = [c for c in sd.columns if c not in df.columns]
        df = df.join(sd[add], how="left")
        log("持仓结构合并：新增 %d 列" % len(add))
        for c, label in [("pld_line", "质押"), ("ulk120", "解禁"), ("cb_conv", "转债"),
                         ("blk_amt", "大宗"), ("gdhs_chg", "户数"),
                         ("lhb_net", "龙虎榜"), ("fund_pct", "公募"),
                         ("bb_amt_hi", "回购"), ("hold_net", "增减持")]:
            if c in df.columns:
                log("   %-6s 覆盖 %d 只" % (label, int(df[c].notna().sum())))
    except Exception as e:
        log("持仓结构层失败（不阻断主流程）：%r" % (e,))

    # ---------------- 成本线共振带
    try:
        df = df.join(st.resonance(df))
        log("共振带：≥1条线 %d / ≥2条 %d / ≥3条 %d 只"
            % (int((df.res_cnt >= 1).sum()), int((df.res_cnt >= 2).sum()),
               int((df.res_cnt >= 3).sum())))
    except Exception as e:
        log("共振带计算失败：%r" % (e,))
        df["res_cnt"] = 0.0
        df["res_lo"] = np.nan
        df["res_hi"] = np.nan
        df["res_ev"] = 0.0
        df["res_score"] = 0.0
        df["res_detail"] = ""
        df["res_ev_tag"] = ""

    # ---------------- 压力分（三维分位合成）
    def pr(s):
        return s.rank(pct=True) * 100

    C_ = pr(df["ratio"])                                # 拥挤度
    S_ = pr(df["dratio20"])                             # 加杠杆速度
    P_ = pr(-df["pnl"])                                 # 浮亏深度
    G_ = pr(df["pos120"])                               # 价格位置（越高越危险）
    df["pct_crowd"], df["pct_speed"], df["pct_loss"], df["pct_pos"] = C_, S_, P_, G_
    # 压力分：现状视角，含浮亏 —— 回答"现在有多紧张"
    df["score"] = 0.40 * C_ + 0.30 * S_ + 0.30 * P_
    # 脆弱度：前瞻视角，剔除浮亏 —— 回答"未来多容易出事"
    df["frag"] = 0.45 * C_ + 0.35 * S_ + 0.20 * G_

    # ---------------- 标签
    def tags(r):
        t = []
        if r.ret20 < -8 and r.dratio20 > 0.3:
            t.append("价跌加杠杆")
        if r.pos120 > -3 and r.dratio20 > 0 and r.ret20 > 0:
            t.append("高位加杠杆")
        if r.ret20 > 8 and r.rz_chg5 < -3:
            t.append("涨中撤杠杆")
        if r.buy_share5 > 14:
            t.append("杠杆定价")
        if r.rz_days > 8:
            t.append("杠杆沉淀厚")
        if r.ratio > 8:
            t.append("占比畸高")
        return "|".join(t)

    df["tags"] = df.apply(tags, axis=1)

    # ---------------- 状态：按浮亏深度与杠杆拥挤度做分类（描述性标签，非下跌预测）
    # 理论追保/平仓线只对「80% 保证金满仓」的极端账户成立，全市场平均维持担保比例 250%+；
    # 120 日样本检验未发现「贴线 → 主动卸杠杆 → 加速下跌」的稳定证据，贴线区反而缩量。
    # 因此状态只描述位置，不代表风险即将来临。
    def state(r):
        if pd.isna(r.buf_call):
            return "数据不足"
        if r.buf_call < 0:
            return "已去杠杆"
        if r.buf_call < 15:
            return "临界"
        if r.ratio > 6 and r.dratio20 > 0.25:
            return "潜伏"
        return "安全"

    df["state"] = df.apply(state, axis=1)
    df["py"] = [py_init(n) for n in df["name"]]

    # 分级：高危只给"临界"，已去杠杆的单独归类，不混入高危
    # 共振带：融资强平 + 质押强平两条线同时落在现价下方 25% 内 → 两类机制共振，直接进高危
    df["level"] = np.select(
        [
            (df["state"] == "临界") & (df["score"] >= 65),
            (df["res_cnt"] >= 2),
            ((df["state"] == "潜伏") & (df["frag"] >= 85)) |
            ((df["state"] == "已去杠杆") & (df["score"] >= 92)) |
            (df["res_score"] >= 2.5),
        ],
        ["高危", "高危", "关注"], default="正常")

    log("分级：高危 %d / 关注 %d / 正常 %d"
        % ((df.level == "高危").sum(), (df.level == "关注").sum(), (df.level == "正常").sum()))
    log("状态：%s" % df.state.value_counts().to_dict())
    log("全市场融资余额合计 %.0f 亿；占比中位数 %.2f%%；P90 %.2f%%；已过追保线 %d 只"
        % (df.rz.sum(), df.ratio.median(), df.ratio.quantile(0.9), (df.buf_call < 0).sum()))

    # ---------------- 历史序列（个股体检用，日期提到全局避免重复存储）
    NSEQ = 60
    hist_dates = list(close_w.index[-NSEQ:])
    hist = {}
    for c in df.index:
        cl = close_w[c].iloc[-NSEQ:]
        rz = rz_w[c].iloc[-NSEQ:]
        hist[c] = {
            "c": [None if pd.isna(x) else round(float(x), 2) for x in cl.values],
            "r": [None if pd.isna(x) else round(float(x) / 1e8, 2) for x in rz.values],
        }

    # ---------------- 全市场杠杆水位
    acct = acct.dropna(subset=["ratio"]).copy()
    acct_tail = acct.tail(250)

    rz_series = rz_w.sum(axis=1) / 1e8                      # 亿元
    fcap_series = fcap_w.sum(axis=1) / 1e8
    lev_ratio = (rz_series / fcap_series * 100)
    rz_20ago = float(rz_series.iloc[-21]) if len(rz_series) > 21 else np.nan

    ov = {
        "rz_total": float(df.rz.sum()),
        "rq_total": float(df.rq.sum()),
        "n_total": int(len(df)),
        "n_high": int((df.level == "高危").sum()),
        "n_watch": int((df.level == "关注").sum()),
        "ratio_med": float(df.ratio.median()),
        "ratio_p90": float(df.ratio.quantile(0.90)),
        "ratio_p99": float(df.ratio.quantile(0.99)),
        "n_over8": int((df.ratio > 8).sum()),
        "n_over10": int((df.ratio > 10).sum()),
        "n_critical": int((df.state == "临界").sum()),
        "n_latent": int((df.state == "潜伏").sum()),
        "n_flushed": int((df.state == "已去杠杆").sum()),        "rz_chg20_total": float((rz_series.iloc[-1] / rz_20ago - 1) * 100) if rz_20ago else np.nan,
        "guarantee": float(acct["ratio"].iloc[-1]),
        "guarantee_date": str(acct["date"].iloc[-1]),
        "lever_series": {
            "d": list(close_w.index),
            "rz": [round(float(x), 1) for x in rz_series.values],
            "ratio": [round(float(x), 3) for x in lev_ratio.values],
        },
        "guarantee_series": {
            "d": list(acct_tail["date"]),
            "v": [round(float(x), 1) for x in acct_tail["ratio"]],
        },
        "investor_series": {
            "d": list(acct_tail["date"]),
            "v": [None if pd.isna(x) else round(float(x), 1)
                  for x in acct_tail["n_investor"]],
        },
    }

    # ---------------- 持仓结构总览
    def _n(cond, c):
        return int(cond.sum()) if c in df.columns else 0

    def _s(c):
        return df[c] if c in df.columns else pd.Series(np.nan, index=df.index)

    res_hist = []
    for k in range(0, 5):
        res_hist.append({
            "k": k if k < 4 else "4+",
            "n": int((df["res_cnt"].fillna(0) == k).sum()) if k < 4
                 else int((df["res_cnt"].fillna(0) >= 4).sum()),
        })

    ov.update({
        "n_pledge": _n(_s("pld_line").notna(), "pld_line"),
        "n_pledge_near": _n((_s("pld_room") > 0) & (_s("pld_room") <= 15), "pld_room"),
        "n_pledge_breach": _n(_s("pld_room") <= 0, "pld_room"),
        "pledge_mv_total": float(_s("pld_mv_ratio").sum(skipna=True)) if "pld_mv_ratio" in df else 0.0,
        "n_unlock60": _n(_s("ulk60") >= 5, "ulk60"),
        "unlock60_total": float(_s("ulk60").sum(skipna=True)) if "ulk60" in df else 0.0,
        "n_cb_arb": _n(_s("cb_prem") < 0, "cb_prem"),
        "n_cb": _n(_s("cb_prem").notna(), "cb_prem"),
        "n_block": _n(_s("blk_ratio") > 0, "blk_ratio"),
        "n_gdhs_dump": _n(_s("gdhs_dump") >= 1, "gdhs_dump"),
        "n_fund": _n(_s("fund_pct").notna(), "fund_pct"),
        "n_res2": _n(df["res_cnt"] >= 2, "res_cnt"),
        "n_res3": _n(df["res_cnt"] >= 3, "res_cnt"),
        "res_hist": res_hist,
        "struct_src": {
            "pledge": "交易所周度质押快照 + 单笔质押明细（含预估平仓线）",
            "unlock": "限售解禁明细（按现价估算未来解禁市值）",
            "cb": "可转债比价（317 只在交易）",
            "block": "大宗交易每日统计（近30日）",
            "gdhs": "股东户数（最新快照，多数标的按旬更新）",
            "lhb": "龙虎榜机构席位统计（近40日）",
            "fund": "公募基金季报重仓（2026Q3）",
            "buyback": "回购计划",
            "holders": "重要股东增减持（近120日）",
        },
    })

    # ---------------- 序列化（列式，控制体积）
    fields = ["code", "name", "py", "price", "chg", "fcap", "rz", "ratio", "dratio20",
              "rz_chg5", "rz_chg20", "buy_share5", "rz_days", "rq", "cost", "pnl",
              "buf_call", "buf_liq", "pos120", "ret20",
              "vol20", "vol_pct", "amt_vr",
              "pct_crowd", "pct_speed", "pct_loss", "pct_pos",
              "score", "frag", "level", "state", "tags",
              # 持仓结构层
              "pld_ratio", "pld_room", "pld_line", "pld_maxline", "pld_n", "pld_mv_ratio",
              "ulk60", "ulk120", "ulk_next", "ulk_next_ratio",
              "cb_prem", "cb_room", "cb_force_up",
              "blk_ratio", "blk_disc", "blk_n",
              "gdhs_chg", "gdhs_ret", "gdhs_avg_mv", "gdhs_dump",
              "lhb_net_ratio", "lhb_n",
              "fund_n", "fund_pct", "fund_chg",
              "bb_ratio", "bb_prem",
              "hold_ratio",
              "res_cnt", "res_lo", "res_hi", "res_score", "res_detail", "res_ev_tag"]
    # 只保留实际存在的列，避免上游缺数据时整表崩
    fields = [f for f in fields if f in df.columns]
    nd = {"code", "name", "py", "level", "state", "tags", "res_detail",
          "res_ev_tag", "ulk_type"}
    cols = {}
    for f in fields:
        if f in nd:
            cols[f] = ["" if (isinstance(x, float) and pd.isna(x)) else str(x)
                       for x in df[f].tolist()]
        else:
            cols[f] = [None if pd.isna(x) else round(float(x), 2) for x in df[f].tolist()]

    payload = {
        "meta": {
            "as_of": T,
            "as_of_date": Td,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "n": int(len(df)),
            "assumptions": {
                "margin_ratio_init": MARGIN_RATIO_INIT,
                "init_guarantee": round(INIT_GUARANTEE, 4),
                "k_call": round(K_CALL, 4),
                "k_liq": round(K_LIQ, 4),
                "half_life": HALF_LIFE,
            },
        },
        "overview": ov,
        "fields": fields,
        "rows": cols,
        "hist_dates": hist_dates,
        "hist": hist,
    }

    # 写任何产物之前过闸门 B；不达标则中止，update.sh 的 set -e 会保住上一版 HTML
    quality_post_gate(ov, prev, T)

    if not OUT.exists():
        OUT.mkdir(parents=True)
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    p = OUT / "payload.js"
    p.write_text("window.PAYLOAD=" + js + ";", encoding="utf-8")
    log("payload.js 落盘 %.2f MB" % (p.stat().st_size / 1024 / 1024))
    (OUT / "payload.json").write_text(js, encoding="utf-8")
    # 构建工具按 src/index.html 所在目录解析相对路径，src/payload.js 必须与 out/ 是同一份数据。
    # 手工跑 build_data.py 后若不同步，成品 HTML 会静默使用旧数据（历史上踩过一次）。
    src_dir = BASE / "src"
    if src_dir.exists():
        (src_dir / "payload.js").write_text("window.PAYLOAD=" + js + ";", encoding="utf-8")
        log("已同步 src/payload.js（避免手工构建读到旧数据）")

    df.to_parquet(DATA / "metrics.parquet")
    shown = ["name", "rz", "ratio", "dratio20", "pnl", "buf_call", "pos120",
             "score", "frag", "state", "level"]
    print("\n=== 压力分 TOP 20 ===")
    print(df.sort_values("score", ascending=False).head(20)[shown].to_string())
    print("\n=== 脆弱度（前瞻）TOP 20 —— 还没出事但杠杆已堆高 ===")
    print(df.sort_values("frag", ascending=False).head(20)[shown].to_string())


if __name__ == "__main__":
    main()
