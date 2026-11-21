#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两融库：沪深两市融资余额与融资净买入，落 parquet（date, rz_ye, rz_net, net_ratio）。

口径说明：
  · 上交所 stock_margin_sse(start,end) 支持区间，单位「元」，一次可取全历史；
  · 深交所 stock_margin_szse(date) 只支持单日，单位「亿元」，需逐日抓；
  · 融资净买入 = 融资余额(T) - 融资余额(T-1)。交易所不直接披露偿还额，
    余额差是净买入的无偏近似（忽略除权、折算率调整等非交易性变动）。
  · 源站面板的「按指数拆分融资余额」只取每个指数的部分成分股（沪深300 仅 30 只），
    口径不可复现，此处改为全市场汇总，并明确标注。

用法：
    python3 margin.py --backfill 2026-08-01
    python3 margin.py --daily
    python3 margin.py --status
"""
import os
import sys
import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "..", "data", "margin.parquet")
THROTTLE = 0.55


def _load():
    if os.path.exists(STORE):
        df = pd.read_parquet(STORE)
        df["date"] = pd.to_datetime(df["date"])
        return df
    return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"),
                         "sh_ye": pd.Series(dtype="float64"),
                         "sz_ye": pd.Series(dtype="float64")})


def trade_days(start, end):
    import akshare as ak
    cal = ak.tool_trade_date_hist_sina()
    cal["trade_date"] = pd.to_datetime(cal["trade_date"])
    m = (cal["trade_date"] >= pd.Timestamp(start)) & (cal["trade_date"] <= pd.Timestamp(end))
    return [d.date() for d in cal.loc[m, "trade_date"]]


def fetch_sse(start, end):
    import akshare as ak
    df = ak.stock_margin_sse(start_date=start.strftime("%Y%m%d"),
                             end_date=end.strftime("%Y%m%d"))
    df["date"] = pd.to_datetime(df["信用交易日期"].astype(str))
    df["sh_ye"] = pd.to_numeric(df["融资余额"], errors="coerce") / 1e8   # 元 → 亿元
    return df[["date", "sh_ye"]].dropna()


def fetch_szse(day):
    import akshare as ak
    df = ak.stock_margin_szse(date=day.strftime("%Y%m%d"))
    if df is None or df.empty:
        return None
    v = pd.to_numeric(df["融资余额"], errors="coerce").iloc[0]   # 已是亿元
    return {"date": pd.Timestamp(day), "sz_ye": float(v)}


def backfill(start="2026-08-01", end=None):
    import datetime as dt
    end = end or dt.date.today()
    old = _load()
    # 已抓过的判定看 sz_ye 是否非空：日期存在但深市为空的日子仍需重抓
    have = set(old.dropna(subset=["sz_ye"])["date"].dt.date) if not old.empty else set()

    try:
        sh = fetch_sse(pd.Timestamp(start).date(), end)
        print("[margin] 沪市 %d 天" % len(sh))
    except Exception as e:
        sh = pd.DataFrame(columns=["date", "sh_ye"])
        print("[margin] 沪市失败 %s" % repr(e)[:100], file=sys.stderr)

    days = [d for d in trade_days(start, end) if d not in have]
    print("[margin] 深市待抓 %d 天" % len(days))
    rows, t0 = [], time.time()
    for i, d in enumerate(days, 1):
        try:
            r = fetch_szse(d)
            if r:
                rows.append(r)
        except Exception as e:
            print("  %s %s" % (d, repr(e)[:60]), file=sys.stderr)
        if i % 30 == 0:
            print("  %d/%d 用时 %.0fs" % (i, len(days), time.time() - t0))
        time.sleep(THROTTLE)

    sz = pd.DataFrame(rows)
    new = sh.merge(sz, on="date", how="outer") if not sz.empty else sh
    # 合并时优先用新值，新值为空处沿用旧值——否则深市一旦抓取失败会把已有数据覆盖成空
    if not old.empty:
        merged = (new.set_index("date").combine_first(old.set_index("date"))
                  .reset_index())
    else:
        merged = new
    merged = merged.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    merged = merged.reset_index(drop=True)
    merged.to_parquet(STORE, index=False)
    # 只在沪深都有数据的日期上做口径一致的分析
    ok = merged.dropna(subset=["sh_ye", "sz_ye"])
    print("[margin] 库内 %d 行（沪深齐全 %d 行），%s ~ %s"
          % (len(merged), len(ok), merged["date"].min().date(), merged["date"].max().date()))
    status()


def daily():
    import datetime as dt
    today = dt.date.today()
    old = _load()
    last = old["date"].max().date() if not old.empty else today - dt.timedelta(days=10)
    start = last - dt.timedelta(days=1)
    backfill(str(start), today)
    return 0


def status():
    df = _load()
    if df.empty:
        print("[margin] 空库")
        return
    # 不用 fillna(0)：深市缺失日若补齐成 0，合计会腰斩、净买入出现上万亿的假数
    df["total"] = df["sh_ye"] + df["sz_ye"]
    df["net"] = df["total"].diff()
    print("[margin] 汇总（亿元）最近 6 日：")
    print(df[["date", "sh_ye", "sz_ye", "total", "net"]].tail(6).round(1).to_string(index=False))
    print("\n覆盖 %d 天，%s ~ %s"
          % (len(df), df["date"].min().date(), df["date"].max().date()))


def main():
    if "--backfill" in sys.argv:
        i = sys.argv.index("--backfill")
        backfill(sys.argv[i + 1] if len(sys.argv) > i + 1 else "2026-08-01")
    elif "--daily" in sys.argv:
        return daily()
    else:
        status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
