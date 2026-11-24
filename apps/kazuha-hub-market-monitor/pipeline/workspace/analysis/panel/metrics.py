#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指标层（自建数据源版）：把份额/净值/成交额/两融算成面板指标，输出 data/metrics.json。

数据来源全部自建，不依赖任何第三方看板：
  · 净流入 = 份额变化 × 单位净值，份额来自交易所披露（沪 T+1 可取），净值来自天天基金；
  · 成交额来自腾讯日线；两融来自沪深交易所；指数来自新浪。
  · 口径已验证：沪市 11 只核心 ETF 与外部 Choice 口径相关系数 1.0000、MAE 0.002~0.003 亿元。

覆盖范围与已知限制：
  · 沪市 117 只宽基 ETF，2024-01-02 起完整历史；
  · 深市份额交易所不提供历史回溯（fund_etf_scale_szse 只返回最新快照），只能逐日累积，
    因此分类中「创业板指 / 创业板50 / 国证2000」在深市数据累积够之前为空。

口径约定：
  · 事件 = 沪市宽基合计单日净流入 > 100 亿元（占样本 8.2%，接近上十分位）
  · 执行 = T+1 开盘买入，持有 h 日到 T+h 收盘
  · 基准 = 同期全样本同持有期均值；超额 = 事件均值 − 基准
  · 显著性 = 事件按 20 日间隔聚簇后的簇级 t（避免把同一波买盘当独立样本）
