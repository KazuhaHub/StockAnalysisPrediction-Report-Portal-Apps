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


if __name__ == "__main__":
    unittest.main()
