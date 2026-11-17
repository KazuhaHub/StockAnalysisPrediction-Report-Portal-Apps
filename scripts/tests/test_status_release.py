"""Check reproducible service archive metadata and target validation."""
import importlib.util
import tempfile
import unittest
import tarfile
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "build-status-release.py"
spec = importlib.util.spec_from_file_location("status_release", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
line_spec = importlib.util.spec_from_file_location("status_line", Path(__file__).resolve().parents[1] / "status_line.py")
line = importlib.util.module_from_spec(line_spec)
line_spec.loader.exec_module(line)


class StatusReleaseTests(unittest.TestCase):
    def test_archives_are_reproducible_and_contain_only_the_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            binary = folder / "binary"
            binary.write_bytes(b"fixture-executable")
            for target in ["linux-amd64", "windows-amd64"]:
                first, second = folder / "first", folder / "second"
                release.archive(binary, target, first)
                release.archive(binary, target, second)
                self.assertEqual(first.read_bytes(), second.read_bytes())
                if target.startswith("windows"):
                    with zipfile.ZipFile(first) as bundle:
                        self.assertEqual(bundle.namelist(), ["status.exe"])
                        self.assertEqual(bundle.read("status.exe"), binary.read_bytes())
                else:
                    with tarfile.open(first) as bundle:
                        self.assertEqual(bundle.getnames(), ["status"])
                        info = bundle.getmember("status")
                        self.assertEqual((info.uid, info.gid, info.mtime, info.mode), (0, 0, 0, 0o755))
                        self.assertEqual(bundle.extractfile(info).read(), binary.read_bytes())

    @unittest.skipIf(line.uses_v2_line(release.ROOT), line.skip_message("The legacy Status release build test"))
    def test_unknown_or_duplicate_target_is_refused_before_building(self):
        with tempfile.TemporaryDirectory() as temporary:
            for targets in [["../escape"], ["linux-amd64", "linux-amd64"]]:
                with self.assertRaisesRegex(ValueError, "target"):
                    release.build(targets, Path(temporary))
            self.assertFalse(list(Path(temporary).iterdir()))

    def test_build_is_skipped_cleanly_on_the_v2_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "apps/status").mkdir(parents=True)
            (root / "apps/status/app.v2.json").write_text("{}")
            output = Path(temporary) / "out"
            import contextlib, io
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(release.main(["--output", str(output)], root=root), 0)
            self.assertIn("build-app-v2.py", captured.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