"""
import os
import json

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

THRESH = 100.0          # 事件阈值（亿元）
CLUSTER_GAP = 20        # 聚簇间隔（交易日）
ROLL_WIN = 120          # 滚动回归窗口

# 面板配色：与 build.py 的 CAT_COLORS 对齐
CAT_COLORS = {
    "沪深300": "#c0392b", "中证A500": "#e67e22", "中证500": "#d4ac0d",
    "中证1000": "#27ae60", "中证2000": "#16a085", "科创50": "#2980b9",
    "创业板指": "#8e44ad", "上证50": "#34495e", "创业板50": "#c2185b",
    "双创50": "#00838f", "国证2000": "#6d4c41", "其他宽基": "#7f8c8d",
}


def load():
    flow = pd.read_parquet(os.path.join(DATA, "flow.parquet"))
    bycat = pd.read_parquet(os.path.join(DATA, "flow_bycat.parquet"))
    amt = pd.read_parquet(os.path.join(DATA, "amount.parquet"))
    px = pd.read_parquet(os.path.join(DATA, "index.parquet"))
    mg = pd.read_parquet(os.path.join(DATA, "margin.parquet"))

    for d in (flow, amt, px, mg):
        d["date"] = pd.to_datetime(d["date"])
    flow["code"] = flow["code"].astype(str)
    amt["code"] = amt["code"].astype(str)

    sh = set(flow.loc[flow["ex"] == "SH", "code"])
    nf, span = sse_daily(flow[flow["code"].isin(sh)])
    amt_s = amt[amt["code"].isin(sh)].groupby("date")["amount"].sum()

    px = px.set_index("date").sort_index()
    md = mg.set_index("date").sort_index()

    # 交易日以指数与成交额为准，从份额有数据的第一天起：份额缺口的日子留在序列里
    # （值为空），而不是被跳过——跳过会让「近 5 日」「连续 N 日」数错天数。
    dates = px.index.intersection(amt_s.index)
    dates = dates[dates >= nf.index.min()].sort_values() if len(nf) else dates.sort_values()
    return (flow, bycat, nf.reindex(dates), span.reindex(dates), amt_s.reindex(dates),
            px.loc[dates], md, dates)


def sse_daily(sse_flow):
    """沪市宽基逐日合计与该日的跨度：某天只要有一只的变化跨了多个交易日
    （中间缺份额），这天的合计就是合并值，span 取最大跨度。"""
    if "span" not in sse_flow.columns:          # 旧版 flow.parquet：全当单日
        sse_flow = sse_flow.assign(span=1)
    g = sse_flow.groupby("date")
    return g["flow"].sum(), g["span"].max()


def num(x, nd):
    """JSON 里的数：非有限值写 null（NaN 不是合法 JSON）。"""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if np.isfinite(x) else None


def cluster_t(vals, positions, base, gap=CLUSTER_GAP):
    """返回 (相对 0 的 t, 相对基准的 t, 簇数)。

    两者必须分开：事件均值相对 0 显著，不代表超额相对基准显著。基准本身可能远离 0
    （例如 2026 年 5 日基准为负），此时「事件均值不显著异于 0」恰恰意味着「显著跑赢基准」。
    只看前者会把结论讲反。
    """
    groups, last = [], -10 ** 9
    for v, p in sorted(zip(vals, positions), key=lambda x: x[1]):
        if p - last >= gap:
            groups.append([])
            last = p
        groups[-1].append(v)
    m = np.array([np.mean(g) for g in groups if len(g)])
    if len(m) < 3:
        return np.nan, np.nan, len(m)
    se = m.std(ddof=1) / np.sqrt(len(m))
    if not se:
        return np.nan, np.nan, len(m)
    return m.mean() / se, (m.mean() - base) / se, len(m)


def fwd(px, h):
    return (px["close"].shift(-h) / px["open"].shift(-1) - 1) * 100


def event_stats(px, mask, h, gap=CLUSTER_GAP):
    r = fwd(px, h)
    ev = r[mask].dropna()
    if len(ev) < 3:
        return None
    pos = [px.index.get_loc(d) for d in ev.index]
    base = r.dropna()
    b = float(base.mean())
    t0, tex, k = cluster_t(ev.values, pos, b, gap)
    return {"n": int(len(ev)), "clusters": int(k),
            "mean": round(float(ev.mean()), 2),
            "win": round(float((ev > 0).mean() * 100), 0),
            "base": round(b, 2),
            "excess": round(float(ev.mean() - b), 2),
            "t": round(float(t0), 2) if np.isfinite(t0) else None,
            "t_excess": round(float(tex), 2) if np.isfinite(tex) else None}


def main():
    flow, bycat, nf_all, span, amt, px, md, dates = load()
    ret = px["close"].pct_change() * 100
    # 单日口径只用真正的单日：合并值（span>1）和缺口日（空）不进事件、β、游程、
    # 阈值与分位统计；窗口求和（近 5/20/60 日、年初至今）用 nf_all，依然精确。
    merged = span.fillna(1) > 1
    nf = nf_all.where(~merged)

    M = {"asof": str(dates[-1].date()),
         "built_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
         "n_days": int(len(dates)),
         "scope": {"universe": "沪市宽基 ETF", "n_codes": int(flow["code"].nunique()),
                   "start": str(dates[0].date()),
                   "note": "逐日净流入只含沪市：深市份额交易所不提供历史回溯，只有逐日快照，"
                           "缺快照的日子无法补齐，深市只计入分类与单只的窗口合计",
                   "merged_days": int(merged.sum())},
         "thresh": THRESH}

    # ---------- 1. 年度信号体检 ----------
    yrs = {"2024": ("2024-01-01", "2024-12-31"), "2025": ("2025-01-01", "2025-12-31"),
           "2026": ("2026-01-01", "2026-12-31"), "全样本": ("2000-01-01", "2100-01-01")}
    sig = nf > THRESH
    yearly = []
    for lab, (a, b) in yrs.items():
        sl = slice(a, b)
        row = {"year": lab}
        for h in (5, 20):
            row["h%d" % h] = event_stats(px.loc[sl], sig.loc[sl], h)
        yearly.append(row)
    M["yearly"] = yearly

    # 逐年 β（净流入 ~ 当日涨跌）
    beta = []
    for y in ("2024", "2025", "2026"):
        sl = slice(y + "-01-01", y + "-12-31")
        x, yv = ret[sl], nf[sl]
        ok = x.notna() & yv.notna()
        x, yv = x[ok], yv[ok]
        if len(x) < 30:
            continue
        b1 = np.polyfit(x, yv, 1)[0]
        r = np.corrcoef(x, yv)[0, 1]
        beta.append({"year": y, "beta_same_day": round(float(b1), 1),
                     "corr_same_day": round(float(r), 3), "n": int(len(x))})
    M["beta_year"] = beta

    # 滚动 β
    roll_beta, roll_corr = [], []
    x_all, y_all = ret.values, nf.values
    for i in range(len(nf)):
        if i < ROLL_WIN:
            roll_beta.append(None)
            roll_corr.append(None)
            continue
        xs, ys = x_all[i - ROLL_WIN + 1:i + 1], y_all[i - ROLL_WIN + 1:i + 1]
        ok = np.isfinite(xs) & np.isfinite(ys)
        if ok.sum() < 60:
            roll_beta.append(None)
            roll_corr.append(None)
            continue
        roll_beta.append(round(float(np.polyfit(xs[ok], ys[ok], 1)[0]), 1))
        roll_corr.append(round(float(np.corrcoef(xs[ok], ys[ok])[0, 1]), 3))
    M["roll"] = {"dates": [str(d.date()) for d in nf.index],
                 "beta": roll_beta, "corr": roll_corr, "win": ROLL_WIN}

    # ---------- 2. 净流出侧 ----------
    M["outflow"] = {}
    for thr in (-200, -100):
        st = event_stats(px, nf < thr, 20)
        if st:
            M["outflow"][str(thr)] = st

    # ---------- 3. 连续流入游程 ----------
    pos = (nf > 0).astype(int)
    grp = (pos != pos.shift()).cumsum()
    runs = []
    for g, sub in nf.groupby(grp):
        if len(sub) >= 5 and (sub > 0).all():
            runs.append({"start": str(sub.index[0].date()), "end": str(sub.index[-1].date()),
                         "days": int(len(sub)), "sum": round(float(sub.sum()), 0)})
    runs.sort(key=lambda r: r["days"], reverse=True)
    M["runs_top"] = runs[:5]

    # 给页面用的动态叙事：最长游程、2026 年最长游程、各自的指数涨跌
    def _seg_pct(r):
        s = px.loc[r["start"]:r["end"], "close"]
        return round(float(s.iloc[-1] / s.iloc[0] - 1) * 100, 2) if len(s) >= 2 else None

    narr = {}
    if runs:
        longest = dict(runs[0])
        longest["idx_pct"] = _seg_pct(longest)
        narr["longest"] = longest
        r26 = [r for r in runs if str(r["start"]).startswith("2026")]
        if r26:
            d = dict(r26[0])
            d["idx_pct"] = _seg_pct(d)
            narr["run2026"] = d
    corrs = {b["year"]: b["corr_same_day"] for b in beta}
    narr["corr24"], narr["corr26"] = corrs.get("2024"), corrs.get("2026")
    M["narrative"] = narr
    neg = (nf < 0).astype(int)
    neg_run = neg.groupby((neg != neg.shift()).cumsum()).cumsum().iloc[-1]
    M["current"] = {"streak_pos": int(pos.groupby((pos != pos.shift()).cumsum()).cumsum().iloc[-1]),
                    "streak_neg": int(neg_run),
                    "last_nf": num(nf.iloc[-1], 1),
                    "last_date": str(nf.index[-1].date()),
                    # 最新一天若是合并值：单日数不成立，给出合并值与跨度，页面照实写
                    "last_span": int(span.fillna(1).iloc[-1]),
                    "last_merged": num(nf_all.iloc[-1], 1) if merged.iloc[-1] else None,
                    "last5": round(float(nf_all.iloc[-5:].sum()), 0),
                    "last20": round(float(nf_all.iloc[-20:].sum()), 0),
                    "last60": round(float(nf_all.iloc[-60:].sum()), 0),
                    "ytd": round(float(nf_all[nf_all.index >= "2026-01-01"].sum()), 0),
                    "amount_last": round(float(amt.iloc[-1]), 0),
                    "idx_last": round(float(px["close"].iloc[-1]), 2),
                    "idx_20d": round(float(px["close"].iloc[-1] / px["close"].iloc[-21] - 1) * 100, 2)}

    # ---------- 4. 状态灯 ----------
    b_now = [x for x in roll_beta if x is not None][-1]
    st5 = event_stats(px.iloc[-ROLL_WIN:], sig.iloc[-ROLL_WIN:], 5)
    ex5 = st5["excess"] if st5 else None
    t5 = st5["t_excess"] if st5 else None
    s1 = 2 if (b_now or 0) > 0 else -2
    # 超额分项要能双向计分，才是界面写的「±1」；显著性口径用「相对基准」的 t
    if (ex5 or 0) > 0.5 and (t5 or 0) > 1.5:
        s2 = 1
    elif (ex5 or 0) < -0.5 and (t5 or 0) < -1.5:
        s2 = -1
    else:
        s2 = 0
    s3 = 1 if nf_all.iloc[-5:].sum() > 0 else -1
    score = s1 + s2 + s3
    light, label = ("green", "可用") if score >= 2 else (("amber", "观察") if score >= 0 else ("red", "失效"))
    M["health"] = {
        "light": light, "label": label, "score": score, "items": [
            {"k": "钱的性质", "v": "β=%s" % b_now,
             "note": "净流入与当日涨跌的 %d 日回归斜率。>0 是涨了才买（助推），<0 是跌了才买（接刀）" % ROLL_WIN,
             "s": s1},
            {"k": "事件超额", "v": "5日 %+.2fpp" % (ex5 or 0),
             "note": "近 %d 日 >%d 亿事件后 5 日超额，t(超额)=%s，n=%s"
                     % (ROLL_WIN, THRESH, t5, st5["n"] if st5 else 0),
             "s": s2},
            {"k": "买盘在否", "v": "近5日 %+.0f 亿" % nf_all.iloc[-5:].sum(),
             "note": "最近 5 个交易日沪市宽基合计净流入", "s": s3}],
        "beta120": b_now, "excess5_120d": ex5, "t_excess5_120d": t5,
        "n_120d": st5["n"] if st5 else 0}

    # ---------- 4b. 阈值时效性：100 亿在 2026 年还管用吗 ----------
    # 固定阈值的问题：净流入波动放大后，同一个 100 亿在 2024 是极端事件、在 2026 只是普通一天。
    # 用「|净流入| 中位数」做尺度基准，倍数掉到 1.5 附近就说明阈值已经退化成分位线。
    diag = []
    for y in ("2024", "2025", "2026"):
        s = nf[nf.index.year == int(y)].dropna()
        if len(s) < 30:
            continue
        med = float(s.abs().median())
        diag.append({"year": y, "n": int(len(s)),
                     "abs_median": round(med, 1),
                     "mult": round(THRESH / med, 2) if med else None,
                     "trig": round(float((s > THRESH).mean() * 100), 1),
                     "q90": round(float(s.quantile(0.90)), 1)})
    M["thresh_diag"] = diag

    # 阈值敏感性：换阈值后结论是否还成立。如果只有 100 亿失效、提高阈值就恢复，
    # 那「信号失效」是选阈值选出来的假象；如果各档都失效，才是结构性的。
    ths = [100, 150, 200, 250]
    sens = {"thresholds": ths, "rows": [], "rolling": []}
    for y in ("2024", "2025", "2026"):
        sl = slice(y + "-01-01", y + "-12-31")
        row = {"year": y, "cells": []}
        for t in ths:
            st = event_stats(px.loc[sl], (nf > t).loc[sl], 5)
            row["cells"].append({"t": t,
                                 "excess": st["excess"] if st else None,
                                 "n": st["n"] if st else 0})
        sens["rows"].append(row)
    # 滚动 90 分位阈值：实盘唯一可用的口径（事前不知道当年分布）
    roll_thr = nf.rolling(250, min_periods=120).quantile(0.90)
    rsig = nf > roll_thr
    for y in ("2025", "2026"):
        sl = slice(y + "-01-01", y + "-12-31")
        st = event_stats(px.loc[sl], rsig.loc[sl], 5)
        if st:
            sens["rolling"].append({"year": y, "excess": st["excess"], "n": st["n"]})
    M["thresh_sens"] = sens

    # ---------- 4c. 成交额能代理什么：区分「事件强度」与「方向」 ----------
    # corr_signed ~ 0 或为负 = 成交额判断不了申购还是赎回；
    # corr_abs 高 = 成交额能判断今天有没有大事。两者必须分开看。
    ad = []
    for y in ("2024", "2025", "2026"):
        sl = slice(y + "-01-01", y + "-12-31")
        a, f = amt.loc[sl], nf.loc[sl]
        ok = a.notna() & f.notna()
        a, f = a[ok], f[ok]
        if len(a) < 60:
            continue
        hi = f[a >= a.quantile(0.90)]
        ad.append({"year": y, "n": int(len(a)),
                   "corr_signed": round(float(np.corrcoef(a, f)[0, 1]), 3),
                   "corr_abs": round(float(np.corrcoef(a, f.abs())[0, 1]), 3),
                   "hi_n": int(len(hi)),
                   "hi_up": round(float((hi > THRESH).mean() * 100), 0)})
    proxy = []
    for t in (500, 600, 700):
        pred, act = amt > t, nf > THRESH
        ok = pred.notna() & act.notna()
        tp = int((pred & act)[ok].sum()); fp = int((pred & ~act)[ok].sum())
        fn = int((~pred & act)[ok].sum())
        proxy.append({"amt": t,
                      "prec": round(tp / (tp + fp) * 100, 0) if tp + fp else 0,
                      "rec": round(tp / (tp + fn) * 100, 0) if tp + fn else 0})
    M["amt_diag"] = {"byyear": ad, "proxy": proxy}

    # ---------- 5. 序列 ----------
    M["series"] = {
        "dates": [str(d.date()) for d in nf.index],
        # nf 含合并值（画成另一种柱），nf_span 是它跨的交易日数；缺口日为 null
        "nf": [num(x, 1) for x in nf_all],
        "nf_span": [int(x) if np.isfinite(x) else None for x in span.astype(float)],
        "amt": [num(x, 1) for x in amt],
        "idx": [num(x, 2) for x in px["close"]],
        "ret": [None if not np.isfinite(x) else round(float(x), 2) for x in ret],
        "amt_ma20": [None if not np.isfinite(x) else round(float(x), 1)
                     for x in amt.rolling(20).mean()],
        "nf_ma20": [None if not np.isfinite(x) else round(float(x), 1)
                    for x in nf.rolling(20, min_periods=15).mean()],
    }

    # ---------- 6. 分类资金 ----------
    bycat = bycat.reindex(nf.index)
    keep = [c for c in bycat.columns if bycat[c].abs().sum() > 0.5]
    M["broad"] = {
        "dates": [str(d.date()) for d in bycat.index],
        "cats": keep,
        "colors": {c: CAT_COLORS.get(c, "#888") for c in keep},
        "series": {c: [num(x, 1) for x in bycat[c]] for c in keep},
        "total": [num(x, 1) for x in bycat[keep].sum(axis=1)],
        "cum": [num(x, 0) for x in bycat[keep].sum(axis=1).cumsum()],
        "cats_empty": [c for c in CAT_COLORS if c not in keep],
    }

    # ---------- 7. 两融（全市场） ----------
    if not md.empty:
        md = md.reindex(nf.index)          # 不 ffill：两融库只有近段数据，前面就是空
        tot = (md["sh_ye"] + md["sz_ye"]).dropna()
        M["margin"] = {
            "dates": [str(d.date()) for d in tot.index],
            "cats": ["全市场"],
            "rzye": {"全市场": [round(float(x), 1) for x in tot]},
            # diff 少一个点，前面补 None 保持与 dates 等长，否则柱状图会整体左移一天
            "rzjme": {"全市场": [None] + [round(float(x), 1) for x in tot.diff().dropna()]},
            "meta": {"全市场": {"n": 2, "rzyeLast": round(float(tot.iloc[-1]), 1),
                              "rzjmeLast": round(float(tot.diff().dropna().iloc[-1]), 2)}},
            "note": "沪深两市融资余额合计；净买入 = 余额日差（交易所不直接披露偿还额）"}
    else:
        M["margin"] = {"dates": [], "cats": [], "rzye": {}, "rzjme": {}, "meta": {}}

    # ---------- 8. 单只明细 ----------
    piv = flow.pivot_table(index="date", columns="code", values="flow", aggfunc="sum")
    piv = piv.reindex(nf.index)
    names = flow.drop_duplicates("code").set_index("code")[["name", "cat"]]
    ytd = piv[piv.index >= "2026-01-01"].sum()
    last20 = piv.tail(20).sum()
    funds = []
    for c in piv.columns:
        info = names.loc[c] if c in names.index else {"name": c, "cat": ""}
        funds.append({"code": c, "name": str(info["name"]), "cat": str(info["cat"]),
                      "cum_ytd": round(float(ytd.get(c, 0)), 1),
                      "cum20": round(float(last20.get(c, 0)), 1)})
    funds.sort(key=lambda x: -x["cum_ytd"])
    M["funds"] = funds

    # 前 5 大累计路径（年初起）
    top5 = [f["code"] for f in funds[:5]]
    cump = piv[top5][piv.index >= "2026-01-01"].cumsum()
    M["cum_dates"] = [str(d.date()) for d in cump.index]
    M["cum_series"] = {c: [round(float(x), 1) for x in cump[c]] for c in top5}
    M["cum_names"] = {c: str(names.loc[c, "name"]) if c in names.index else c for c in top5}
    M["cum_from"] = "2026-01-01"

    # ---------- 9. 数据状态 ----------
    M["data_health"] = {
        "share_last": str(pd.read_parquet(os.path.join(DATA, "shares.parquet"))["date"].max().date()),
        "nav_last": str(pd.to_datetime(
            pd.read_parquet(os.path.join(DATA, "nav.parquet"))["date"]).max().date()),
        "amount_last": str(pd.read_parquet(os.path.join(DATA, "amount.parquet"))["date"].max().date()),
        "index_last": str(px.index[-1].date()),
        # 沪深两市都到齐才算数：只有沪市的日子是深市尚未披露的过渡行，不能计入新鲜度
        "margin_last": str(md.dropna(subset=["sh_ye", "sz_ye"]).index.max().date())
                       if md.dropna(subset=["sh_ye", "sz_ye"]).shape[0] else "—",
    }

    json.dump(M, open(os.path.join(DATA, "metrics.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    print("[metrics] asof=%s days=%d codes=%d" % (M["asof"], M["n_days"], M["scope"]["n_codes"]))
    print("  状态灯 %s(%s) score=%s β120=%s" % (label, light, score, b_now))
    for r in yearly:
        h5, h20 = r["h5"], r["h20"]
        f = lambda x: ("n=%s 均值%+.2f%% 超额%+.2fpp t=%s" % (x["n"], x["mean"], x["excess"], x["t"])) if x else "—"
        print("  %-4s 5日 %s | 20日 %s" % (r["year"], f(h5), f(h20)))
    print("  逐年β:", beta)
    print("  当前:", M["current"])
    print("  分类有效:", keep, "空:", M["broad"]["cats_empty"])
    print("  数据:", M["data_health"])


if __name__ == "__main__":
    main()
