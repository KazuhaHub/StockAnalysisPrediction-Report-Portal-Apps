"""Tests for the job entry: work-dir preparation, job dispatch and the
conversion of each module's output into a snapshot document."""
import json
import math
import os
import socket
import stat
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mm_job  # noqa: E402

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # a plain checkout may lack it; CI sets MM_REQUIRE_PYARROW
    if os.environ.get("MM_REQUIRE_PYARROW"):
        raise
    pa = pq = None
needs_pyarrow = unittest.skipIf(pa is None, "pyarrow not installed")

SNAPSHOT_KEYS = {"format", "module", "as_of", "summary", "rows", "details"}


def write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(value, str):
            f.write(value)
        else:
            json.dump(value, f, ensure_ascii=False)


def margin_payload():
    return {
        "meta": {"as_of": "2026-11-18", "generated_at": "2026-11-19 10:00:50", "n": 2},
        "overview": {
            "rz_total": 20719.7, "guarantee": 249.7, "n_res2": 106, "n_critical": 642,
            "n_high": 415, "n_pledge_near": 72, "n_pledge_breach": 53, "n_unlock60": 99,
            "n_cb_arb": 5, "n_block": 375, "n_gdhs_dump": 507,
            "lever_series": {"d": ["2026-11-17", "2026-11-18"], "rz": [20800, 20719.7], "ratio": [2.57, 2.56]},
            "guarantee_series": {"d": ["2026-11-17"], "v": [249.7]},
        },
        "fields": ["code", "name", "frag", "state"],
        "rows": {"code": ["600000", "000001"], "name": ["A", "B"], "frag": [90.0, float("nan")], "state": ["临界", "安全"]},
        "hist_dates": ["2026-11-17", "2026-11-18"],
        "hist": {"600000": {"c": [10.0, 10.5], "r": [1.0, 1.1]}},
    }


def sentiment_monitor():
    return {
        "asof": "2026-11-19", "headline": "h",
        "dims": [{"k": "广度", "v": 4.8}, {"k": "量能", "v": 15.7}],
        "traj": {"dates": ["2026-11-18", "2026-11-19"], "series": {"广度": [10.3, 4.8], "量能": [18, 15.7]}},
        "alerts": [], "conclusion": {"v": 24.9},
    }


def etf_metrics():
    return {
        "asof": "2026-11-16",
        "current": {"last20": 2832.0},
        "health": {"label": "失效", "light": "red", "items": []},
        "series": {"dates": ["2026-11-13", "2026-11-16"], "nf": [10.0, 136.8], "idx": [3600, 3602]},
        "funds": [{"code": "588000", "name": "科创50ETF", "cat": "科创50", "cum20": 414.6}],
    }


def panorama_payload():
    return {
        "meta": {"asof": "2026-11-16", "report_period": "2026Q3"},
        "factors": [], "strategies": {}, "methods": [],
        "stocks": [{"symbol": "000001", "name": "平安银行", "pe": 5.5, "upside": float("inf")},
                   {"symbol": "600000", "name": "浦发银行", "pe": 6.1, "upside": 0.1}],
        "pct": {"EP": [0.1, 0.2]},
    }


class Env:
    def __init__(self, test):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.work = os.path.join(self.root, "work")
        self.out = os.path.join(self.root, "out")
        os.makedirs(self.out)

    def outputs(self):
        out = {}
        for name in sorted(os.listdir(self.out)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(self.out, name), encoding="utf-8") as f:
                out[name[:-5]] = json.load(f)
        return out


