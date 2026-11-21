"""Price features must be computed on adjusted closes, valuation on real prices."""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from features import price_panels, trend_features  # noqa: E402


def _bars():
    """Two stocks over 300 trading days, both flat in total-return terms.

    AAA pays a large dividend on day 200: its traded price drops 40% while the
    back-adjusted close and the cumulative factor move so that the holder's
    wealth is unchanged. BBB never has a corporate action.
    """
    dates = pd.bdate_range("2025-01-01", periods=300)
    rows = []
    for i, d in enumerate(dates):
        factor = 1.0 if i < 200 else 1.0 / 0.6
        real = 10.0 if i < 200 else 6.0
        rows.append({"code": "AAA", "date": d, "close": real * factor, "factor": factor,
                     "volume": 1000.0, "amount": 1e6})
        rows.append({"code": "BBB", "date": d, "close": 20.0, "factor": 1.0,
                     "volume": 1000.0, "amount": 1e6})
    return pd.DataFrame(rows)


class PricePanels(unittest.TestCase):
    def test_real_price_is_close_over_factor(self):
        real, adj = price_panels(_bars())
        self.assertAlmostEqual(real["AAA"].iloc[-1], 6.0)
        self.assertAlmostEqual(adj["AAA"].iloc[-1], 10.0)

    def test_zero_volume_bars_are_dropped(self):
        bars = _bars()
        bars.loc[(bars["code"] == "BBB") & (bars.index % 4 == 1), "volume"] = 0
        real, adj = price_panels(bars)
        self.assertTrue(real["BBB"].isna().any())
        self.assertTrue(adj["BBB"].isna().any())


class TrendFeatures(unittest.TestCase):
    def test_ex_dividend_day_is_not_a_loss(self):
        _, adj = price_panels(_bars())
        f = trend_features(adj)
        for col in ["ret_1m", "ret_3m", "ret_6m", "mom_12_1", "max_ret_20", "rs_market_60"]:
            self.assertAlmostEqual(f.loc["AAA", col], 0.0, places=9, msg=col)

    def test_ex_dividend_day_adds_no_volatility(self):
        _, adj = price_panels(_bars())
        f = trend_features(adj)
        for col in ["vol20", "vol120", "vol_ann"]:
            self.assertAlmostEqual(f.loc["AAA", col], 0.0, places=9, msg=col)

    def test_ex_dividend_day_is_not_a_drawdown(self):
        _, adj = price_panels(_bars())
        f = trend_features(adj)
        self.assertAlmostEqual(f.loc["AAA", "dist_high"], 0.0, places=9)

    def test_columns_match_the_screener_inputs(self):
        _, adj = price_panels(_bars())
        f = trend_features(adj)
        self.assertEqual(sorted(f.columns), sorted([
            "px_nd", "ret_1m", "ret_3m", "ret_6m", "ret_12m", "mom_12_1", "ma_align",
            "above_ma120", "dist_high", "vol20", "vol120", "vol_ratio", "vol_ann",
            "max_ret_20", "beta252", "rs_market_60"]))


if __name__ == "__main__":
    unittest.main()
