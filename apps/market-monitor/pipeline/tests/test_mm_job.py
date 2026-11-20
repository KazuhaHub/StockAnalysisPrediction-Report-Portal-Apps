"""Tests for the job entry: work-dir preparation, job dispatch and the
conversion of each module's output into a snapshot document."""
import json
import math
import os
import socket
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mm_job  # noqa: E402

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

    def test_corrects_a_stale_venv_link(self):
        e = Env(self)
        src = os.path.join(e.root, "src")
        os.makedirs(src)
        os.makedirs(e.work)
        os.symlink("/nonexistent/venv", os.path.join(e.work, "venv"))
        mm_job.prepare_work(src, e.work)
        self.assertEqual(os.path.realpath(os.path.join(e.work, "venv")), os.path.realpath(sys.prefix))

    def test_links_the_running_interpreter_as_the_pipeline_venv(self):
        e = Env(self)
        src = os.path.join(e.root, "src")
        os.makedirs(src)
        mm_job.prepare_work(src, e.work)
        self.assertTrue(os.path.exists(os.path.join(e.work, "venv", "bin", "python3")))


class Dispatch(unittest.TestCase):
    def test_unknown_job_exits_2(self):
        self.assertEqual(mm_job.main(["mm_job.py", "nope"]), 2)
        self.assertEqual(mm_job.main(["mm_job.py"]), 2)

    def test_every_service_job_is_known(self):
        self.assertEqual(sorted(mm_job.JOBS), ["etf", "margin", "marketdata", "panorama", "sentiment"])

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
        # Once the store holds that margin snapshot, risk cites it.
        write(os.path.join(data, "snapshots", "margin", "2026-11-18.json"), "{}")
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


if __name__ == "__main__":
    unittest.main()
