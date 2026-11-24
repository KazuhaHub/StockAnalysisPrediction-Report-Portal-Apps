"""ETF flows across days without share data: the SSE gap is backfilled, a
change that still spans several trading days is a merged value, and merged
values stay out of single-day statistics."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import numpy as np
    import pandas as pd
    import pyarrow  # noqa: F401  (parquet engine)
except ImportError:  # CI sets MM_REQUIRE_PANDAS
    if os.environ.get("MM_REQUIRE_PANDAS"):
        raise
    pd = None

PANEL = Path(__file__).resolve().parent.parent / "workspace" / "analysis" / "panel"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(PANEL / "feed"))


def days(n, start="2026-03-02"):
    return list(pd.bdate_range(start, periods=n))


@unittest.skipIf(pd is None, "pandas not installed")
class MergedSpans(unittest.TestCase):
    def setUp(self):
        import flow
        self.flow = flow

    def test_a_four_day_gap_is_one_merged_value_spanning_five_days(self):
        cal = pd.DatetimeIndex(days(7))
        observed = [cal[0], cal[1], cal[6]]          # cal[2..5] have no shares
        sh = pd.DataFrame({"date": observed, "code": "510300",
                           "shares": [100e8, 101e8, 111e8], "ex": "SH"})
        nv = pd.DataFrame({"date": cal, "code": "510300", "nav": 2.0})
        got = self.flow.compute_flows(sh, nv, cal).set_index("date")
        self.assertEqual(list(got.index), [cal[1], cal[6]])
        self.assertEqual(got.loc[cal[1], "span"], 1)
        self.assertEqual(got.loc[cal[6], "span"], 5)
        self.assertAlmostEqual(got.loc[cal[6], "flow"], 20.0)   # (111-101) x 2, in 100M
        # Nothing is invented for the days without shares.
        self.assertNotIn(cal[3], got.index)


@unittest.skipIf(pd is None, "pandas not installed")
class Metrics(unittest.TestCase):
    """metrics.main end to end on synthetic stores: the merged last day is
    not the latest single-day flow and breaks a streak; window sums keep it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        cal = pd.DatetimeIndex(days(260))
        rng = np.random.default_rng(1)
        flows = rng.normal(0, 30, len(cal))
        flows[-13] = -10.0          # the streak starts after an outflow
        flows[-12:-5] = 50.0        # a seven-day inflow streak
        flows[-5:] = 10.0           # five more positive days, the last merged
        span = np.ones(len(cal), dtype=int)
        span[-1] = 5
        nf = pd.DataFrame({"date": cal, "code": "510300", "flow": flows, "span": span,
                           "cat": "沪深300", "name": "x", "ex": "SH"})
        nf.loc[len(nf) - 1, "flow"] = 1387.5
        # The four gap days have no SSE flow at all.
        nf = nf.drop(index=range(len(nf) - 5, len(nf) - 1)).reset_index(drop=True)
        nf.to_parquet(self.data / "flow.parquet", index=False)
        pd.DataFrame({"沪深300": nf.set_index("date")["flow"]}).rename_axis("date").to_parquet(
            self.data / "flow_bycat.parquet")
        pd.DataFrame({"date": cal, "code": "510300", "amount": 100.0}).to_parquet(
            self.data / "amount.parquet", index=False)
        close = 3000 + np.cumsum(rng.normal(0, 10, len(cal)))
        pd.DataFrame({"date": cal, "open": close, "high": close, "low": close, "close": close}).to_parquet(
            self.data / "index.parquet", index=False)
        pd.DataFrame({"date": cal, "sh_ye": 1.0, "sz_ye": 1.0}).to_parquet(
            self.data / "margin.parquet", index=False)
        pd.DataFrame({"date": cal, "code": "510300", "shares": 1.0, "ex": "SH"}).to_parquet(
            self.data / "shares.parquet", index=False)
        pd.DataFrame({"date": cal, "code": "510300", "nav": 1.0}).to_parquet(
            self.data / "nav.parquet", index=False)
        import metrics
        self.metrics = metrics
        p = patch.object(metrics, "DATA", str(self.data))
        p.start()
        self.addCleanup(p.stop)
        self.cal = cal

    def run_metrics(self):
        self.metrics.main()
        with open(self.data / "metrics.json", encoding="utf-8") as f:
            return json.load(f)

    def test_the_merged_last_day_is_not_a_single_day_flow(self):
        m = self.run_metrics()
        c = m["current"]
        self.assertIsNone(c["last_nf"])
        self.assertEqual(c["last_span"], 5)
        self.assertEqual(c["last_merged"], 1387.5)
        # Window sums stay exact: the merged value covers the gap days.
        self.assertEqual(c["last5"], 1388)

    def test_the_merged_day_and_the_gap_break_streaks(self):
        m = self.run_metrics()
        self.assertEqual(m["current"]["streak_pos"], 0)
        top = m["runs_top"][0]
        self.assertEqual(top["days"], 7)
        self.assertEqual(top["end"], str(self.cal[-6].date()))

    def test_series_mark_the_merged_value_and_leave_gap_days_empty(self):
        m = self.run_metrics()
        s = m["series"]
        self.assertEqual(s["dates"][-1], str(self.cal[-1].date()))
        self.assertEqual(s["nf"][-1], 1387.5)
        self.assertEqual(s["nf_span"][-1], 5)
        self.assertEqual(s["nf"][-5:-1], [None] * 4)
        self.assertEqual(m["scope"]["merged_days"], 1)


