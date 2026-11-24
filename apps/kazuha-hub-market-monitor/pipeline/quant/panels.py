# -*- coding: utf-8 -*-
"""量化状态作业的行情宽表读取（build_quant.py 用，单独成文件以便测试）。"""
import market_data as md


def load_panels(start="2014-06-01"):
    """收盘价与成交额宽表（date × code，float32）：只保留有成交（volume>0）的
    bar，剔除北交所（8/4/92 开头），去掉一根有成交 bar 都没有的日期与代码——
    与原生成器 md.load → volume>0 → pivot_table → astype(float32) 的结果一致，
    但不建全库长表（2 GiB 容器里放不下）。"""
    close = md.panel("close", start=start, dtype="float32")
    traded = md.panel("volume", start=start, dtype="float32").reindex_like(close) > 0
    keep = ~close.columns.astype(str).str.startswith(("8", "4", "92"))
    close, traded = close.loc[:, keep], traded.loc[:, keep]
    rows, cols = traded.any(axis=1), traded.any(axis=0)
    traded = traded.loc[rows, cols]
    close = close.loc[rows, cols].where(traded)
    amount = md.panel("amount", start=start, dtype="float32").reindex_like(close).where(traded)
    return close.sort_index(), amount.sort_index()