class PrepareWork(unittest.TestCase):
    def test_copies_code_and_keeps_data(self):
        e = Env(self)
        src = os.path.join(e.root, "src")
        write(os.path.join(src, "margin_scan", "build_data.py"), "v1")
        mm_job.prepare_work(src, e.work)
        write(os.path.join(e.work, "margin_scan", "out", "payload.json"), {"kept": True})
        write(os.path.join(src, "margin_scan", "build_data.py"), "v2")
        mm_job.prepare_work(src, e.work)
        with open(os.path.join(e.work, "margin_scan", "build_data.py"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "v2")
        self.assertTrue(os.path.exists(os.path.join(e.work, "margin_scan", "out", "payload.json")))

    def test_skips_top_level_tests_and_the_entry_but_not_nested_tests(self):
        e = Env(self)
        src = os.path.join(e.root, "src")
        write(os.path.join(src, "tests", "test_x.py"), "t")
        write(os.path.join(src, "mm_job.py"), "entry")
        write(os.path.join(src, "pkg", "tests", "fixture.json"), "{}")
        mm_job.prepare_work(src, e.work)
        self.assertFalse(os.path.exists(os.path.join(e.work, "tests")))
        self.assertFalse(os.path.exists(os.path.join(e.work, "mm_job.py")))
        self.assertTrue(os.path.exists(os.path.join(e.work, "pkg", "tests", "fixture.json")))

    def test_removes_a_venv_link_an_earlier_version_left(self):
        # Up to 0.1.0-beta.5 this linked work/venv to the interpreter; the
        # platform's data checkpoint refuses any symlink in the data root.
        e = Env(self)
        src = os.path.join(e.root, "src")
        os.makedirs(src)
        os.makedirs(e.work)
        os.symlink(sys.prefix, os.path.join(e.work, "venv"))
        mm_job.prepare_work(src, e.work)
        self.assertFalse(os.path.lexists(os.path.join(e.work, "venv")))

    def test_removes_a_real_venv_and_the_ones_an_earlier_version_set_aside(self):
        # A real venv holds symlinks (bin/python3); beta.5 and earlier renamed
        # one found here to venv.replaced-<time>.
        e = Env(self)
        src = os.path.join(e.root, "src")
        os.makedirs(src)
        os.makedirs(os.path.join(e.work, "venv", "bin"))
        os.symlink(sys.executable, os.path.join(e.work, "venv", "bin", "python3"))
        write(os.path.join(e.work, "venv.replaced-1700000000", "pyvenv.cfg"), "x")
        write(os.path.join(e.work, "venvish", "keep"), "x")
        mm_job.prepare_work(src, e.work)
        self.assertEqual(sorted(os.listdir(e.work)), ["venvish"])

    def test_unshares_hard_links_in_the_work_dir(self):
        e = Env(self)
        src = os.path.join(e.root, "src")
        os.makedirs(src)
        bars = os.path.join(e.work, "MarketData", "bars", "2024.parquet")
        snap = os.path.join(e.work, "MarketData", "snapshots", "s1", "2024.parquet")
        write(bars, "bars")
        os.makedirs(os.path.dirname(snap))
        os.link(bars, snap)
        os.utime(bars, ns=(1_700_000_000_123_456_789, 1_700_000_000_123_456_789))
        write(os.path.join(e.work, "MarketData", "x.parquet" + mm_job.UNSHARE_SUFFIX), "partial")
        mm_job.prepare_work(src, e.work)
        for path in (bars, snap):
            self.assertEqual(os.stat(path).st_nlink, 1)
            # publish() trusts output mtimes, so unsharing must keep them
            self.assertEqual(os.stat(path).st_mtime_ns, 1_700_000_000_123_456_789)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "bars")
        self.assertEqual(sorted(os.listdir(os.path.join(e.work, "MarketData"))), ["bars", "snapshots"])

    def test_a_failed_unshare_leaves_no_partial_copy(self):
        e = Env(self)
        a = os.path.join(e.work, "a")
        write(a, "data")
        os.link(a, os.path.join(e.work, "b"))
        saved = mm_job.shutil.copy2

        def broken(s, t):
            with open(t, "w") as f:
                f.write("par")
            raise OSError(28, "No space left on device")
        mm_job.shutil.copy2 = broken
        self.addCleanup(setattr, mm_job.shutil, "copy2", saved)
        with self.assertRaises(OSError):
            mm_job.unshare_hard_links(e.work)
        self.assertEqual(sorted(os.listdir(e.work)), ["a", "b"])

    def test_leaves_nothing_the_data_checkpoint_refuses(self):
        e = Env(self)
        src = os.path.join(e.root, "src")
        write(os.path.join(src, "margin_scan", "update.sh"), "#!/bin/sh\n")
        os.makedirs(e.work)
        os.symlink(sys.prefix, os.path.join(e.work, "venv"))
        mm_job.prepare_work(src, e.work)
        self.assertEqual(checkpoint_unsafe(e.root), [])


def checkpoint_unsafe(root):
    """Entries under root that the platform's data checkpoint refuses: any
    symlink, socket, fifo or device, and regular files with more than one
    link."""
    bad = []
    for top, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(top, name)
            st = os.lstat(path)
            if stat.S_ISDIR(st.st_mode):
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
                bad.append(os.path.relpath(path, root))
    return sorted(bad)


class JobEnv(unittest.TestCase):
    def test_skips_html_and_uses_the_exchange_time_zone(self):
        saved = os.environ.pop("TZ", None)
        self.addCleanup(lambda: saved is not None and os.environ.__setitem__("TZ", saved))
        env = mm_job.job_env("/w")
        self.assertEqual(env["MM_NO_HTML"], "1")
        self.assertEqual(env["TZ"], "Asia/Shanghai")

    def test_runs_the_pipeline_on_this_interpreter_and_copies_snapshots(self):
        env = mm_job.job_env("/w")
        self.assertEqual(env["PY"], sys.executable)
        # Hard-linked write-ahead snapshots would leave files with two links.
        self.assertEqual(env["MD_SNAPSHOT_COPY"], "1")


class NoVenvUnderTheDataRoot(unittest.TestCase):
    """Job scripts must take the interpreter from $PY: nothing provides
    /opt/daily-tasks/venv any more."""

    def test_no_job_script_hard_codes_the_venv_interpreter(self):
        pipeline = os.path.dirname(HERE)
        offenders = []
        for top, dirs, files in os.walk(pipeline):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for name in files:
                if not name.endswith((".py", ".sh")) or name in ("install.sh", "env.sh", "mm_job.py"):
                    continue
                path = os.path.join(top, name)
                with open(path, encoding="utf-8") as f:
                    for n, line in enumerate(f, 1):
                        if name.endswith(".sh"):
                            code, prose = line.split("#", 1)[0], False
                        else:  # usage lines in docstrings name the interpreter
                            code = line
                            prose = code.lstrip().startswith(("/opt/daily-tasks/venv/bin/python3 ", "解释器"))
                        if "venv/bin/python" in code and "${PY:-" not in code \
                                and "os.environ.get(\"PY\"" not in code and not prose:
                            offenders.append(f"{os.path.relpath(path, pipeline)}:{n}")
        self.assertEqual(offenders, [])


