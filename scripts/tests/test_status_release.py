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

    def test_unknown_or_duplicate_target_is_refused_before_building(self):
        with tempfile.TemporaryDirectory() as temporary:
            for targets in [["../escape"], ["linux-amd64", "linux-amd64"]]:
                with self.assertRaisesRegex(ValueError, "target"):
                    release.build(targets, Path(temporary))
            self.assertFalse(list(Path(temporary).iterdir()))


if __name__ == "__main__":
    unittest.main()
