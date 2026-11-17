"""The legacy Status release, container and browser tooling applies to the legacy line only."""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree(v2):
    folder = Path(tempfile.mkdtemp(prefix="status-line-", dir=os.environ.get("TMPDIR")))
    (folder / "apps/status").mkdir(parents=True)
    (folder / "apps/status/app.v2.json" if v2 else folder / "apps/status/app.json").write_text("{}")
    return folder


class StatusLineTests(unittest.TestCase):
    def test_the_line_follows_the_manifest_on_disk(self):
        line = load("status_line", "status_line.py")
        for v2 in (True, False):
            folder = tree(v2)
            self.addCleanup(shutil.rmtree, folder)
            self.assertEqual(line.uses_v2_line(folder), v2)

    def test_the_skip_message_names_the_v2_packaging_step(self):
        line = load("status_line", "status_line.py")
        message = line.skip_message("Status release build")
        self.assertIn("apps/status/app.v2.json", message)
        self.assertIn("build-app-v2.py", message)
        self.assertIn("Status release build", message)

    def test_workflow_output_and_notice_for_both_lines(self):
        line = load("status_line", "status_line.py")
        for v2, legacy in ((True, "false"), (False, "true")):
            folder = tree(v2)
            self.addCleanup(shutil.rmtree, folder)
            output = folder / "github-output"
            result = subprocess.run([sys.executable, "-I", str(SCRIPTS / "status_line.py"), "--root", str(folder), "--github-output", str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), f"legacy={legacy}\n")
            self.assertEqual("::notice " in result.stdout, v2)

    def test_container_smoke_skips_cleanly_on_the_v2_line(self):
        for v2 in (True, False):
            folder = tree(v2)
            self.addCleanup(shutil.rmtree, folder)
            (folder / "scripts").mkdir()
            for name in ("status-container-smoke.py", "status_line.py"):
                shutil.copy(SCRIPTS / name, folder / "scripts" / name)
            # On the legacy line the script goes on to need Docker, which is not
            # started here: only the v2 line must exit before touching it.
            if not v2:
                continue
            result = subprocess.run([sys.executable, "-I", str(folder / "scripts/status-container-smoke.py")], cwd=folder, capture_output=True, text=True, env={"PATH": "/nonexistent"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("build-app-v2.py", result.stdout)
            self.assertFalse(list(folder.glob("status-*")))


if __name__ == "__main__":
    unittest.main()