class Dispatch(unittest.TestCase):
    def test_unknown_job_exits_2(self):
        self.assertEqual(mm_job.main(["mm_job.py", "nope"]), 2)
        self.assertEqual(mm_job.main(["mm_job.py"]), 2)

    def test_every_service_job_is_known(self):
        self.assertEqual(sorted(mm_job.JOBS), ["etf", "margin", "marketdata", "panorama", "quant", "sentiment"])

    def test_job_failure_writes_nothing(self):
        e = Env(self)
        write(os.path.join(e.work, "margin_scan", "out", "payload.json"), margin_payload())
        code = mm_job.publish("margin", e.work, e.out, exit_code=7)
        self.assertEqual(code, 7)
        self.assertEqual(os.listdir(e.out), [])


class Convert(unittest.TestCase):
    def check_snapshot(self, snap, module, as_of):
        self.assertEqual(set(snap) - {"details"}, SNAPSHOT_KEYS - {"details"})
        self.assertEqual(snap["format"], "market-monitor.snapshot/1")
        self.assertEqual(snap["module"], module)
        self.assertEqual(snap["as_of"], as_of)
        self.assertIsInstance(snap["summary"], dict)
        codes = [r["code"] for r in snap["rows"]]
        self.assertEqual(len(codes), len(set(codes)))

    def margin_with_ratio(self, ratios):
        payload = margin_payload()
        payload["fields"] = ["code", "ratio"]
        payload["rows"] = {"code": [f"{i:06d}" for i in range(len(ratios))], "ratio": ratios}
        payload["hist"] = {}
        return payload

    def test_margin_ratio_hist(self):
        ratios = [0.0, 0.49, 0.5, 7.99, 8.0, 14.4, 14.5, 40.0, None, float("nan")]
        h = mm_job.convert_margin(self.margin_with_ratio(ratios))["summary"]["overview"]["ratio_hist"]
        self.assertEqual(h["width"], 0.5)
        self.assertEqual(len(h["counts"]), 30)
        # Bin i covers [i*0.5, (i+1)*0.5); the last bin is open-ended; missing ratios are skipped.
        self.assertEqual(h["counts"][0], 2)
        self.assertEqual(h["counts"][1], 1)
        self.assertEqual(h["counts"][15], 1)
        self.assertEqual(h["counts"][16], 1)
        self.assertEqual(h["counts"][28], 1)
        self.assertEqual(h["counts"][29], 2)
        self.assertEqual(sum(h["counts"]), 8)
        self.assertEqual(h["median"], 7.995)

    def test_margin_ratio_hist_drops_negative_ratios_and_survives_huge_ones(self):
        h = mm_job.convert_margin(self.margin_with_ratio([-1.0, 1.0, 1e308]))["summary"]["overview"]["ratio_hist"]
        self.assertEqual(sum(h["counts"]), 2)
        self.assertEqual(h["counts"][0], 0)
        self.assertEqual(h["counts"][2], 1)
        self.assertEqual(h["counts"][29], 1)

    def test_margin_ratio_hist_keeps_the_builders_median_and_existing_hist(self):
        payload = self.margin_with_ratio([1.0, 2.0, 3.0])
        payload["overview"]["ratio_med"] = 2.5
        self.assertEqual(mm_job.convert_margin(payload)["summary"]["overview"]["ratio_hist"]["median"], 2.5)
        payload["overview"]["ratio_hist"] = {"width": 1, "counts": [1], "median": 0}
        self.assertEqual(mm_job.convert_margin(payload)["summary"]["overview"]["ratio_hist"]["width"], 1)

    def test_margin_without_ratios_has_no_hist(self):
        # margin_payload() rows carry no ratio column at all
        self.assertNotIn("ratio_hist", mm_job.convert_margin(margin_payload())["summary"]["overview"])

    def test_margin(self):
        e = Env(self)
        write(os.path.join(e.work, "margin_scan", "out", "payload.json"), margin_payload())
        self.assertEqual(mm_job.publish("margin", e.work, e.out), 0)
        out = e.outputs()
        m = out["margin"]
        self.check_snapshot(m, "margin", "2026-11-18")
        self.assertEqual(m["rows"][0], {"code": "600000", "name": "A", "frag": 90.0, "state": "临界"})
        self.assertIsNone(m["rows"][1]["frag"])  # NaN becomes null
        self.assertEqual(m["summary"]["hist_dates"], ["2026-11-17", "2026-11-18"])
        self.assertEqual(m["details"], {"600000": {"c": [10.0, 10.5], "r": [1.0, 1.1]}})
        self.assertIn("risk", out)

    def test_sentiment(self):
        e = Env(self)
        write(os.path.join(e.work, "workspace", "analysis", "out", "sentiment", "monitor.json"), sentiment_monitor())
        mm_job.publish("sentiment", e.work, e.out)
        s = e.outputs()["sentiment"]
        self.check_snapshot(s, "sentiment", "2026-11-19")
        self.assertEqual(s["rows"], [])
        self.assertEqual(s["summary"]["headline"], "h")

    def test_etf(self):
        e = Env(self)
        write(os.path.join(e.work, "workspace", "analysis", "panel", "data", "metrics.json"), etf_metrics())
        mm_job.publish("etf", e.work, e.out)
        s = e.outputs()["etf"]
        self.check_snapshot(s, "etf", "2026-11-16")
        self.assertEqual(s["rows"][0]["code"], "588000")
        self.assertNotIn("funds", s["summary"])

    def test_panorama(self):
        e = Env(self)
        write(os.path.join(e.work, "workspace", "panorama", "data", "site_payload.json"), panorama_payload())
        mm_job.publish("panorama", e.work, e.out)
        out = e.outputs()
        p = out["panorama"]
        self.check_snapshot(p, "panorama", "2026-11-16")
        self.assertEqual([r["code"] for r in p["rows"]], ["000001", "600000"])
        self.assertIsNone(p["rows"][0]["upside"])  # inf becomes null
        self.assertNotIn("stocks", p["summary"])
        self.assertNotIn("pct", p["summary"])
        self.assertNotIn("risk", out)  # Panorama is not a risk input

    def panorama_site(self, e, asof="2026-11-16", mtime=None, text=None):
        site = {"meta": {"asof": asof, "corr": [[1.0]], "inter": [[3]], "n_industries": 1},
                "industries": [{"name": "银行", "n": 42, "s_value": 65.0}],
                "market": {"median_pe": 19.8, "median_pb": 2.18, "above_ma120_pct": 9.5},
                "diff": {"first": False, "prev": "2026-11-13", "cur": asof,
                         "shift": [{"s": "300215", "n": "电科院", "a": 0.213, "b": -0.553}]},
                "rows": [[1, 2]], "cols": ["x"]}
        path = os.path.join(e.work, "workspace", "panorama", "site", "data.js")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text if text is not None else "window.PANORAMA=" + json.dumps(site, ensure_ascii=False) + ";")
        if mtime is not None:
            os.utime(path, (mtime, mtime))

    def publish_panorama(self, **site):
        e = Env(self)
        write(os.path.join(e.work, "workspace", "panorama", "data", "site_payload.json"), panorama_payload())
        if site.pop("present", True):
            self.panorama_site(e, **site)
        started = time.time() - 60
        self.assertEqual(mm_job.publish("panorama", e.work, e.out, started=started), 0)
        return e.outputs()["panorama"]["summary"]

    def test_panorama_adds_the_site_extras(self):
        s = self.publish_panorama()
        self.assertEqual(s["industries"][0]["name"], "银行")
        self.assertEqual(s["market"]["median_pe"], 19.8)
        self.assertEqual(s["diff"]["shift"][0]["s"], "300215")
        self.assertEqual(s["meta"]["corr"], [[1.0]])
        self.assertEqual(s["meta"]["report_period"], "2026Q3")  # site_payload meta kept
        self.assertNotIn("rows", s)  # only the named extras are taken
        self.assertEqual(sorted(s["market"]), ["above_ma120_pct", "median_pb", "median_pe"])

    def test_panorama_keeps_diff_only_for_the_same_date(self):
        # diff.py compares the latest two snapshot dates; a backfill of an
        # older date must not carry a later comparison.
        e = Env(self)
        write(os.path.join(e.work, "workspace", "panorama", "data", "site_payload.json"), panorama_payload())
        self.panorama_site(e)
        path = os.path.join(e.work, "workspace", "panorama", "site", "data.js")
        text = open(path, encoding="utf-8").read().replace('"cur": "2026-11-16"', '"cur": "2026-11-17"')
        open(path, "w", encoding="utf-8").write(text)
        mm_job.publish("panorama", e.work, e.out, started=time.time() - 60)
        s = e.outputs()["panorama"]["summary"]
        self.assertNotIn("diff", s)
        self.assertIn("industries", s)

    def test_panorama_site_nan_becomes_null(self):
        e = Env(self)
        write(os.path.join(e.work, "workspace", "panorama", "data", "site_payload.json"), panorama_payload())
        self.panorama_site(e, text='window.PANORAMA={"meta":{"asof":"2026-11-16"},'
                                   '"industries":[{"name":"银行","s_dividend":NaN}]};')
        mm_job.publish("panorama", e.work, e.out, started=time.time() - 60)
        self.assertIsNone(e.outputs()["panorama"]["summary"]["industries"][0]["s_dividend"])

    def test_panorama_without_fresh_matching_extras_still_publishes(self):
        cases = {
            "missing": {"present": False},
            "stale": {"mtime": time.time() - 3600},
            "other date": {"asof": "2026-11-13"},
            "malformed": {"text": "window.PANORAMA={broken"},
            "wrong prefix": {"text": "var X={};"},
        }
        for name, site in cases.items():
            with self.subTest(name):
                s = self.publish_panorama(**site)
                for key in ("industries", "market", "diff"):
                    self.assertNotIn(key, s)
                self.assertNotIn("corr", s["meta"])

    def test_marketdata_publishes_nothing(self):
        e = Env(self)
        self.assertEqual(mm_job.publish("marketdata", e.work, e.out), 0)
        self.assertEqual(os.listdir(e.out), [])

    def test_missing_output_fails_the_job(self):
        e = Env(self)
        self.assertEqual(mm_job.publish("margin", e.work, e.out), mm_job.EXIT_OUTPUT_MISSING)
        self.assertEqual(os.listdir(e.out), [])

    def test_risk_cites_only_inputs_the_store_installed(self):
        e = Env(self)
        data = os.path.dirname(e.work)
        write(os.path.join(e.work, "margin_scan", "out", "payload.json"), margin_payload())
        write(os.path.join(e.work, "workspace", "analysis", "out", "sentiment", "monitor.json"), sentiment_monitor())
        # Unpublished margin output (e.g. its run failed later) is never cited.
        mm_job.publish("sentiment", e.work, e.out)
        self.assertNotIn("margin", e.outputs()["risk"]["summary"])
        # Published but not (yet) installed by the store: not cited either.
        mm_job.publish("margin", e.work, e.out)
        for name in os.listdir(e.out):
            os.remove(os.path.join(e.out, name))
        mm_job.publish("sentiment", e.work, e.out)
        self.assertNotIn("margin", e.outputs()["risk"]["summary"])
        # A plain .json is not an installed v2 snapshot.
        write(os.path.join(data, "snapshots", "margin", "2026-11-18.json"), "{}")
        mm_job.publish("sentiment", e.work, e.out)
        self.assertNotIn("margin", e.outputs()["risk"]["summary"])
        # Once the store holds that margin snapshot, risk cites it.
        write(os.path.join(data, "snapshots", "margin", "2026-11-18.json.gz"), "{}")
        mm_job.publish("sentiment", e.work, e.out)
        r = e.outputs()["risk"]
        self.check_snapshot(r, "risk", "2026-11-19")  # latest input date
        s = r["summary"]
        self.assertEqual(s["inputs"], {"margin": "2026-11-18", "sentiment": "2026-11-19"})
        self.assertEqual(s["margin"]["lever_ratio"], 2.56)
        self.assertEqual(s["sentiment"]["breadth"], 4.8)
        self.assertNotIn("etf", s)

    def test_a_broken_risk_input_does_not_fail_the_job(self):
        e = Env(self)
        bad = margin_payload()
        bad["overview"]["lever_series"]["ratio"] = []
        write(os.path.join(e.work, "margin_scan", "out", "payload.json"), bad)
        self.assertEqual(mm_job.publish("margin", e.work, e.out), 0)
        write(os.path.join(e.work, "workspace", "analysis", "out", "sentiment", "monitor.json"), sentiment_monitor())
        self.assertEqual(mm_job.publish("sentiment", e.work, e.out), 0)
        self.assertIn("sentiment", e.outputs())

    def test_output_is_strict_json(self):
        e = Env(self)
        write(os.path.join(e.work, "margin_scan", "out", "payload.json"), margin_payload())
        mm_job.publish("margin", e.work, e.out)
        with open(os.path.join(e.out, "margin.json"), encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn("NaN", raw)
        json.loads(raw, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))

    def test_clean(self):
        self.assertEqual(mm_job.clean({"a": [1.0, float("nan"), {"b": -math.inf}]}), {"a": [1.0, None, {"b": None}]})


