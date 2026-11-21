#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从底层抓取"持仓结构"多类被动卖出机制的原始数据，落盘 parquet 缓存。
覆盖：股权质押、限售解禁、可转债、大宗交易、股东户数、龙虎榜机构席位、
      公募季报持仓、回购、重要股东增减持。
每一类独立 try，单类失败不影响其他类。
"""
import json
import time
import traceback
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd

DATA = __import__("pathlib").Path(__file__).parent / "data"
DATA.mkdir(exist_ok=True)


def log(m):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), m), flush=True)


def save(df, name, tag):
    p = DATA / (name + ".parquet")
    df.to_parquet(p)
    log("%-10s 落盘 shape=%s  %.1f KB" % (name, df.shape, p.stat().st_size / 1024))
    log("           列 = %s" % list(df.columns))
    if len(df):
        log("           样 = %s" % str(df.iloc[0].to_dict())[:400])
    return df


def run(fn, name, interval=None):
    t = time.time()
    try:
        df = fn()
        if df is None or len(df) == 0:
            log("%-10s 空结果" % name)
            return None
        log("%-10s 抓取成功 shape=%s  %.1fs" % (name, df.shape, time.time() - t))
        return save(df, name, interval)
    except Exception:
        log("%-10s 失败" % name)
        if name == "cb":
            log("           已知：ak.bond_cov_comparison 含 '-' 占位符会写 parquet 失败，"
                "由 fetch_fix.py 清洗后重抓，此条可忽略")
        traceback.print_exc()
        return None


def main():
    t0 = time.time()
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    margin = pd.read_parquet(DATA / "margin_hist.parquet")
    T = str(margin["date"].max())
    log("基准日 T = %s" % T)
    Td = datetime.strptime(T, "%Y%m%d")

    # ---------------- P0-1 股权质押（单笔明细，含预估平仓线）
    run(lambda: ak.stock_gpzy_pledge_ratio_detail_em(), "pledge")

    # ---------------- P0-2 限售解禁（往前留一年、往后留半年）
    run(lambda: ak.stock_restricted_release_detail_em(
        start_date=(Td - timedelta(days=365)).strftime("%Y%m%d"),
        end_date=(Td + timedelta(days=180)).strftime("%Y%m%d")), "unlock")

    # ---------------- P0-3 可转债比价
    run(lambda: ak.bond_cov_comparison(), "cb")

    # ---------------- P1-1 大宗交易（近 30 个自然日，逐日拉）
    def _block():
        out = []
        for i in range(30):
            d = (Td - timedelta(days=i)).strftime("%Y%m%d")
            try:
                df = ak.stock_dzjy_mrtj(start_date=d, end_date=d)
                if df is not None and len(df):
                    out.append(df)
            except Exception:
                pass
            time.sleep(0.15)
        return pd.concat(out, ignore_index=True) if out else pd.DataFrame()
    run(_block, "block")

    # ---------------- P1-2 股东户数（最新快照，含上次对比）
    run(lambda: ak.stock_zh_a_gdhs(symbol="最新"), "gdhs")

    # ---------------- P1-3 龙虎榜机构买卖统计（近 40 个自然日）
    run(lambda: ak.stock_lhb_jgmmtj_em(
        start_date=(Td - timedelta(days=40)).strftime("%Y%m%d"),
        end_date=Td.strftime("%Y%m%d")), "lhb")

    # ---------------- P2-1 公募季报持仓（最近一期：2026Q3）
    run(lambda: ak.stock_report_fund_hold(symbol="基金持仓", date="20260930"), "fundhold")

    # ---------------- P2-2 回购
    run(lambda: ak.stock_repurchase_em(), "buyback")

    # ---------------- P2-2 重要股东增减持
    run(lambda: ak.stock_ggcg_em(symbol="全部"), "holders")

    log("全部完成，总耗时 %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
