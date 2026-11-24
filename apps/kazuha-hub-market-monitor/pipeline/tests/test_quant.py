"""The quant job: the generator's wide panels come straight from the store
and equal what its long-table pivot gave; its data object becomes the quant
snapshot and a line of the risk summary."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import numpy as np
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


@unittest.skipIf(pd is None, "pandas not installed")
class Panels(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bars = os.path.join(tmp.name, "bars")
        os.makedirs(bars)
        rows = []
        for i, d in enumerate(pd.bdate_range("2014-05-26", periods=14).strftime("%Y-%m-%d")):
            rows.append(("600000", d, 10.0 + i, 0.0 if i == 4 else 100.0, 1e6 + i))
            rows.append(("000001", d, 5.5, 50.0, 2e5))
            rows.append(("830001", d, 7.0, 10.0, 1e4))     # Beijing exchange: dropped
            rows.append(("920001", d, 7.0, 10.0, 1e4))     # Beijing exchange: dropped
            if i > 7:
                rows.append(("300001", d, 7.0, 0.0, 0.0))  # never traded
        for year in ("2014",):
            cols = {k: [r[j] for r in rows] for j, k in enumerate(["code", "date", "close", "volume", "amount"])}
            cols.update(open=cols["close"], high=cols["close"], low=cols["close"],
                        factor=[1.0] * len(rows), tradestatus=pa.array([1] * len(rows), pa.int8()))
            pq.write_table(pa.table(cols), os.path.join(bars, year + ".parquet"))
        sys.path.insert(0, str(PIPELINE / "MarketData"))
        sys.path.insert(0, str(PIPELINE / "quant"))
        import market_data
        import panels
        self.md, self.panels = market_data, panels
        p = patch.object(market_data, "BARS", bars)
        p.start()
        self.addCleanup(p.stop)

    def test_equals_the_generators_long_table_pivot(self):
        # The generator's original load, verbatim.
        ld = self.md.load(start="2014-06-01")
        ld = ld[ld["volume"] > 0]
        c = ld["code"].astype(str)
        ld = ld[~c.str.startswith(("8", "4", "92"))]
        close0 = ld.pivot_table(index="date", columns="code", values="close").sort_index().astype(np.float32)
        amount0 = ld.pivot_table(index="date", columns="code", values="amount").sort_index().astype(np.float32)
        close, amount = self.panels.load_panels()
        pd.testing.assert_frame_equal(close, close0, check_names=False, check_freq=False)
        pd.testing.assert_frame_equal(amount, amount0, check_names=False, check_freq=False)
        self.assertEqual(list(close.columns), ["000001", "600000"])


class Snapshot(unittest.TestCase):
    DATA = {"asof": "2026-11-23", "state": "熊市确认（主跌延续）", "stateCode": "bad", "b": 8.4, "ndr": -7.3,
            "step": {"pos": 25, "stage": 1, "capr": ""}, "mstate": "深跌区（偏买）", "mcode": "ok",
            "mstep": {"pos": 25}, "mon": {"hist": []}}

    def test_the_data_object_is_the_summary(self):
        doc = mm_job.convert_quant(self.DATA)
        self.assertEqual((doc["module"], doc["as_of"], doc["rows"]), ("quant", "2026-11-23", []))
        self.assertEqual(doc["summary"], self.DATA)

    def test_risk_carries_the_current_state_and_positions(self):
        part = mm_job.risk_part("quant", mm_job.convert_quant(self.DATA))
        self.assertEqual(part, {"as_of": "2026-11-23", "state": "熊市确认（主跌延续）", "state_code": "bad",
                                "breadth": 8.4, "ndr": -7.3, "step_pos": 25, "step_stage": 1, "step_cap": None,
                                "micro_state": "深跌区（偏买）", "micro_code": "ok", "micro_pos": 25})

    def test_the_job_runs_the_generator_in_its_directory(self):
        self.assertEqual(mm_job.JOBS["quant"][:3], ("quant", ["{py}", "build_quant.py"], "quant"))
        self.assertEqual(mm_job.OUTPUTS["quant"], "quant/out/quant.json")
        self.assertIn("quant", mm_job.RISK_INPUTS)


if __name__ == "__main__":
    unittest.main()
