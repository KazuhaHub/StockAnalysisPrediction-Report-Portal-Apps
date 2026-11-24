"""Price panels and price-derived screener features.

The bar store keeps back-adjusted (hfq) OHLC plus the cumulative adjustment
factor, so the traded price is ``close / factor``. Two panels follow from that:

* ``real``: traded prices. Use them only where a price level meets a per-share
  accounting figure (PE, PB, dividend yield) or a share count (turnover).
* ``adj``: back-adjusted closes. Use them for anything measured over time
  (returns, momentum, moving averages, highs, volatility, beta). A dividend or
  bonus issue changes the traded price without changing the holder's wealth,
  so traded prices would book every ex-date as a loss.
"""
import numpy as np
import pandas as pd


def price_panels(bars: pd.DataFrame):
    """Return ``(real, adj)`` wide panels (date x code) from long bars.

    Bars with zero volume are suspension placeholders and are dropped, as the
    original pipeline did.
    """
    b = bars[bars["volume"] > 0].copy()
    b["date"] = pd.to_datetime(b["date"])
    b["real"] = b["close"] / b["factor"]
    real = b.pivot(index="date", columns="code", values="real").sort_index()
    adj = b.pivot(index="date", columns="code", values="close").sort_index()
    return real, adj


def store_panels(md, codes, start, end):
    """``(real, adj, amount)`` wide panels read straight from the bar store.

    The same panels as ``price_panels`` on the long table (plus the traded
    amount), without ever holding the long table: 5,800 codes over three
    years as a long frame of Python strings got panorama's master step
    killed in a 2 GiB container. Days without volume are suspensions and
    are left empty; dates and codes with no traded bar at all are dropped,
    as the pivot of the filtered long table did.
    """
    close = md.panel("close", codes=codes, start=start, end=end)
    if close.empty:
        empty = pd.DataFrame()
        return empty, empty, empty
    traded = md.panel("volume", codes=codes, start=start, end=end).reindex_like(close) > 0
    rows, cols = traded.any(axis=1), traded.any(axis=0)
    traded = traded.loc[rows, cols]
    adj = close.loc[rows, cols].where(traded)
    del close
    factor = md.panel("factor", codes=codes, start=start, end=end).reindex_like(adj)
    real = (adj / factor).where(traded)
    del factor
    amount = md.panel("amount", codes=codes, start=start, end=end).reindex_like(adj).where(traded)
    return real, adj, amount


def _last_valid(s: pd.Series):
    return s.dropna().iloc[-1] if s.notna().any() else np.nan


def trend_features(adj: pd.DataFrame) -> pd.DataFrame:
    """Per-code trend, momentum and risk features from adjusted closes."""
    ret = adj.pct_change()
    feat = {}
    feat["px_nd"] = adj.notna().sum()

    def ret_n(n):
        return adj.pct_change(n).apply(_last_valid)

    feat["ret_1m"] = ret_n(21)
    feat["ret_3m"] = ret_n(63)
    feat["ret_6m"] = ret_n(126)
    feat["ret_12m"] = ret_n(252)
    feat["mom_12_1"] = adj.shift(21).pct_change(231).apply(_last_valid)

    # Each intermediate panel is freed as soon as its features are taken: at
    # 5,800 codes x 3 years every panel is about 40 MB, and holding them all
    # at once (the moving averages, the alignment terms and the volatilities)
    # doubled the step's peak memory.
    ma20 = adj.rolling(20).mean()
    ma60 = adj.rolling(60).mean()
    align = (adj > ma20).astype(float) + (ma20 > ma60).astype(float)
    del ma20
    ma120 = adj.rolling(120).mean()
    align += (ma60 > ma120).astype(float)
    del ma60
    ma250 = adj.rolling(250).mean()
    align += (ma120 > ma250).astype(float)
    del ma250
    feat["ma_align"] = align.apply(_last_valid)
    del align
    last = adj.iloc[-1]
    feat["above_ma120"] = (last > ma120.iloc[-1]).astype(float).where(last.notna())
    del ma120
    feat["dist_high"] = last / adj.rolling(250, min_periods=60).max().iloc[-1] - 1

    v20 = ret.rolling(20).std()
    v120 = ret.rolling(120).std()
    feat["vol20"] = v20.apply(_last_valid)
    feat["vol120"] = v120.apply(_last_valid)
    feat["vol_ratio"] = (v20 / v120).apply(_last_valid)
    del v20, v120
    feat["vol_ann"] = ret.rolling(250).std().apply(_last_valid) * np.sqrt(252)
    feat["max_ret_20"] = ret.rolling(20).max().apply(_last_valid)

    # Beta against the equal-weighted market of the same universe.
    mkt = ret.mean(axis=1)
    cov = ret.rolling(252, min_periods=120).cov(mkt)
    var = mkt.rolling(252, min_periods=120).var()
    feat["beta252"] = cov.div(var, axis=0).apply(_last_valid)
    r60 = adj.pct_change(60).apply(_last_valid)
    feat["rs_market_60"] = r60 - float(r60.median())

    return pd.DataFrame(feat)
