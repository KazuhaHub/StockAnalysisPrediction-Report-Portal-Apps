#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓结构层：把"有被动卖出机制的持仓"统一换算成【现价下方的成本线位置】。

统一的量纲：room = (1 - 成本线价 / 现价) × 100
    room > 0  该成本线在现价下方 room% 处（跌到那里才触发）
    room < 0  现价已经跌破该成本线（机制已被触发）

这样融资盘追保线、质押平仓线、转债转股价可以放进同一个价格轴比较，
进而统计"有多条线落在同一个跌幅窗口内"——即成本线共振带。
"""
import glob
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"

# 质押率 40%、平仓线 140% 反推：预估平仓线 ≈ 质押日收盘价 × 0.56
PLEDGE_RATIO = 0.40
PLEDGE_LIQ_LINE = 1.40


def col(df, *keys, exclude=()):
    """按关键字找列名，容忍不同数据源的列名差异。"""
    for c in df.columns:
        s = str(c)
        if all(k in s for k in keys) and not any(e in s for e in exclude):
            return c
    return None


def num(s):
    return pd.to_numeric(s, errors="coerce")


def norm_code(s):
    """统一成 6 位字符串代码：兼容 301018 / 301018.0 / '301018' 三种形态。"""
    def f(x):
        try:
            if pd.isna(x):
                return None
            v = float(x)
            if v == int(v):
                return str(int(v)).zfill(6)
        except Exception:
            pass
        return str(x).strip().zfill(6)
    return s.map(f)


def unit_factor(detail: pd.DataFrame, qty_col, mv_col, px_col):
    """自动判定数量列单位：股 or 万股。返回换算到【股】的乘数。"""
    q = num(detail[qty_col])
    mv = num(detail[mv_col])
    px = num(detail[px_col])
    m = (mv / q / px).replace([np.inf, -np.inf], np.nan).dropna()
    if len(m) == 0:
        return 1.0
    med = float(m.median())
    if med < 10:
        return 1.0            # 数量已是股：市值/数量 ≈ 股价
    if med > 1000:
        return 1e4            # 数量是万股
    return 1.0


# ---------------------------------------------------------------- P0-1 质押
def calc_pledge(price, fcap, Tstr):
    p = DATA / "pledge.parquet"
    if not p.exists():
        return pd.DataFrame(index=price.index)
    d = pd.read_parquet(p)
    c_code = col(d, "股票代码") or col(d, "代码")
    c_qty = col(d, "质押股份数量") or col(d, "质押数量")
    c_line = col(d, "预估平仓线")
    c_px0 = col(d, "质押日收盘价")
    c_ratio = col(d, "占总股本比例")
    c_state = col(d, "状态")
    c_end = col(d, "质押结束日期")
    c_start = col(d, "质押开始日期")
    d = d.copy()
    d["code"] = norm_code(d[c_code])
    d["qty"] = num(d[c_qty])
    d["line"] = num(d[c_line])
    if c_px0:
        d["px0"] = num(d[c_px0])
        if d["line"].notna().sum() == 0:
            d["line"] = d["px0"] * PLEDGE_RATIO * PLEDGE_LIQ_LINE
    d = d[d["qty"] > 0]

    # 只保留仍在质押中的（已解押的不构成平仓压力）；结束日期为空的视为存续
    T = pd.Timestamp(Tstr)
    if c_start:
        s0 = pd.to_datetime(d[c_start], errors="coerce")
        d = d[s0.isna() | (s0 >= T - pd.Timedelta(days=1095))]
    if c_state:
        alive = ~d[c_state].astype(str).str.contains("已解押")
        d = d[alive]
    if c_end:
        e = pd.to_datetime(d[c_end], errors="coerce")
        d = d[e.isna() | (e > T)]

    g = d.groupby("code")
    wline = g.apply(lambda x: np.nansum(x["line"] * x["qty"]) / np.nansum(x["qty"])
                    if np.nansum(x["qty"]) > 0 else np.nan)
    out = pd.DataFrame({
        "pld_line": wline,
        "pld_maxline": g["line"].max(),
        "pld_n": g.size(),
        "pld_qty": g["qty"].sum(),
    })

    # 质押比例：优先用交易所周度快照（口径统一），缺失处用明细加总补齐
    pr = DATA / "pledge_ratio.parquet"
    snap = None
    if pr.exists():
        r = pd.read_parquet(pr)
        cc = col(r, "股票代码")
        cr = col(r, "质押比例")
        if cc and cr:
            r = r[[cc, cr]].dropna()
            r[cc] = norm_code(r[cc])
            snap = r.set_index(cc)[cr].rename("pld_ratio")
    if snap is not None:
        out = out.join(snap, how="left")
    if c_ratio:
        by_detail = g[c_ratio].sum().clip(upper=100)
        if "pld_ratio" in out.columns:
            out["pld_ratio"] = out["pld_ratio"].fillna(by_detail)
        else:
            out["pld_ratio"] = by_detail

    out["pld_mv"] = out["pld_qty"] * price.reindex(out.index)      # 元
    out["pld_mv_ratio"] = out["pld_mv"] / fcap.reindex(out.index) * 100
    # 距平仓线可跌空间（%）：正数=平仓线在下方，负数=已跌破
    out["pld_room"] = (1 - out["pld_line"] / price.reindex(out.index)) * 100
    out["pld_room_max"] = (1 - out["pld_maxline"] / price.reindex(out.index)) * 100
    return out


# ---------------------------------------------------------------- P0-2 解禁
def calc_unlock(price, fcap, Tstr):
    p = DATA / "unlock.parquet"
    if not p.exists():
        return pd.DataFrame(index=price.index)
    d = pd.read_parquet(p).copy()
    c_code = col(d, "股票代码")
    c_date = col(d, "解禁时间")
    c_qty = col(d, "解禁数量", exclude=("实际",))
    c_act = col(d, "实际解禁数量")
    c_mv = col(d, "实际解禁市值")
    c_px = col(d, "解禁前一交易日收盘价")
    c_type = col(d, "限售股类型")

    d["code"] = norm_code(d[c_code])
    d["dt"] = pd.to_datetime(d[c_date], errors="coerce")

    # 单位自适应：以历史已实现解禁数据标定数量列单位
    f = 1.0
    if c_mv and c_act and c_px:
        hist = d[num(d[c_mv]) > 0]
        if len(hist):
            f = unit_factor(hist, c_act, c_mv, c_px)
    d["qty"] = num(d[c_act]).fillna(num(d[c_qty])) * f

    T = pd.Timestamp(Tstr)
    d = d[d["dt"].notna()]
    fut = d[d["dt"] >= T].copy()
    fut["mv"] = fut["qty"] * price.reindex(fut["code"]).values      # 用现价估算未来解禁市值
    fut["ratio"] = fut["mv"] / fcap.reindex(fut["code"]).values * 100

    out = pd.DataFrame(index=price.index)
    for days, tag in [(60, "60"), (120, "120"), (250, "250")]:
        w = fut[fut["dt"] <= T + pd.Timedelta(days=days)]
        s = w.groupby("code")["ratio"].sum()
        out["ulk" + tag] = s.reindex(out.index)
    out["ulk_next"] = (fut.groupby("code")["dt"].min() - T).dt.days.reindex(out.index)
    out["ulk_next_ratio"] = (fut.sort_values("dt").groupby("code")["ratio"]
                             .first().reindex(out.index))
    if c_type:
        big = fut[fut["ratio"] >= 3].groupby("code")[c_type].first()
        out["ulk_type"] = big.reindex(out.index)
    return out


# ---------------------------------------------------------------- P0-3 转债
def calc_cb(price, fcap):
    p = DATA / "cb.parquet"
    if not p.exists():
        return pd.DataFrame(index=price.index)
    d = pd.read_parquet(p).copy()
    c_code = col(d, "正股代码")
    c_conv = col(d, "转股价")
    c_prem = col(d, "转股溢价率")
    c_force = col(d, "强赎触发价")
    c_put = col(d, "回售触发价")
    c_bal = col(d, "剩余规模") or col(d, "债券余额") or col(d, "余额")
    c_name = col(d, "转债名称")

    d["code"] = norm_code(d[c_code])
    d["conv"] = num(d[c_conv])
    d["prem"] = num(d[c_prem])
    d["force"] = num(d[c_force]) if c_force else np.nan
    d["bal"] = num(d[c_bal]) if c_bal else np.nan

    out = pd.DataFrame(index=price.index)
    g = d.groupby("code")
    out["cb_prem"] = g["prem"].min()                       # 最低转股溢价率（负值=套利空间）
    out["cb_conv"] = g["conv"].first()
    out["cb_name"] = g[c_name].first() if c_name else ""
    out["cb_bal"] = g["bal"].sum()                         # 元
    out["cb_bal_ratio"] = out["cb_bal"] / fcap.reindex(out.index) * 100
    out["cb_force"] = g["force"].first() if c_force else np.nan
    # 距转股价（负=转股价在现价上方，尚未进入实值）
    out["cb_room"] = (1 - out["cb_conv"] / price.reindex(out.index)) * 100
    # 距强赎触发（现价还要涨多少才触发强赎）= 强制转股抛压的前瞻位
    out["cb_force_up"] = (out["cb_force"] / price.reindex(out.index) - 1) * 100
    return out


# ---------------------------------------------------------------- P1-1 大宗
def calc_block(fcap, Tstr):
    p = DATA / "block.parquet"
    if not p.exists():
        return pd.DataFrame(index=fcap.index)
    d = pd.read_parquet(p).copy()
    c_code = col(d, "证券代码") or col(d, "代码")
    c_dt = col(d, "交易日期")
    c_amt = col(d, "成交总额", exclude=("流通",))
    c_rate = col(d, "折溢率")
    c_cnt = col(d, "成交笔数")

    d["code"] = norm_code(d[c_code])
    d["dt"] = pd.to_datetime(d[c_dt], errors="coerce")
    d["amt"] = num(d[c_amt]) * 1e4      # 东财该字段单位为万元，换算到元
    d["rate"] = num(d[c_rate])
    # 折溢率为小数（0.0036 = +0.36%），统一到百分数
    if d["rate"].abs().max(skipna=True) is not None and d["rate"].abs().max() < 1:
        d["rate"] = d["rate"] * 100

    T = pd.Timestamp(Tstr)
    w = d[(d["dt"] <= T) & (d["dt"] >= T - pd.Timedelta(days=45))]

    out = pd.DataFrame(index=fcap.index)
    g = w.groupby("code")
    out["blk_amt"] = g["amt"].sum()
    out["blk_ratio"] = out["blk_amt"] / fcap.reindex(out.index) * 100
    out["blk_n"] = g.size()
    out["blk_disc"] = g.apply(lambda x: np.average(x["rate"].fillna(0), weights=x["amt"].fillna(1))
                              if x["amt"].notna().any() else np.nan)
    out["blk_cnt_day"] = g[c_cnt].sum() if c_cnt else np.nan
    return out


# ---------------------------------------------------------------- P1-2 股东户数
def calc_gdhs():
    p = DATA / "gdhs.parquet"
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_parquet(p).copy()
    c_code = col(d, "代码")
    c_chg = col(d, "增减比例")
    c_ret = col(d, "区间涨跌幅")
    c_now = col(d, "股东户数", exclude=("上次", "增减"))
    c_avg = col(d, "户均持股市值")
    c_dt = col(d, "统计截止日", exclude=("上次",))

    d["code"] = norm_code(d[c_code])
    out = pd.DataFrame(index=d["code"])
    out["gdhs_chg"] = num(d[c_chg]).clip(-200, 500).values   # 户数增减比例 %（正=分散）
    out["gdhs_ret"] = num(d[c_ret]).values            # 同期区间涨跌幅 %
    out["gdhs_n"] = num(d[c_now]).values
    out["gdhs_avg_mv"] = num(d[c_avg]).values         # 户均持股市值（元）
    out["gdhs_date"] = pd.to_datetime(d[c_dt], errors="coerce").dt.strftime("%Y-%m-%d").values
    # 筹码派发信号：户数增加 + 股价下跌 = 散户接盘
    out["gdhs_dump"] = np.where((out["gdhs_chg"] > 3) & (out["gdhs_ret"] < 0), 1,
                                np.where((out["gdhs_chg"] > 0) & (out["gdhs_ret"] < 0), 0.5, 0))
    return out[~out.index.duplicated()]


# ---------------------------------------------------------------- P1-3 龙虎榜
def calc_lhb(fcap, Tstr):
    p = DATA / "lhb.parquet"
    if not p.exists():
        return pd.DataFrame(index=fcap.index)
    d = pd.read_parquet(p).copy()
    c_code = col(d, "代码")
    c_net = col(d, "机构买入净额") or col(d, "机构净买额")
    c_tot = col(d, "市场总成交额")
    d["code"] = norm_code(d[c_code])
    out = pd.DataFrame(index=fcap.index)
    g = d.groupby("code")
    out["lhb_n"] = g.size()
    out["lhb_net"] = g[c_net].sum() if c_net else np.nan
    out["lhb_net_ratio"] = out["lhb_net"] / fcap.reindex(out.index) * 100
    if c_tot:
        out["lhb_net_share"] = (g[c_net].sum() / g[c_tot].sum() * 100)
    return out


# ---------------------------------------------------------------- P2-1 公募
def calc_fund(price, fcap):
    """公募基金季报重仓。

    akshare 该接口存在列名错位（代码跑到"简称"列、家数跑到"持股总数"列），
    已用「持股总数 × 现价 ÷ 流通市值」交叉验证：第 6 列 = 占流通股比例(%)，
    与手动计算完全吻合（中际旭创 19.06% vs 19.05%），故按位置取列。
    """
    p = DATA / "fundhold.parquet"
    if not p.exists():
        return pd.DataFrame(index=fcap.index)
    d = pd.read_parquet(p)
    if d.shape[1] < 9:
        return pd.DataFrame(index=fcap.index)
    out = pd.DataFrame({
        "code": norm_code(d.iloc[:, 2]).values,
        "fund_n": num(d.iloc[:, 4]).values,          # 持有基金家数
        "fund_sh": num(d.iloc[:, 5]).values,         # 持股总数(股)
        "fund_pct": num(d.iloc[:, 6]).values,        # 占流通股比例(%)
        "fund_chg": num(d.iloc[:, 8]).values,        # 变动数量(股)
    }).drop_duplicates("code").set_index("code")
    # 交叉校验：用股数×现价/流通市值 复核占比，系统性偏差过大则整表作废
    chk = out["fund_sh"] * price.reindex(out.index) / fcap.reindex(out.index) * 100
    dev = (chk - out["fund_pct"]).abs()
    bad_share = float((dev > 2).sum()) / max(len(dev.dropna()), 1)
    print("   [校验] 公募占比自校验：中位偏差 %.3f%%，超2pp占比 %.1f%%"
          % (float(dev.median()), bad_share * 100))
    if bad_share > 0.2:
        print("   [校验] 偏差过大，公募持仓数据弃用")
        return pd.DataFrame(index=fcap.index)
    return out


# ---------------------------------------------------------------- P2-2 回购
def calc_buyback(price, fcap):
    p = DATA / "buyback.parquet"
    if not p.exists():
        return pd.DataFrame(index=price.index)
    d = pd.read_parquet(p).copy()
    c_code = col(d, "股票代码")
    c_px = col(d, "计划回购价格区间")
    c_hi = col(d, "计划回购金额区间", "上限") or col(d, "金额上限")
    c_lo = col(d, "计划回购金额区间", "下限")
    d["code"] = norm_code(d[c_code])
    out = pd.DataFrame(index=price.index)
    g = d.groupby("code")
    out["bb_px"] = g[c_px].max() if c_px else np.nan
    out["bb_amt_hi"] = g[c_hi].max() if c_hi else np.nan
    out["bb_amt_lo"] = g[c_lo].max() if c_lo else np.nan
    out["bb_ratio"] = out["bb_amt_hi"] / fcap.reindex(out.index) * 100
    # 回购价上限相对现价的溢价：越高说明管理层认为价值越被低估
    out["bb_prem"] = (out["bb_px"] / price.reindex(out.index) - 1) * 100
    return out


# ---------------------------------------------------------------- P2-2 增减持
def calc_holders(price, fcap, Tstr):
    p = DATA / "holders.parquet"
    if not p.exists():
        return pd.DataFrame(index=price.index)
    d = pd.read_parquet(p).copy()
    c_code = col(d, "代码")
    c_dir = col(d, "增减")
    c_qty = col(d, "变动数量")
    c_end = col(d, "变动截止日") or col(d, "公告日")
    d["code"] = norm_code(d[c_code])
    d["qty"] = num(d[c_qty])
    d["sgn"] = np.where(d[c_dir].astype(str).str.contains("增"), 1,
                        np.where(d[c_dir].astype(str).str.contains("减"), -1, 0))
    # 只统计近 120 日公告的变动，避免把历史减持当近期信号
    if c_end:
        dt = pd.to_datetime(d[c_end], errors="coerce")
        T = pd.Timestamp(Tstr)
        d = d[(dt >= T - pd.Timedelta(days=120)) & (dt <= T + pd.Timedelta(days=5))]
    # 变动数量单位为万股：×1e4 还原为股
    d["mv"] = d["sgn"] * d["qty"] * 1e4 * price.reindex(d["code"]).values
    out = pd.DataFrame(index=price.index)
    g = d.groupby("code")
    out["hold_net"] = g["mv"].sum()
    out["hold_ratio"] = out["hold_net"] / fcap.reindex(out.index) * 100
    out["hold_n"] = g.size()
    return out


# ---------------------------------------------------------------- 汇总
def build(price, fcap, Tstr):
    parts = [
        calc_pledge(price, fcap, Tstr),
        calc_unlock(price, fcap, Tstr),
        calc_cb(price, fcap),
        calc_block(fcap, Tstr),
        calc_gdhs(),
        calc_lhb(fcap, Tstr),
        calc_fund(price, fcap),
        calc_buyback(price, fcap),
        calc_holders(price, fcap, Tstr),
    ]
    out = pd.DataFrame(index=price.index)
    for p in parts:
        if p is None or len(p) == 0:
            continue
        add = [c for c in p.columns if c not in out.columns]
        out = out.join(p[add], how="left")
    return out


# ---------------------------------------------------------------- 成本线共振带
def resonance(df):
    """成本线共振带：统计【不同机制】的成本线是否落在同一跌幅窗口内。

    必须按机制去重——融资盘追保线与平仓线是同一批筹码、同一次强平，
    把它们算成两条线会系统性虚增共振数（这两条线几乎永远同时存在）。
    可公开验证的价格触发型机制只有两类：融资盘强平、股权质押强平。
    转债、解禁、强赎属于"事件型"，单独计入 res_ev，不混入价格线计数。
    """
    window = 25.0
    mech = {
        "融资强平": "buf_call",
        "质押强平": "pld_room",
    }
    cnt = np.zeros(len(df))
    lo = np.full(len(df), np.nan)
    hi = np.full(len(df), np.nan)
    detail = []
    for i, (code, r) in enumerate(df.iterrows()):
        hits = []
        for k, c in mech.items():
            if c not in df.columns:
                continue
            v = r.get(c)
            if pd.notna(v) and 0 < v <= window:
                hits.append((k, float(v)))
        cnt[i] = len(hits)
        if hits:
            vals = [h[1] for h in hits]
            lo[i], hi[i] = min(vals), max(vals)
        detail.append("|".join("%s:%.1f" % h for h in hits))
    out = pd.DataFrame({"res_cnt": cnt, "res_lo": lo, "res_hi": hi,
                        "res_detail": detail}, index=df.index)

    # 事件型被动卖出：解禁到期、强赎触发、转债负溢价套利
    ev = np.zeros(len(df))
    tag = [[] for _ in range(len(df))]
    if "ulk60" in df.columns:
        u = df["ulk60"].fillna(0).values
        ev += np.where(u >= 5, 1.5, np.where(u >= 2, 1.0, 0))
        tag = [[*t, "解禁%.0f%%" % v] if v >= 2 else t for t, v in zip(tag, u)]
    if "cb_force_up" in df.columns:
        f = df["cb_force_up"].values
        near = (f > 0) & (f <= 8)
        ev += np.where(near, 1.0, 0)
        tag = [[*t, "近强赎"] if n else t for t, n in zip(tag, near)]
    if "cb_prem" in df.columns:
        p = df["cb_prem"].values
        arb = (p < 0)
        ev += np.where(arb, 0.5, 0)
        tag = [[*t, "转债负溢价"] if n else t for t, n in zip(tag, arb)]
    if "blk_disc" in df.columns and "blk_ratio" in df.columns:
        bd = df["blk_disc"].values
        br = df["blk_ratio"].values
        # 折价 >5% 且成交额占流通市值 >0.5%，视为折价出货
        sell = (bd < -5) & (br > 0.5)
        ev += np.where(sell, 0.5, 0)
        tag = [[*t, "大宗折价"] if n else t for t, n in zip(tag, sell)]

    out["res_ev"] = ev
    out["res_score"] = out["res_cnt"] + out["res_ev"]
    out["res_ev_tag"] = ["|".join(t) for t in tag]
    return out
