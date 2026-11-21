#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""净流入计算：份额变化 × 单位净值，落 parquet 长表（date, code, flow）。

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


def compute():
    sh, nv, uni = load_inputs()
    dates = sorted(set(sh["date"]) & set(nv["date"]))
    cal = pd.DatetimeIndex(dates)
    print("[flow] 份额 %d 行 / 净值 %d 行 / 交易日 %d（%s ~ %s）"
          % (len(sh), len(nv), len(cal), cal.min().date(), cal.max().date()))

    share = sh.pivot_table(index="date", columns="code", values="shares", aggfunc="last")
    nav = nv.pivot_table(index="date", columns="code", values="nav", aggfunc="last")
    share = share.reindex(cal).ffill()   # 未披露日沿用前值（份额未变 → 零流入）
    nav = nav.reindex(cal).ffill()

    codes = [c for c in share.columns if c in nav.columns]
    share, nav = share[codes], nav[codes]

    d = share.diff()
    flow = (d * nav / 1e8).round(4)      # 亿元
    # 首日无前值 → diff 为 NaN，保留 NaN 而不是填 0：
    # 填 0 会让「只有单个快照的代码」（如刚累积第一天的深市）在首行伪造出一个 0 值，
    # 反而把它真实的日期挤掉。

    long = flow.stack().rename("flow").reset_index()
    long.columns = ["date", "code", "flow"]
    long = long.merge(uni, left_on="code", right_on="基金代码", how="left")
    long[["date", "code", "flow", "cat", "name", "ex"]].to_parquet(FLOW, index=False)

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
