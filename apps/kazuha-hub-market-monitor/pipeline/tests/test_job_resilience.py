"""Jobs that failed on production with beta.7: margin died on one eastmoney
call, panorama could not reach its trading calendar, sentiment was killed
loading its panels, and a bootstrap ran before the egress proxy was ready."""
import datetime as dt
import os
import socket
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # CI sets MM_REQUIRE_PANDAS
    if os.environ.get("MM_REQUIRE_PANDAS"):
        raise
    pd = None

PIPELINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE))
import mm_job  # noqa: E402


class FakeProxy:
    """A CONNECT proxy that refuses the first `refusals` requests with 403."""

    def __init__(self, test, refusals):
        self.refusals, self.seen = refusals, []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        test.addCleanup(self.sock.close)
        threading.Thread(target=self.serve, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.sock.getsockname()[1]

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                line = conn.makefile("rb").readline().decode()
                self.seen.append(line.split()[1] if len(line.split()) > 1 else "")
                code = "403 Forbidden" if len(self.seen) <= self.refusals else "200 Connection established"
                conn.sendall(("HTTP/1.1 %s\r\n\r\n" % code).encode())


class JobEnvironment(unittest.TestCase):
    def test_arrow_returns_freed_memory(self):
        self.assertEqual(mm_job.job_env("/w")["ARROW_DEFAULT_MEMORY_POOL"], "system")


class WaitForProxy(unittest.TestCase):
    def test_waits_through_refusals_until_the_proxy_passes(self):
        proxy = FakeProxy(self, refusals=2)
        self.assertTrue(mm_job.wait_for_proxy({"HTTPS_PROXY": proxy.url}, wait=10, poll=0.01))
        self.assertEqual(len(proxy.seen), 3)
        self.assertEqual(proxy.seen[0], mm_job.PROXY_PROBE)

    def test_gives_up_after_the_wait_and_lets_the_job_run(self):
        proxy = FakeProxy(self, refusals=10**6)
        self.assertFalse(mm_job.wait_for_proxy({"HTTPS_PROXY": proxy.url}, wait=0.05, poll=0.01))

    def test_no_proxy_means_no_wait(self):
        self.assertTrue(mm_job.wait_for_proxy({}, wait=0, poll=0))


@unittest.skipIf(pd is None, "pandas not installed")
class MarginAccount(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(PIPELINE / "margin_scan"))
        import fetch_data
        self.fd = fetch_data
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        for name, value in (("DATA", self.data), ("ACCOUNT_BACKOFF", 0)):
            p = patch.object(fetch_data, name, value)
            p.start()
            self.addCleanup(p.stop)

    def akshare(self, *results):
        calls = list(results)

        def info():
            r = calls.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        # Only the akshare entry: patch.dict(sys.modules) would also drop the
        # modules pandas imports meanwhile, and pandas cannot be imported twice.
        saved = sys.modules.get("akshare")
        sys.modules["akshare"] = types.SimpleNamespace(stock_margin_account_info=info)
        self.addCleanup(lambda: sys.modules.pop("akshare") if saved is None else sys.modules.__setitem__("akshare", saved))
        import contextlib
        return contextlib.nullcontext()

    def fresh(self):
        return pd.DataFrame({"日期": ["2026-11-23"], "融资余额": [1.0], "融券余额": [1.0], "融资买入额": [1.0],
                             "融券卖出额": [1.0], "担保物总价值": [1.0], "平均维持担保比例": [250.0],
                             "有融资融券负债的投资者数量": [1.0]})

    def test_retries_a_cut_off_response(self):
        with self.akshare(ConnectionError("Response ended prematurely"), self.fresh()):
            df = self.fd.fetch_account()
        self.assertEqual(df["date"].iloc[-1], "2026-11-23")
        self.assertTrue((self.data / "account.parquet").exists())

    def test_reuses_the_last_good_stats_when_every_try_fails(self):
        pd.DataFrame({"date": ["2026-11-20"], "ratio": [251.0]}).to_parquet(self.data / "account.parquet")
        errors = [ConnectionError("cut")] * self.fd.ACCOUNT_RETRIES
        with self.akshare(*errors):
            df = self.fd.fetch_account()
        self.assertEqual(df["date"].iloc[-1], "2026-11-20")

    def test_fails_only_without_any_earlier_stats(self):
        errors = [ConnectionError("cut")] * self.fd.ACCOUNT_RETRIES
        with self.akshare(*errors), self.assertRaises(ConnectionError):
            self.fd.fetch_account()


@unittest.skipIf(pd is None, "pandas not installed")
class MarketDataPanel(unittest.TestCase):
    """panel() fills the wide table straight from arrow; it must give what the
    long-table pivot gave."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.makedirs(os.path.join(tmp.name, "bars"))
        rows = [("600000", "2025-12-31", 1.0), ("600000", "2026-01-05", 2.0),
                ("000001", "2026-01-05", 3.0), ("000001", "2026-01-06", 4.0)]
        for year in ("2025", "2026"):
            part = [r for r in rows if r[1][:4] == year]
            t = pa.table({"code": [r[0] for r in part], "date": [r[1] for r in part],
                          "close": [r[2] for r in part], "volume": [10.0] * len(part)})
            pq.write_table(t, os.path.join(tmp.name, "bars", year + ".parquet"))
        sys.path.insert(0, str(PIPELINE / "MarketData"))
        import market_data
        self.md = market_data
        p = patch.object(market_data, "BARS", os.path.join(tmp.name, "bars"))
        p.start()
        self.addCleanup(p.stop)

    def test_matches_the_pivot(self):
        got = self.md.panel("close")
        self.assertEqual(list(got.columns), ["000001", "600000"])
        self.assertEqual([d.strftime("%Y-%m-%d") for d in got.index], ["2025-12-31", "2026-01-05", "2026-01-06"])
        self.assertEqual(got.loc["2026-01-05", "000001"], 3.0)
        self.assertTrue(pd.isna(got.loc["2026-01-06", "600000"]))
        self.assertIsInstance(got.index, pd.DatetimeIndex)

    def test_filters_and_dtype(self):
        got = self.md.panel("close", codes=["600000"], start="2026-01-01", dtype="float32")
        self.assertEqual(list(got.columns), ["600000"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got.dtypes.iloc[0], "float32")

    def test_nothing_selected_is_an_empty_frame(self):
        self.assertTrue(self.md.panel("close", start="2030-01-01").empty)


class PanoramaCalendar(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(PIPELINE / "workspace" / "panorama"))
        try:
            import check_freshness
        except ImportError as e:  # needs requests (mcpc) and the asof helper's deps
            self.skipTest(str(e))
        self.cf = check_freshness

    def calendar(self, days):
        """last_trading_day over a fixed list of trading days."""
        def ltd(upto=None):
            return max(d for d in days if d <= upto)
        return patch.object(self.cf, "last_trading_day", ltd)

    def test_a_trading_day_before_its_bars_accepts_the_previous_day(self):
        with self.calendar(["2026-11-20", "2026-11-23", "2026-11-24"]):
            self.assertEqual(self.cf.expected_asof("2026-11-23", dt.date(2026, 11, 24)), "2026-11-23")
            self.assertEqual(self.cf.expected_asof("2026-11-24", dt.date(2026, 11, 24)), "2026-11-24")
            # Two days behind is stale.
            self.assertEqual(self.cf.expected_asof("2026-11-20", dt.date(2026, 11, 24)), "2026-11-24")

    def test_the_next_morning_wants_the_last_trading_day(self):
        with self.calendar(["2026-11-20", "2026-11-23"]):
            # Saturday: the last trading day is Friday's, nothing looser.
            self.assertEqual(self.cf.expected_asof("2026-11-20", dt.date(2026, 11, 22)), "2026-11-20")

    def test_falls_back_to_the_data_server_when_the_store_calendar_fails(self):
        def broken(upto=None):
            raise OSError("no route")
        with patch.object(self.cf, "_from_market_data", broken), \
                patch.object(self.cf, "_from_data_server", lambda upto=None: "2026-11-23"):
            self.assertEqual(self.cf.last_trading_day("2026-11-24"), "2026-11-23")

    def test_reports_both_sources_when_neither_answers(self):
        def broken(upto=None):
            raise ConnectionError("down")
        with patch.object(self.cf, "_from_market_data", broken), patch.object(self.cf, "_from_data_server", broken), \
                self.assertRaises(SystemExit) as e:
            self.cf.last_trading_day("2026-11-24")
        self.assertIn("_from_market_data", str(e.exception))
        self.assertIn("_from_data_server", str(e.exception))


class DataServerAddress(unittest.TestCase):
    def test_panorama_reaches_the_data_server_by_the_exported_url(self):
        offenders = []
        for path in sorted((PIPELINE / "workspace" / "panorama").glob("*.py")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if "localhost:8091" in code and not code.lstrip().startswith(('"""', "m = MCP(")):
                    offenders.append(f"{path.name}:{n}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
