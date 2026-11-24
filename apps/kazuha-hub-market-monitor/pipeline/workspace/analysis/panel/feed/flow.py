#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""净流入计算：份额变化 × 单位净值，落 parquet 长表（date, code, flow, span）。

口径（与交易所披露一致，已用 510300 在 2026-11-12 验证）：
    净流入(T) = [份额(T) - 份额(T-1)] × 单位净值(T)
  · 份额来自交易所披露（沪 T+1 可取，深为快照累积）；
  · 净值来自天天基金 f10/lsjz 单位净值；
  · 510300 11-12：份额 -2.871 亿份 × 净值 4.1203 = -11.83 亿，与源站完全一致。

用法：
    python3 flow.py            # 全量重算
    python3 flow.py --status
"""
import os
import sys
import json

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
UNIV = os.path.join(HERE, "universe.csv")
FLOW = os.path.join(DATA, "flow.parquet")
BYCAT = os.path.join(DATA, "flow_bycat.parquet")
VERIFY = os.path.join(DATA, "verify_flow.json")

# 源站面板沿用的 20 只重点 ETF（保留该口径用于与外部分析对照）
CORE20 = ["510310", "588000", "159915", "510300", "563360", "159352", "512100",
          "159338", "510500", "159949", "588080", "510050", "510210", "159845",
          "159952", "159361", "512050", "159633", "560010", "159919"]

CATS = ["沪深300", "中证A500", "中证500", "中证1000", "中证2000", "科创50",
        "创业板指", "上证50", "创业板50", "双创50", "国证2000", "其他宽基"]


def load_inputs():
    sh = pd.read_parquet(os.path.join(DATA, "shares.parquet"))
    nv = pd.read_parquet(os.path.join(DATA, "nav.parquet"))
    u = pd.read_csv(UNIV, dtype={"基金代码": str})
    u = u[u["cat"] != "非宽基"][["基金代码", "cat", "name", "ex"]]
    for d in (sh, nv):
        d["date"] = pd.to_datetime(d["date"])
        d["code"] = d["code"].astype(str)
    return sh, nv, u


def trading_calendar(nv):
    """交易日历：上证指数日线的日期（只含交易日，不受份额缺口影响）；指数还没
    到的最新几天用净值日期补上。净值不单独做日历：个别基金会在非交易日
    （半年末、年末）公布净值，混进来会让跨过它的变化都变成合并值。"""
    nav_days = pd.DatetimeIndex(sorted(set(pd.to_datetime(nv["date"]))))
    idx = os.path.join(DATA, "index.parquet")
    if not os.path.exists(idx):
        return nav_days
    days = pd.DatetimeIndex(sorted(set(pd.to_datetime(pd.read_parquet(idx, columns=["date"])["date"]))))
    if len(days):
        days = days.append(nav_days[nav_days > days.max()])
    return days


def compute_flows(sh, nv, cal):
    """逐只按「相邻两次份额观测」算净流入，并记下这段变化跨了几个交易日。

    净流入(t) = [份额(t) − 份额(上次观测)] × 净值(t)。
    span = 上次观测到 t 之间的交易日数（含 t）：1 是真正的单日；>1 是合并值——
    中间的日子没有份额（应用没跑、源站没披露、深市只有快照），这段变化只能整体
    记在 t 上，不能当成 t 一天的流入。没有观测的日子不填 0、不补值。
    返回长表 (date, code, flow 亿元, span)。
    """
    pos = pd.Series(range(len(cal)), index=cal)
    nav = nv.pivot_table(index="date", columns="code", values="nav", aggfunc="last")
    nav = nav.reindex(cal).ffill()
    rows = []
    for code, g in sh.sort_values("date").groupby("code"):
        if code not in nav.columns:
            continue
        g = g.drop_duplicates("date", keep="last")
        g = g[g["date"].isin(cal)]
        if len(g) < 2:
            continue
        d = g["date"].to_numpy()
        p = pos.reindex(g["date"]).to_numpy()
        diff = g["shares"].diff().to_numpy()[1:]
        span = (p[1:] - p[:-1]).astype(int)
        price = nav[code].reindex(g["date"]).to_numpy()[1:]
        rows.append(pd.DataFrame({"date": d[1:], "code": code,
                                  "flow": (diff * price / 1e8).round(4), "span": span}))
    if not rows:
        return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "code": [], "flow": [], "span": []})
    return pd.concat(rows, ignore_index=True)


def compute():
    sh, nv, uni = load_inputs()
    cal = trading_calendar(nv)
    cal = cal[cal >= sh["date"].min()]
    print("[flow] 份额 %d 行 / 净值 %d 行 / 交易日 %d（%s ~ %s）"
          % (len(sh), len(nv), len(cal), cal.min().date(), cal.max().date()))

    long = compute_flows(sh, nv, cal)
    merged = long[long["span"] > 1]
    if len(merged):
        print("[flow] 合并值 %d 条（中间缺份额，跨 2~%d 个交易日），不计入单日统计"
              % (len(merged), int(merged["span"].max())))
    long = long.merge(uni, left_on="code", right_on="基金代码", how="left")
    long[["date", "code", "flow", "span", "cat", "name", "ex"]].to_parquet(FLOW, index=False)

    # 分类合计是按日相加的，窗口求和（近 20 日、年初至今）依然精确
    flow = long.pivot_table(index="date", columns="code", values="flow", aggfunc="sum")
    codes = list(flow.columns)
    bycat = flow.T.groupby(uni.set_index("基金代码").loc[codes, "cat"]).sum().T
    bycat = bycat.reindex(columns=[c for c in CATS if c in bycat.columns])
    bycat.index.name = "date"
    bycat.to_parquet(BYCAT)

    print("[flow] 明细 %d 行 → %s" % (len(long), os.path.basename(FLOW)))
    print("[flow] 分类 %s" % os.path.basename(BYCAT))
    print(bycat.tail(5).round(1).to_string())
    return flow, bycat


def verify():
    """与源站 histData 逐日比对（沪市标的应有极高吻合度）。"""
    snap_path = os.path.join(DATA, "latest.json")
    flow_p = pd.read_parquet(FLOW)
    out = {"anchor": "510300 2026-11-12 份额变化 × 净值 vs 源站净流入", "items": []}

    if not os.path.exists(snap_path):
        print("[verify] 无 latest.json，跳过源站比对")
        return out
    snap = json.load(open(snap_path, encoding="utf-8")).get("snapshot") or {}
    h = snap.get("histData") or {}
    if not h.get("cum"):
        return out
    src = pd.DataFrame(h["cum"], index=pd.to_datetime(h["dates"])).diff()

    pivot = flow_p.pivot_table(index="date", columns="code", values="flow")
    for c in CORE20:
        if c not in pivot.columns or c not in src.columns:
            continue
        a = pivot[c].reindex(src.index)
        b = src[c]
        m = a.notna() & b.notna() & (b.abs() > 0.5)   # 只比有意义的日
        if m.sum() < 5:
            continue
        diff = (a[m] - b[m])
        out["items"].append({
            "code": c, "n": int(m.sum()),
            "corr": round(float(a[m].corr(b[m])), 4),
            "mae": round(float(diff.abs().mean()), 3),
            "bias": round(float(diff.mean()), 3),
        })
    if out["items"]:
        df = pd.DataFrame(out["items"]).sort_values("mae")
        print("[verify] 与源站比对（%d 只，仅取源站非零日）：" % len(df))
        print(df.to_string(index=False))
        out["summary"] = {
            "n_codes": len(df),
            "median_corr": round(float(df["corr"].median()), 4),
            "median_mae": round(float(df["mae"].median()), 3),
        }
    json.dump(out, open(VERIFY, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return out


def status():
    if not os.path.exists(FLOW):
        print("[flow] 未生成")
        return
    df = pd.read_parquet(FLOW)
    print("[flow] %d 行 / %d 只 / %s ~ %s"
          % (len(df), df["code"].nunique(), df["date"].min().date(), df["date"].max().date()))
    b = pd.read_parquet(BYCAT)
    print("\n最近 5 日分类（亿元）：")
    print(b.tail(5).round(1).to_string())


def main():
    if "--status" in sys.argv:
        status()
        return 0
    compute()
    verify()
    return 0


if __name__ == "__main__":
    sys.exit(main())
