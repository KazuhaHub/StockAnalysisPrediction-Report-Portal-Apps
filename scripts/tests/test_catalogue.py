import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("catalogue", Path(__file__).parents[1] / "catalogue.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        folder = self.root / "apps" / "sample"
        (folder / "frontend").mkdir(parents=True)
        self.manifest = {"id": "sample", "name": "Sample", "version": "1.0.0", "entry": "index.html", "scopes": []}
        (folder / "app.json").write_text(json.dumps(self.manifest))
        (folder / "frontend" / "index.html").write_text("<!doctype html><title>Sample</title>")
        self.entry = {**self.manifest, "url": "https://github.com/example/apps/releases/download/sample%2Fv1.0.0/sample.zip"}
        self.save([self.entry])

    def save(self, entries):
        (self.root / "index.json").write_text(json.dumps({"apps": entries}))

    def test_duplicate_or_drift_rejected(self):
        self.save([self.entry, self.entry])
        with self.assertRaises(ValueError): c.check(self.root)
        self.save([{**self.entry, "scopes": ["query"]}])
        with self.assertRaises(ValueError): c.check(self.root)

    def test_mutable_or_credential_url_rejected(self):
        for url in ["http://github.com/x.zip", "https://github.com/a/b/releases/latest/a.zip", "https://user:secret@github.com/a/b/releases/download/v1/a.zip"]:
            self.save([{**self.entry, "url": url}])
            with self.assertRaises(ValueError): c.check(self.root)

    def test_deterministic_bounded_root_archive(self):
        first = c.package("sample", self.root).read_bytes()
        second = c.package("sample", self.root)
        self.assertEqual(first, second.read_bytes())
        with zipfile.ZipFile(second) as z:
            self.assertEqual(z.namelist(), ["app.json", "index.html"])
        self.assertEqual(c.check(self.root), 1)

    def test_symlink_and_secret_files_rejected(self):
        assets = self.root / "apps/sample/frontend"
        (assets / ".env").write_text("placeholder")
        with self.assertRaises(ValueError): c.package("sample", self.root)
        (assets / ".env").unlink()
        (assets / "linked.js").symlink_to(assets / "index.html")
        with self.assertRaises(ValueError): c.package("sample", self.root)

    def test_path_escape_and_unreleased_scope_rejected(self):
        with self.assertRaises(ValueError): c.package("../outside", self.root)
        self.manifest["scopes"] = ["extension.read"]
        (self.root / "apps/sample/app.json").write_text(json.dumps(self.manifest))
        self.save([{**self.entry, "scopes": ["extension.read"]}])
        with self.assertRaises(ValueError): c.check(self.root)

    def test_symlinked_asset_root_rejected(self):
        assets = self.root / "apps/sample/frontend"
        (assets / "index.html").unlink()
        assets.rmdir()
        other = self.root / "outside"
        other.mkdir()
        (other / "index.html").write_text("private content")
        assets.symlink_to(other, target_is_directory=True)
        with self.assertRaises(ValueError): c.package("sample", self.root)

    def test_release_tag_and_asset_must_match_identity(self):
        self.save([{**self.entry, "url": "https://github.com/example/apps/releases/download/other%2Fv9.0.0/wrong.zip"}])
        with self.assertRaises(ValueError): c.check(self.root)
