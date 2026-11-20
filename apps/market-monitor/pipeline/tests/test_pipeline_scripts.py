"""Fixes to the imported pipeline scripts that decide whether stale data can
be published: they must report failure, not exit 0."""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

PIPELINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def port_open(port):
    try:
        socket.create_connection(("127.0.0.1", port), 0.5).close()
        return True
    except OSError:
        return False


class MarketDataUpdate(unittest.TestCase):
    def run_update(self, update_exit, check_exit):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        md = os.path.join(tmp.name, "MarketData")
        os.makedirs(md)
        for name in ("update.sh", "locklib.sh"):
            shutil.copy(os.path.join(PIPELINE, "MarketData", name), md)
        with open(os.path.join(md, "trading_day.py"), "w") as f:
            f.write("print('2026-11-18')\n")
        with open(os.path.join(md, "market_data.py"), "w") as f:
            f.write("import sys\n"
                    f"sys.exit({{'update': {update_exit}, 'check': {check_exit}}}.get(sys.argv[1], 0))\n")
        env = dict(os.environ, MD_HOME=md, PY=sys.executable)
        return subprocess.run(["bash", "update.sh"], cwd=md, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode

    def test_a_failed_update_is_reported(self):
        self.assertEqual(self.run_update(1, 0), 1)

    def test_a_failed_check_is_reported(self):
        self.assertEqual(self.run_update(0, 4), 4)

    def test_success_is_zero(self):
        self.assertEqual(self.run_update(0, 0), 0)


def importable(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


@unittest.skipUnless(importable("requests"), "needs the pipeline's dependencies (requests)")
@unittest.skipIf(port_open(8091), "something listens on 8091")
class PanoramaFreshness(unittest.TestCase):
    def test_unreachable_calendar_blocks_publication(self):
        env = dict(os.environ, PANORAMA_ASOF="2026-11-18")
        p = subprocess.run([sys.executable, "check_freshness.py"], env=env, capture_output=True, text=True,
                           cwd=os.path.join(PIPELINE, "workspace", "panorama"))
        self.assertNotEqual(p.returncode, 0)
        self.assertTrue(p.stdout.strip().splitlines()[-1].startswith("STALE"), p.stdout)



FAKE_PY = r'''#!/bin/sh
# Records each call; creates the outputs a step would write.
echo "$*" >> "$CALLS"
case "$*" in
  *-c*) exit 0 ;;
  *build_report.py*) exit 1 ;;   # the HTML builder fails without its vendored JS
  *build_data.py*) mkdir -p out; echo '{"meta":{"as_of":"2026-11-18"}}' > out/payload.json; echo 'x' > out/payload.js ;;
  *metrics.py*) mkdir -p data; echo '{}' > data/metrics.json ;;
  *build.py*|*selfcheck.py*) exit 1 ;;
esac
exit 0
'''


class SkipHtml(unittest.TestCase):
    """With MM_NO_HTML=1 the scripts compute their data and skip the HTML
    steps, which need vendored echarts/mermaid the app does not ship."""

    def run_script(self, rel_dir, script, extra_files=(), no_html="1"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = os.path.join(tmp.name, "work")
        shutil.copytree(os.path.join(PIPELINE, rel_dir), os.path.join(work, rel_dir))
        for rel in extra_files:
            os.makedirs(os.path.dirname(os.path.join(work, rel)), exist_ok=True)
            open(os.path.join(work, rel), "w").close()
        fake = os.path.join(tmp.name, "py")
        with open(fake, "w") as f:
            f.write(FAKE_PY)
        os.chmod(fake, 0o755)
        calls = os.path.join(tmp.name, "calls")
        env = dict(os.environ, PY=fake, CALLS=calls, HOME=work, MM_NO_HTML=no_html, PANORAMA_ASOF="2026-11-18")
        p = subprocess.run(["bash", script], cwd=os.path.join(work, rel_dir), env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        with open(calls) as f:
            return p.returncode, f.read(), p.stdout

    def test_margin(self):
        code, calls, out = self.run_script("margin_scan", "update.sh", ["margin_scan/src/.keep"])
        self.assertEqual(code, 0, out)
        self.assertIn("build_data.py", calls)
        self.assertNotIn("build_report.py", calls)

    def test_html_is_still_built_without_the_flag(self):
        # Outside the app (the production host) the pages are still built;
        # the fake builder fails, so the script stops at that step.
        for no_html in ("", "0"):
            code, calls, out = self.run_script("margin_scan", "update.sh", ["margin_scan/src/.keep"], no_html)
            self.assertIn("build_report.py", calls, no_html)

    def test_etf(self):
        code, calls, out = self.run_script("workspace/analysis/panel", "refresh.sh")
        self.assertEqual(code, 0, out)
        self.assertIn("metrics.py", calls)
        for step in ("build.py", "build_report.py", "selfcheck.py"):
            self.assertNotIn(" " + step if step == "build.py" else step, " " + calls.replace("\n", " "), step)

    def test_panorama(self):
        code, calls, out = self.run_script("workspace/panorama", "daily_update.sh")
        self.assertEqual(code, 0, out)
        self.assertIn("export_site.py", calls)
        self.assertNotIn("build_report.py", calls)



class ExternalSourcesUseHttps(unittest.TestCase):
    """Backend egress goes through an HTTPS CONNECT proxy (HTTPS_PROXY only), so a
    plain-http source would not reach it. The quotes API is addressed by its HTTPS
    name (QUOTE_API), never by the old plain-http IP."""

    def test_no_plain_http_source_to_a_public_host(self):
        import re
        bad = []
        for root, dirs, files in os.walk(PIPELINE):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8", errors="replace") as f:
                    for n, line in enumerate(f, 1):
                        for m in re.finditer(r"http://([A-Za-z0-9._-]+)", line):
                            host = m.group(1)
                            if host in ("localhost", "127.0.0.1") or host.startswith("<"):
                                continue
                            bad.append("%s:%d %s" % (os.path.relpath(path, PIPELINE), n, host))
        self.assertEqual(bad, [])

    def test_quote_api_is_configurable_and_https(self):
        import re
        users = ["MarketData/trading_day.py", "MarketData/bulk_pull.py",
                 "MarketData/fetch_catalog.py", "stock_server/stock_mcp_integrated.py",
                 "stock_server/stock_mcp_server.py"]
        for rel in users:
            with open(os.path.join(PIPELINE, rel), encoding="utf-8") as f:
                src = f.read()
            self.assertIn('os.environ.get("QUOTE_API", "https://', src, rel)
            self.assertIsNone(re.search(r"\b\d{1,3}(\.\d{1,3}){3}:8000", src), rel)


if __name__ == "__main__":
    unittest.main()
