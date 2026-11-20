#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指数库：上证综指日线，落 parquet（date, open, close, high, low）。

主源用新浪（ak.stock_zh_index_daily，一次返回全历史，稳定）；
腾讯 fqkline 在批量抓取后会被 WAF 拦（HTTP 501），不再作为主源。

事件研究需要 T+1 开盘价，故保留 open。
"""
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "..", "data", "index.parquet")


def fetch_sina(symbol="sh000001"):
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol=symbol)
    df = df[["date", "open", "high", "low", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    return df


def update():
    df = fetch_sina()
    if df.empty:
        print("[index] 抓取失败", file=sys.stderr)
        return 1
    df = df.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    df = df[df["date"] >= pd.Timestamp("2024-01-01")]
    df.to_parquet(STORE, index=False)
    print("[index] %d 行，%s ~ %s，最新收 %.2f"
          % (len(df), df["date"].min().date(), df["date"].max().date(), df["close"].iloc[-1]))
    return 0


if __name__ == "__main__":
    sys.exit(update())