@unittest.skipIf(pd is None, "pandas not installed")
class Backfill(unittest.TestCase):
    def setUp(self):
        import shares
        self.shares = shares
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, value in (("STORE", os.path.join(tmp.name, "shares.parquet")), ("THROTTLE", 0)):
            p = patch.object(shares, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.cal = [d.date() for d in days(10, "2026-11-09")]   # 11-09 .. 11-20
        held = [self.cal[i] for i in (0, 1, 2, 3, 4, 9)]          # 11-16 .. 11-19 missing
        self.store = self.shares._append(self.shares._load(), pd.DataFrame(
            {"date": pd.to_datetime(held), "code": "510300", "shares": 1.0, "ex": "SH"}))
        self.calls = []

    def fetch(self, day):
        self.calls.append(day)
        return pd.DataFrame({"date": [day], "code": ["510300"], "shares": [2.0], "ex": ["SH"]})

    def test_fills_the_missing_sse_days_then_a_rerun_is_a_no_op(self):
        with patch.object(self.shares, "universe", lambda: pd.DataFrame(
                {"基金代码": ["510300"], "ex": ["SH"], "cat": ["沪深300"], "name": ["x"]})):
            store, filled = self.shares.fill_gaps(self.store, self.cal[-1], self.cal, fetch=self.fetch)
            self.assertEqual(filled, self.cal[5:9])
            self.assertEqual(self.calls, self.cal[5:9])
            have = set(self.shares._load()["date"].dt.date)
            self.assertTrue(set(self.cal) <= have)
            self.calls.clear()
            _, again = self.shares.fill_gaps(store, self.cal[-1], self.cal, fetch=self.fetch)
            self.assertEqual(again, [])
            self.assertEqual(self.calls, [])

    def test_a_day_the_source_cannot_give_stays_missing_for_the_next_run(self):
        with patch.object(self.shares, "universe", lambda: pd.DataFrame(
                {"基金代码": ["510300"], "ex": ["SH"], "cat": ["沪深300"], "name": ["x"]})):
            _, filled = self.shares.fill_gaps(
                self.store, self.cal[-1], self.cal,
                fetch=lambda d: None if d == self.cal[6] else self.fetch(d))
        self.assertNotIn(self.cal[6], filled)
        self.assertNotIn(self.cal[6], set(self.shares._load()["date"].dt.date))

    def test_never_reaches_before_the_first_sse_day_or_past_upto(self):
        with patch.object(self.shares, "universe", lambda: pd.DataFrame(
                {"基金代码": ["510300"], "ex": ["SH"], "cat": ["沪深300"], "name": ["x"]})):
            early = [dt.date(2026, 11, 2)] + self.cal
            self.shares.fill_gaps(self.store, self.cal[6], early, fetch=self.fetch)
        self.assertEqual(self.calls, self.cal[5:7])


if __name__ == "__main__":
    unittest.main()