# The history column sets of docs/store-v2.md, spelled out independently of
# the converter's own table.
MARGIN_SCHEMA = (
    [("code", "string"), ("name", "string")]
    + [(c, "double") for c in ("price", "chg", "rz", "ratio", "dratio20", "rz_chg5", "rz_chg20",
                               "buf_call", "buf_liq", "pnl", "score", "frag")]
    + [("state", "string"), ("level", "string"), ("tags", "string")])
PANORAMA_SCHEMA = (
    [("code", "string"), ("name", "string"), ("sw1", "string")]
    + [(c, "double") for c in ("price", "mktcap", "pe", "pb", "roe", "upside")]
    + [("label", "string"), ("quad", "string"), ("profile", "string")]
    + [(c, "double") for c in ("s_value", "s_growth", "s_cyclical", "s_dividend", "s_momentum", "s_quality")])
ETF_SCHEMA = [("code", "string"), ("name", "string"), ("cat", "string"), ("cum_ytd", "double"), ("cum20", "double")]


def margin_rows():
    """Rows shaped like the real 2026-11-16 data: many more fields than the
    history keeps, nulls where the source had none."""
    return [
        {"code": "600000", "name": "A", "py": "A", "price": 10.5, "chg": -1.2, "rz": 3.0, "ratio": 2.0,
         "dratio20": 0.1, "rz_chg5": 1.0, "rz_chg20": 2.0, "buf_call": 30.0, "buf_liq": 40.0, "pnl": -5.0,
         "score": 70.0, "frag": 90.0, "state": "临界", "level": "高", "tags": "a|b", "res_detail": "x",
         "pld_n": None},
        {"code": "000001", "name": "B", "price": 9.0, "chg": 0.5, "rz": 1.0, "ratio": 1.0, "dratio20": None,
         "rz_chg5": None, "rz_chg20": 0.0, "buf_call": 1.0, "buf_liq": 2.0, "pnl": 3.0, "score": None,
         "frag": None, "state": "安全", "level": "低", "tags": ""},
    ]


