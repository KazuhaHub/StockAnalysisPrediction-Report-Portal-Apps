"""Margin's daily bars: read from the MarketData store first, then the Tencent
and Sina fallbacks, all before the coverage gate, which stays as it was.
None of these tests touch the network."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # a plain checkout may lack them; CI sets MM_REQUIRE_PANDAS
    if os.environ.get("MM_REQUIRE_PANDAS"):
        raise
    pd = None

PIPELINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE / "margin_scan"))
if pd is not None:
    import bar_sources as bs  # noqa: E402
    import fetch_data as fd  # noqa: E402

COLS = ["code", "date", "open", "close", "high", "low", "volume", "amount"]
DAYS = ["2026-11-18", "2026-11-19", "2026-11-20", "2026-11-23"]
TARGET = "2026-11-23"


def md_store(root, rows):
    """Write a MarketData bars/ partition: rows of (code, date, raw close,
    factor, real shares, amount, tradestatus)."""
    bars = os.path.join(root, "bars")
    os.makedirs(bars, exist_ok=True)
    recs = []
    for code, date, raw, factor, shares, amount, status in rows:
        hfq = raw * factor
        recs.append({"code": code, "date": date, "open": hfq, "high": hfq, "low": hfq,
                     "close": hfq, "volume": shares / factor, "amount": amount,
                     "factor": factor, "tradestatus": status})
    df = pd.DataFrame(recs)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), os.path.join(bars, "2026.parquet"))


def old_bars(codes, days, close=10.0, amount=1e6):
    return pd.DataFrame([(c, d, close, close, close, close, 100.0, amount)
                         for c in codes for d in days], columns=COLS)


@unittest.skipIf(pd is None, "pandas not installed")
class MarketDataSource(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.md = tmp.name

    def test_converts_hfq_to_qfq_anchored_at_the_target_day(self):
        # A 10% bonus between 11-19 and 11-20: hfq stays continuous, the
        # factor steps up, and qfq history is scaled down to the target day.
        md_store(self.md, [("600000", "2026-11-19", 11.0, 1.0, 1000, 11000.0, 1),
                           ("600000", "2026-11-20", 10.0, 1.1, 1100, 11000.0, 1),
                           ("600000", TARGET, 10.0, 1.1, 1100, 11000.0, 1)])
        got = bs.from_marketdata(["600000"], TARGET, 150, self.md)
        rows = got.set_index("date")
        self.assertAlmostEqual(rows.loc[TARGET, "close"], 10.0)
        self.assertAlmostEqual(rows.loc["2026-11-19", "close"], 10.0)  # 11 * 1.0 / 1.1
        self.assertAlmostEqual(rows.loc[TARGET, "volume"], 11.0)       # lots of 100 real shares
        self.assertAlmostEqual(rows.loc[TARGET, "amount"], 11000.0)
        self.assertEqual(list(got.columns), COLS)

    def test_skips_codes_without_a_traded_bar_on_the_target_day(self):
        md_store(self.md, [("600000", "2026-11-20", 10.0, 1.0, 100, 1000.0, 1),
                           ("000001", "2026-11-20", 10.0, 1.0, 100, 1000.0, 1),
                           ("000001", TARGET, 10.0, 1.0, 0, 0.0, 0)])  # suspended
        got = bs.from_marketdata(["600000", "000001"], TARGET, 150, self.md)
        self.assertTrue(got.empty)

    def test_drops_suspended_days_and_keeps_the_last_limit_bars(self):
        md_store(self.md, [("600000", d, 10.0, 1.0, 100, 1000.0, 0 if d == "2026-11-19" else 1)
                           for d in DAYS])
        got = bs.from_marketdata(["600000"], TARGET, 2, self.md)
        self.assertEqual(list(got["date"]), ["2026-11-20", TARGET])

    def test_a_zero_volume_bar_counts_as_suspended(self):
        # The store backfills tradestatus to 1, so a suspended day shows up
        # only as a bar without volume.
        md_store(self.md, [("600000", "2026-11-20", 10.0, 1.0, 100, 1000.0, 1),
                           ("600000", TARGET, 10.0, 1.0, 0, 0.0, 1)])
        self.assertTrue(bs.from_marketdata(["600000"], TARGET, 150, self.md).empty)

    def test_duplicate_store_rows_do_not_break_the_read(self):
        md_store(self.md, [("600000", TARGET, 10.0, 1.0, 100, 1000.0, 1),
                           ("600000", TARGET, 10.0, 1.0, 100, 1000.0, 1)])
        self.assertEqual(len(bs.from_marketdata(["600000"], TARGET, 150, self.md)), 1)

    def test_a_missing_store_gives_nothing(self):
        self.assertTrue(bs.from_marketdata(["600000"], TARGET, 150, os.path.join(self.md, "none")).empty)


@unittest.skipIf(pd is None, "pandas not installed")
class Consistency(unittest.TestCase):
    def series(self, closes, amount=1e6):
        return pd.DataFrame([("A", d, c, c, c, c, 1.0, amount) for d, c in zip(DAYS, closes)], columns=COLS)

    def test_same_prices_agree(self):
        self.assertTrue(bs.consistent(self.series([10, 10, 10, 11]), self.series([10, 10, 10])))

    def test_a_constant_re_anchoring_agrees(self):
        # Old qfq anchored before a dividend: every old price is off by the same factor.
        self.assertTrue(bs.consistent(self.series([9, 9, 9, 9]), self.series([10, 10, 10])))

    def test_a_drifting_ratio_disagrees(self):
        self.assertFalse(bs.consistent(self.series([10, 10, 9.5, 9]), self.series([10, 10, 10])))

    def test_amounts_in_other_units_disagree(self):
        self.assertFalse(bs.consistent(self.series([10, 10, 10, 10], amount=1e4), self.series([10, 10, 10])))

    def test_no_overlap_agrees(self):
        self.assertTrue(bs.consistent(self.series([10, 10, 10, 10]), self.series([])))


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


@unittest.skipIf(pd is None, "pandas not installed")
class Tencent(unittest.TestCase):
    """newfqkline rows: date, open, close, high, low, volume, {}, turnover,
    amount (10k yuan); volume is in lots, except STAR Market shares."""

    def kline(self, code, rows):
        mkt = bs._tx_market(code)
        return FakeResponse({"data": {mkt + code: {"qfqday": rows}}})

    def test_reads_amount_and_lots(self):
        rows = [["2026-11-20", "1", "10.00", "1", "1", "500.00", {}, "0.1", "50.00", ""],
                [TARGET, "1", "11.00", "1", "1", "600.00", {}, "0.1", "66.00", ""]]
        star = [[TARGET, "1", "11.00", "1", "1", "60000.00", {}, "0.1", "66.00", ""]]
        with patch("requests.get", lambda url, params, **kw: self.kline(
                params["param"][2:8], star if params["param"][2:8] == "688001" else rows)):
            self.assertEqual(bs.tx_daily("600000")[TARGET], (1.0, 11.0, 1.0, 1.0, 600.0, 660000.0))
            self.assertEqual(bs.tx_daily("688001")[TARGET][4], 600.0)
            self.assertEqual(bs._tx_market("510300"), "sh")

    def test_reference_day_close_and_amount_must_match(self):
        prevd = pd.DataFrame({"close": [10.0, 10.0, 10.0], "amount": [5e5, 5e5, 9e9]},
                             index=["600000", "600001", "600002"])
        good = {"2026-11-20": (1, 10.0, 1, 1, 5, 5e5), TARGET: (1, 11.0, 1, 1, 6, 6e5)}
        reanchored = {"2026-11-20": (1, 9.0, 1, 1, 5, 5e5), TARGET: (1, 11.0, 1, 1, 6, 6e5)}
        data = {"600000": good, "600001": reanchored, "600002": good}
        with patch.object(bs, "tx_daily", lambda c: data[c]):
            recs, bad = bs.from_tx(["600000", "600001", "600002", "600003"], TARGET, "2026-11-20", prevd)
        self.assertEqual(recs, [("600000", TARGET, 1, 11.0, 1, 1, 6, 6e5)])
        self.assertEqual(bad, 2)


@unittest.skipIf(pd is None, "pandas not installed")
class Collect(unittest.TestCase):
    """collect() tries MarketData, then Tencent, then Sina, per code."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.md = tmp.name
        md_store(self.md, [(c, d, 10.0, 1.0, 10000, 1e6, 1) for c in ("600000", "600001") for d in DAYS])
        self.old = old_bars(["600000", "600001", "510300", "000002", "000003"], DAYS[:3])
        self.calls = {"tx": [], "sina": []}

    def tx(self, codes, target, prev, prev_close, workers=6):
        self.calls["tx"].append(sorted(codes))
        return [(c, target, 10, 10, 10, 10, 1, 1e6) for c in codes if c == "510300"], 0

    def sina(self, codes, target, prev, prevd, workers=4):
        self.calls["sina"].append(sorted(codes))
        return [(c, target, 10, 10, 10, 10, 1, 1e6) for c in codes if c == "000002"], 0

    def collect(self, codes):
        with patch.object(bs, "from_tx", self.tx), patch.object(bs, "from_sina", self.sina):
            return bs.collect(codes, self.old, TARGET, 150, self.md)

    def test_falls_back_in_order_and_counts_each_source(self):
        codes = ["600000", "600001", "510300", "000002", "000003"]
        new, mix = self.collect(codes)
        self.assertEqual(mix, {"marketdata": 2, "tx": 1, "sina": 1, "missing": 1})
        self.assertEqual(self.calls["tx"], [["000002", "000003", "510300"]])
        self.assertEqual(self.calls["sina"], [["000002", "000003"]])
        self.assertEqual(sorted(new[new["date"] == TARGET]["code"]), ["000002", "510300", "600000", "600001"])

    def test_inconsistent_marketdata_bars_fall_back(self):
        self.old.loc[self.old["code"] == "600001", "amount"] = 1.0  # other units: refuse the store's copy
        new, mix = self.collect(["600000", "600001"])
        self.assertEqual(mix["marketdata"], 1)
        self.assertEqual(self.calls["tx"], [["600001"]])

    def test_no_fallback_call_when_the_store_covers_everything(self):
        _, mix = self.collect(["600000", "600001"])
        self.assertEqual(mix, {"marketdata": 2, "tx": 0, "sina": 0, "missing": 0})
        self.assertEqual(self.calls, {"tx": [], "sina": []})


