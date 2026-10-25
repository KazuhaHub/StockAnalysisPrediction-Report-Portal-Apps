import hashlib
import importlib.util
import io
import json
from pathlib import Path
import platform
import tarfile
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("released_lifecycle", Path(__file__).parents[1] / "status-released-lifecycle.py")
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)


class ReleasedLifecycleTests(unittest.TestCase):
    def fixture(self, root, scopes=None, member=None):
        target = {"Darwin": "darwin", "Linux": "linux"}[platform.system()]
        arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}[platform.machine()]
        archive_name = f"status-v0.1.0-fixture-{target}-{arch}.tar.gz"
        with zipfile.ZipFile(root / "status.zip", "w") as bundle:
            bundle.writestr("app.json", json.dumps({"id": "status", "version": "0.1.0-fixture",
                                                  "scopes": scopes or ["extension.read", "extension.manage"]}))
        with tarfile.open(root / archive_name, "w:gz") as archive:
            info = member or tarfile.TarInfo("status")
            info.mode = 0o755
            data = b"fixture executable bytes"
            info.size = len(data) if info.isfile() else 0
            archive.addfile(info, io.BytesIO(data) if info.isfile() else None)
        metadata = {"app_id": "status", "version": "0.1.0-fixture", "artifacts": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in [archive_name, "status.zip"]}}
        (root / "release.json").write_text(json.dumps(metadata))

    def test_checksum_failure_prevents_extracting_or_running_a_release(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "status.zip").write_bytes(b"changed after review")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                lifecycle.release(root, root / "extracted")
            self.assertFalse((root / "extracted").exists())

    def test_permission_expansion_is_not_accepted_as_a_routine_upgrade(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root, scopes=["extension.read", "extension.manage", "query"])
            with self.assertRaisesRegex(RuntimeError, "permission change"):
                lifecycle.release(root, root / "extracted")
            self.assertFalse((root / "extracted").exists())

    def test_archive_links_and_traversal_are_refused_even_with_matching_hashes(self):
        for name, kind in [("../status", tarfile.REGTYPE), ("status", tarfile.SYMTYPE)]:
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                info = tarfile.TarInfo(name)
                info.type = kind
                info.linkname = "../../outside"
                self.fixture(root, member=info)
                with self.assertRaisesRegex(RuntimeError, "archive contents"):
                    lifecycle.release(root, root / "extracted")
                self.assertFalse((root / "status").exists())
