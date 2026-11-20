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

    ma20 = adj.rolling(20).mean()
    ma60 = adj.rolling(60).mean()
    ma120 = adj.rolling(120).mean()
    ma250 = adj.rolling(250).mean()
    align = ((adj > ma20).astype(float) + (ma20 > ma60).astype(float)
             + (ma60 > ma120).astype(float) + (ma120 > ma250).astype(float))
    feat["ma_align"] = align.apply(_last_valid)
    last = adj.iloc[-1]
    feat["above_ma120"] = (last > ma120.iloc[-1]).astype(float).where(last.notna())
    feat["dist_high"] = last / adj.rolling(250, min_periods=60).max().iloc[-1] - 1

    v20 = ret.rolling(20).std()
    v120 = ret.rolling(120).std()
    v250 = ret.rolling(250).std()
    feat["vol20"] = v20.apply(_last_valid)
    feat["vol120"] = v120.apply(_last_valid)
    feat["vol_ratio"] = (v20 / v120).apply(_last_valid)
    feat["vol_ann"] = v250.apply(_last_valid) * np.sqrt(252)
    feat["max_ret_20"] = ret.rolling(20).max().apply(_last_valid)

    # Beta against the equal-weighted market of the same universe.
    mkt = ret.mean(axis=1)
    cov = ret.rolling(252, min_periods=120).cov(mkt)
    var = mkt.rolling(252, min_periods=120).var()
    feat["beta252"] = cov.div(var, axis=0).apply(_last_valid)
    r60 = adj.pct_change(60).apply(_last_valid)
    feat["rs_market_60"] = r60 - float(r60.median())

    return pd.DataFrame(feat)