@unittest.skipIf(pd is None, "pandas not installed")
class FetchBarsGate(unittest.TestCase):
    """fetch_bars feeds collect() into the unchanged 98% coverage gate and
    never asks eastmoney's push2his."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        patcher = patch.object(fd, "DATA", self.data)
        patcher.start()
        self.addCleanup(patcher.stop)
        old_bars([f"60000{i}" for i in range(5)], DAYS[:3]).to_parquet(self.data / "bars.parquet", index=False)
        self.no_push2his = patch.object(fd, "_fetch_bars_one", side_effect=AssertionError("push2his called"))
        self.no_push2his.start()
        self.addCleanup(self.no_push2his.stop)

    def fetch(self, covered):
        def collect(codes, old, target, limit, md_home):
            new = old_bars([c for c in codes if c in covered], [target], close=11.0)
            return new, {"marketdata": len(new), "tx": 0, "sina": 0, "missing": len(codes) - len(new)}
        with patch.object(bs, "collect", collect):
            return fd.fetch_bars([f"60000{i}" for i in range(5)], refresh=True, end_date="20261123")

    def test_full_coverage_passes_and_new_bars_win(self):
        out = self.fetch({f"60000{i}" for i in range(5)})
        self.assertEqual(out[out["date"] == TARGET]["code"].nunique(), 5)

    def test_low_coverage_keeps_the_old_table_authoritative(self):
        out = self.fetch({"600000"})
        self.assertEqual(set(out[out["date"] == TARGET]["code"]), {"600000"})
        self.assertTrue((out[out["date"] < TARGET]["close"] == 10.0).all())


class HttpsOnly(unittest.TestCase):
    """The job environment loads a sitecustomize that sends every plain-HTTP
    request to a non-loopback host over https: only HTTPS_PROXY is set, so a
    plain-HTTP request would bypass the reviewed proxy."""

    def setUp(self):
        sys.path.insert(0, str(PIPELINE / "pysite"))
        self.addCleanup(sys.path.remove, str(PIPELINE / "pysite"))
        import https_only
        self.h = https_only

    def test_upgrades_remote_http(self):
        self.assertEqual(self.h.upgrade("http://data.eastmoney.com/dataapi/zlsj/list?a=1"),
                         "https://data.eastmoney.com/dataapi/zlsj/list?a=1")
        self.assertEqual(self.h.upgrade("HTTP://vip.stock.finance.sina.com.cn:80/x"),
                         "https://vip.stock.finance.sina.com.cn/x")

    def test_leaves_loopback_and_https_alone(self):
        for url in ("http://127.0.0.1:8091/mcp", "http://localhost:8091/mcp", "http://[::1]:8091/",
                    "https://data.eastmoney.com/x"):
            self.assertEqual(self.h.upgrade(url), url)

    def test_requests_sends_the_upgraded_url(self):
        try:
            import requests
        except ImportError:
            self.skipTest("requests not installed")
        self.h.install()
        seen = []

        class Adapter(requests.adapters.BaseAdapter):
            def send(self, request, **kw):
                seen.append(request.url)
                resp = requests.Response()
                resp.status_code, resp.url, resp._content = 200, request.url, b"{}"
                return resp

            def close(self):
                pass
        s = requests.Session()
        s.mount("https://", Adapter())
        s.mount("http://", Adapter())
        s.get("http://data.eastmoney.com/dataapi/zlsj/list", params={"p": 1})
        s.get("http://127.0.0.1:8091/mcp")
        self.assertEqual(seen, ["https://data.eastmoney.com/dataapi/zlsj/list?p=1", "http://127.0.0.1:8091/mcp"])

    def test_the_job_environment_loads_it(self):
        sys.path.insert(0, str(PIPELINE))
        import mm_job
        env = mm_job.job_env("/w")
        self.assertEqual(env["PYTHONPATH"].split(os.pathsep)[0], str(PIPELINE / "pysite"))


if __name__ == "__main__":
    unittest.main()
