#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补齐/修复：可转债比价、交易所周度质押比例、机构持股一览、十大流通股东集中度。
akshare 部分接口返回 object 列含 '-' 占位符，落盘前统一清洗。"""
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd

DATA = Path(__file__).parent / "data"


def log(m):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), m), flush=True)


def clean(df):
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object:
            t = pd.to_numeric(df[c], errors="coerce")
            if t.notna().mean() > 0.8:
                df[c] = t
            else:
                df[c] = df[c].astype(str)
    return df


def save(df, name):
    df = clean(df)
    p = DATA / (name + ".parquet")
    df.to_parquet(p)
    log("%-14s shape=%s  %.0f KB" % (name, df.shape, p.stat().st_size / 1024))
    log("               列 = %s" % list(df.columns))
    if len(df):
        log("               样 = %s" % str(df.iloc[0].to_dict())[:300])


def main():
    # 1) 可转债比价
    try:
        save(ak.bond_cov_comparison(), "cb")
    except Exception:
        log("cb 失败"); traceback.print_exc()

    # 2) 交易所周度质押比例（回溯找最近一个有数据的快照日）
    T = pd.read_parquet(DATA / "margin_hist.parquet")["date"].max()
    Td = datetime.strptime(str(T), "%Y%m%d")
    ok = False
    for i in range(1, 16):
        d = (Td - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = ak.stock_gpzy_pledge_ratio_em(date=d)
            if df is not None and len(df) > 100:
                save(df, "pledge_ratio")
                log("质押比例快照日 = %s（距今 %d 天）" % (d, i))
                ok = True
                break
        except Exception:
            pass
    if not ok:
        log("质押比例快照 未取到")

    # 3) 机构持股一览（2026 三季报）
    try:
        save(ak.stock_institute_hold(symbol="20263"), "institute")
    except Exception:
        log("institute 失败"); traceback.print_exc()

    # 4) 十大流通股东持股统计（集中度）
    try:
        save(ak.stock_gdfx_free_holding_statistics_em(date="20260930"), "top10free")
    except Exception:
        log("top10free 失败"); traceback.print_exc()


if __name__ == "__main__":
    main()