@needs_pyarrow
class History(unittest.TestCase):
    def write_margin(self, e, rows=None):
        payload = margin_payload()
        if rows is not None:
            fields = sorted({k for r in rows for k in r})
            payload["fields"] = fields
            payload["rows"] = {f: [r.get(f) for r in rows] for f in fields}
        write(os.path.join(e.work, "margin_scan", "out", "payload.json"), payload)

    def history(self, e, module):
        return pq.read_table(os.path.join(e.out, module + ".history.parquet"))

    def check_schema(self, table, expected):
        self.assertEqual([(f.name, str(f.type)) for f in table.schema], expected)
        self.assertTrue(all(f.nullable for f in table.schema))

    def test_margin_schema_is_exactly_the_specified_columns(self):
        e = Env(self)
        self.write_margin(e, margin_rows())
        self.assertEqual(mm_job.publish("margin", e.work, e.out), 0)
        table = self.history(e, "margin")
        self.check_schema(table, MARGIN_SCHEMA)
        self.assertEqual(table.num_rows, 2)
        first = table.to_pylist()[0]
        self.assertEqual((first["code"], first["name"], first["price"], first["tags"]), ("600000", "A", 10.5, "a|b"))
        self.assertNotIn("py", first)
        self.assertIsNone(table.to_pylist()[1]["dratio20"])

    def test_a_column_the_snapshot_lacks_is_null_not_missing(self):
        e = Env(self)
        self.write_margin(e)  # the shared payload only has code, name, frag, state
        mm_job.publish("margin", e.work, e.out)
        table = self.history(e, "margin")
        self.check_schema(table, MARGIN_SCHEMA)
        self.assertEqual(table.column("price").null_count, 2)
        self.assertEqual(table.column("frag").to_pylist(), [90.0, None])  # NaN after clean()

    def test_panorama_schema_and_code_is_the_symbol(self):
        e = Env(self)
        payload = panorama_payload()
        payload["stocks"][0].update({"sw1": "银行", "price": 11.0, "mktcap": 2e11, "roe": 10.0, "in_pool": True,
                                     "label": "低估", "quad": "Q1", "profile": "P", "s_value": 60.0,
                                     "s_growth": None, "n_methods": 4})
        write(os.path.join(e.work, "workspace", "panorama", "data", "site_payload.json"), payload)
        mm_job.publish("panorama", e.work, e.out)
        table = self.history(e, "panorama")
        self.check_schema(table, PANORAMA_SCHEMA)
        rows = table.to_pylist()
        self.assertEqual([r["code"] for r in rows], ["000001", "600000"])
        self.assertEqual((rows[0]["sw1"], rows[0]["mktcap"], rows[0]["s_value"]), ("银行", 2e11, 60.0))
        self.assertIsNone(rows[0]["upside"])  # inf
        self.assertEqual(rows[1]["upside"], 0.1)

    def test_etf_schema(self):
        e = Env(self)
        m = etf_metrics()
        m["funds"][0]["cum_ytd"] = 12.5
        write(os.path.join(e.work, "workspace", "analysis", "panel", "data", "metrics.json"), m)
        mm_job.publish("etf", e.work, e.out)
        table = self.history(e, "etf")
        self.check_schema(table, ETF_SCHEMA)
        self.assertEqual(table.to_pylist(), [{"code": "588000", "name": "科创50ETF", "cat": "科创50",
                                              "cum_ytd": 12.5, "cum20": 414.6}])

    def test_codes_equal_the_snapshots_row_codes_in_order(self):
        e = Env(self)
        self.write_margin(e, margin_rows())
        mm_job.publish("margin", e.work, e.out)
        snap_codes = [r["code"] for r in e.outputs()["margin"]["rows"]]
        self.assertEqual(self.history(e, "margin").column("code").to_pylist(), snap_codes)

    def test_odd_values_become_null_and_are_counted(self):
        rows = margin_rows()
        rows[0]["price"] = "10.5"          # a string in a numeric column
        rows[0]["chg"] = True              # a bool is not a number
        rows[1]["chg"] = False
        rows[1]["rz"] = 7                  # an int is a number
        rows[1]["state"] = 3               # a number in a string column
        rows[1]["tags"] = None             # absent values are not "nulled"
        doc = {"as_of": "2026-11-18", "rows": rows}
        table, nulled = mm_job.history_table("margin", doc)
        self.assertEqual(table.column("price").to_pylist(), [None, 9.0])
        self.assertEqual(table.column("chg").to_pylist(), [None, None])
        self.assertEqual(table.column("rz").to_pylist(), [3.0, 7.0])
        self.assertEqual(table.column("state").to_pylist(), ["临界", None])
        self.assertEqual({k: v for k, v in nulled.items() if v}, {"price": 1, "chg": 2, "state": 1})

    def test_non_finite_and_huge_numbers_become_null(self):
        rows = [dict(margin_rows()[0], price=float("nan"), chg=float("inf"), rz=10 ** 400)]
        table, nulled = mm_job.history_table("margin", {"as_of": "2026-11-18", "rows": rows})
        self.assertEqual([table.column(c).to_pylist() for c in ("price", "chg", "rz")], [[None]] * 3)
        self.assertEqual((nulled["price"], nulled["chg"], nulled["rz"]), (1, 1, 1))

    def test_the_nulled_count_is_logged(self):
        e = Env(self)
        rows = margin_rows()
        rows[0]["price"] = "x"
        self.write_margin(e, rows)
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mm_job.publish("margin", e.work, e.out)
        self.assertIn("price=1", buf.getvalue())
        self.assertIn("history 2 rows", buf.getvalue())

    def test_file_metadata_compression_and_no_leftovers(self):
        e = Env(self)
        self.write_margin(e, margin_rows())
        mm_job.publish("margin", e.work, e.out)
        path = os.path.join(e.out, "margin.history.parquet")
        meta = pq.ParquetFile(path).metadata
        kv = {k.decode(): v.decode() for k, v in meta.metadata.items()}
        self.assertEqual({k: kv[k] for k in ("format", "module", "as_of")},
                         {"format": "market-monitor.history/1", "module": "margin", "as_of": "2026-11-18"})
        self.assertEqual(meta.row_group(0).column(0).compression, "ZSTD")
        self.assertEqual(sorted(os.listdir(e.out)), ["margin.history.parquet", "margin.json", "risk.json"])

    def test_sentiment_and_risk_have_no_history_file(self):
        e = Env(self)
        write(os.path.join(e.work, "workspace", "analysis", "out", "sentiment", "monitor.json"), sentiment_monitor())
        mm_job.publish("sentiment", e.work, e.out)
        self.assertEqual(sorted(os.listdir(e.out)), ["risk.json", "sentiment.json"])

    def test_a_failing_write_leaves_no_tmp_file_and_the_snapshot_is_still_written(self):
        # The service then refuses the run for the missing history file; the
        # converter must not crash the job or leave a half-written file, which
        # the service would refuse as an unexpected output.
        e = Env(self)
        self.write_margin(e, margin_rows())
        real = pq.write_table

        def failing(table, where, *args, **kwargs):
            with open(where, "wb") as f:
                f.write(b"PAR1 half")
            raise OSError("disk full")
        pq.write_table = failing
        self.addCleanup(lambda: setattr(pq, "write_table", real))
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(mm_job.publish("margin", e.work, e.out), 0)
        self.assertEqual(sorted(os.listdir(e.out)), ["margin.json", "risk.json"])
        self.assertIn("history not written", err.getvalue())
        self.assertIn("disk full", err.getvalue())

    def test_the_tables_match_the_specification_independently(self):
        self.assertEqual({m: [(n, {"s": "string", "d": "double"}[k]) for n, k in c]
                          for m, c in mm_job.HISTORY_COLUMNS.items()},
                         {"margin": MARGIN_SCHEMA, "panorama": PANORAMA_SCHEMA, "etf": ETF_SCHEMA})


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Run(unittest.TestCase):
    """run() end to end with fake pipeline scripts."""

    def setUp(self):
        self.e = Env(self)
        self.src = os.path.join(self.e.root, "src")
        self.data = os.path.join(self.e.root, "data")
        self.work = os.path.join(self.data, "work")
        self.link = os.path.join(self.e.root, "prefix")
        os.makedirs(self.data)
        os.symlink(self.work, self.link)
        saved = (mm_job.SERVER_CMD, mm_job.SERVER_WAIT)
        self.addCleanup(lambda: setattr(mm_job, "SERVER_CMD", saved[0]) or setattr(mm_job, "SERVER_WAIT", saved[1]))

    def margin_script(self, body):
        write(os.path.join(self.src, "margin_scan", "fixture.json"), margin_payload())
        write(os.path.join(self.src, "margin_scan", "update.sh"), "#!/bin/sh\nset -e\n" + body)

    def run_job(self, job):
        return mm_job.run(job, self.src, self.data, self.e.out, self.link)

    def test_publishes_fresh_output(self):
        self.margin_script("mkdir -p out\ncp fixture.json out/payload.json\n")
        self.assertEqual(self.run_job("margin"), 0)
        self.assertEqual(sorted(self.e.outputs()), ["margin", "risk"])

    def test_a_job_run_leaves_the_data_root_checkpoint_safe(self):
        # The script hard-links a file, as the bar store's snapshots did.
        self.margin_script("mkdir -p out\ncp fixture.json out/payload.json\nln out/payload.json out/linked.json\n")
        os.makedirs(self.work)
        os.symlink(sys.prefix, os.path.join(self.work, "venv"))
        self.assertEqual(self.run_job("margin"), 0)
        self.assertEqual(checkpoint_unsafe(self.data), [])

    def test_refuses_output_this_run_did_not_write(self):
        self.margin_script("exit 0\n")
        write(os.path.join(self.work, "margin_scan", "out", "payload.json"), margin_payload())
        old = time.time() - 3600
        os.utime(os.path.join(self.work, "margin_scan", "out", "payload.json"), (old, old))
        self.assertEqual(self.run_job("margin"), mm_job.EXIT_NOT_REFRESHED)
        self.assertEqual(os.listdir(self.e.out), [])

    def test_clears_locks_left_by_a_killed_run(self):
        # The pipeline skips (exit 0) while its lock looks alive; a killed run
        # leaves the lock behind, and a reused pid makes it look alive.
        self.margin_script('if [ -f .update.lock ] && kill -0 "$(cat .update.lock)" 2>/dev/null; then exit 0; fi\n'
                           "mkdir -p out\ncp fixture.json out/payload.json\n")
        write(os.path.join(self.work, "margin_scan", ".update.lock"), str(os.getpid()))
        os.makedirs(os.path.join(self.work, "MarketData", ".mdwrite.lock"))
        self.assertEqual(self.run_job("margin"), 0)
        self.assertFalse(os.path.exists(os.path.join(self.work, "MarketData", ".mdwrite.lock")))

    def test_pipeline_failure_publishes_nothing(self):
        self.margin_script("mkdir -p out\ncp fixture.json out/payload.json\nexit 9\n")
        self.assertEqual(self.run_job("margin"), 9)
        self.assertEqual(os.listdir(self.e.out), [])

    def test_refuses_a_prefix_link_that_points_elsewhere(self):
        os.remove(self.link)
        os.symlink(self.e.root, self.link)
        self.margin_script("mkdir -p out\ncp fixture.json out/payload.json\n")
        self.assertEqual(self.run_job("margin"), mm_job.EXIT_ENVIRONMENT)

    def test_fails_when_the_data_server_never_listens(self):
        mm_job.SERVER_CMD, mm_job.SERVER_WAIT = ["true"], 1
        write(os.path.join(self.src, "workspace", "panorama", "daily_update.sh"), "#!/bin/sh\nexit 0\n")
        os.makedirs(os.path.join(self.src, "stock_server"))
        self.assertEqual(self.run_job("panorama"), mm_job.EXIT_ENVIRONMENT)

    def test_etf_does_not_need_the_data_server(self):
        mm_job.SERVER_CMD, mm_job.SERVER_WAIT = ["true"], 1
        write(os.path.join(self.src, "workspace", "analysis", "panel", "fixture.json"), etf_metrics())
        write(os.path.join(self.src, "workspace", "analysis", "panel", "refresh.sh"),
              "#!/bin/sh\nset -e\nmkdir -p data\ncp fixture.json data/metrics.json\n")
        self.assertEqual(self.run_job("etf"), 0)

    def test_refuses_to_start_when_the_port_is_taken(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            os.environ["MM_STOCK_SERVER_PORT"] = str(busy.getsockname()[1])
            self.addCleanup(os.environ.pop, "MM_STOCK_SERVER_PORT")
            write(os.path.join(self.src, "workspace", "panorama", "daily_update.sh"), "#!/bin/sh\nexit 0\n")
            os.makedirs(os.path.join(self.src, "stock_server"))
            self.assertEqual(self.run_job("panorama"), mm_job.EXIT_ENVIRONMENT)

    def test_starts_the_data_server_for_the_job_and_stops_it(self):
        port = free_port()
        os.environ["MM_STOCK_SERVER_PORT"] = str(port)
        self.addCleanup(os.environ.pop, "MM_STOCK_SERVER_PORT")
        server = ("import os,socket,time\ns=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)\n"
                  "s.bind(('127.0.0.1',int(os.environ['MCP_PORT'])));s.listen();print('server up',flush=True);time.sleep(60)\n")
        mm_job.SERVER_CMD, mm_job.SERVER_WAIT = [sys.executable, "-c", server], 10
        os.makedirs(os.path.join(self.src, "stock_server"))
        write(os.path.join(self.src, "workspace", "panorama", "fixture.json"), panorama_payload())
        write(os.path.join(self.src, "workspace", "panorama", "daily_update.sh"),
              "#!/bin/sh\nset -e\n"
              f"\"$PY\" -c \"import socket; socket.create_connection(('127.0.0.1', {port}), 2)\"\n"
              "mkdir -p data\ncp fixture.json data/site_payload.json\n")
        self.assertEqual(self.run_job("panorama"), 0)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), 1).close()
        with open(os.path.join(self.work, "stock_server", "server.log"), encoding="utf-8") as f:
            self.assertIn("server up", f.read())  # kept out of the job log


class ReferenceData(unittest.TestCase):
    """Hand-curated tables the jobs need and no script produces; they ship
    with the pipeline code (and are copied into the work dir)."""

    def test_reference_tables_are_present(self):
        for rel, header in (
            ("workspace/analysis/panel/feed/universe.csv", "基金代码"),
            ("workspace/panorama/data/code_name.csv", "code"),
            ("workspace/panorama/data/div_seed.csv", "code"),
        ):
            path = os.path.join(HERE, "..", rel)
            with open(path, encoding="utf-8-sig") as f:
                self.assertTrue(f.readline().startswith(header), rel)
                self.assertGreater(sum(1 for _ in f), 100, rel)


if __name__ == "__main__":
    unittest.main()
