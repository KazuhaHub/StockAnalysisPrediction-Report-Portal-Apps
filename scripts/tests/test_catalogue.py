import importlib.util
import json
import tempfile
import unittest
import zipfile
import io
import hashlib
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

    def extension_release(self):
        self.manifest["scopes"] = ["extension.read", "extension.manage"]
        (self.root / "apps/sample/app.json").write_text(json.dumps(self.manifest))
        self.entry["scopes"] = self.manifest["scopes"]
        self.save([self.entry])
        folder = self.root / "apps/sample/releases"
        folder.mkdir()
        self.record = {"schema_version": 1, "app_id": "sample", "version": "1.0.0",
                       "minimum_portal_release": "v2026.43.2"}
        self.record_path = folder / "1.0.0.json"
        self.record_path.write_text(json.dumps(self.record))
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            z.writestr("app.json", json.dumps(self.manifest))
            z.writestr("index.html", "<!doctype html><title>Sample</title>")
        self.bundle = data.getvalue()
        self.metadata = {**self.record, "tag": "sample/v1.0.0",
                         "source_commit": "a" * 40,
                         "artifacts": {"sample.zip": hashlib.sha256(self.bundle).hexdigest()}}
        self.base = self.entry["url"].rsplit("/", 1)[0]
        self.portal_url = "https://api.github.com/repos/KazuhaHub/StockAnalysisPrediction-Report-Portal/releases/tags/v2026.43.2"
        self.release_url = "https://api.github.com/repos/example/apps/releases/tags/sample%2Fv1.0.0"
        self.responses = {
            self.entry["url"]: self.bundle,
            self.base + "/release.json": json.dumps(self.metadata).encode(),
            self.portal_url: json.dumps({"tag_name": "v2026.43.2", "draft": False, "published_at": "2026-10-24T00:00:00Z"}).encode(),
            self.release_url: json.dumps({"tag_name": "sample/v1.0.0", "draft": False, "published_at": "2026-10-24T00:00:00Z"}).encode(),
            "https://api.github.com/repos/example/apps/git/ref/tags/sample%2Fv1.0.0": json.dumps({"object": {"type": "tag", "sha": "b" * 40}}).encode(),
            "https://api.github.com/repos/example/apps/git/tags/" + "b" * 40: json.dumps({"object": {"type": "commit", "sha": "a" * 40}}).encode(),
        }
        self.update_sums()

    def update_sums(self):
        raw = json.dumps(self.metadata).encode()
        self.responses[self.base + "/release.json"] = raw
        self.responses[self.base + "/SHA256SUMS"] = (
            hashlib.sha256(self.bundle).hexdigest() + "  sample.zip\n" +
            hashlib.sha256(raw).hexdigest() + "  release.json\n").encode()

    def test_released_extension_requires_record_and_supported_portal(self):
        self.extension_release()
        self.assertEqual(c.check(self.root), 1)
        for key, value in [("version", "9.0.0"), ("app_id", "other"),
                           ("minimum_portal_release", "v2026.43.1"),
                           ("minimum_portal_release", "latest")]:
            self.record_path.write_text(json.dumps({**self.record, key: value}))
            with self.assertRaises(ValueError): c.check(self.root)

    def test_online_release_checks_publication_bundle_and_metadata(self):
        self.extension_release()
        fetch = lambda url, limit: self.responses[url]
        self.assertEqual(c.check(self.root, verify_downloads=True, fetch=fetch), 1)
        good = dict(self.responses)
        for url, raw in [(self.entry["url"], self.bundle + b"tampered"),
                         (self.portal_url, b'{"draft":true}'),
                         (self.release_url, b'{"draft":true}'),
                         (self.base + "/SHA256SUMS", b"malformed")]:
            self.responses = {**good, url: raw}
            with self.assertRaises(ValueError): c.check(self.root, verify_downloads=True, fetch=fetch)
        self.responses = good
        self.metadata["source_commit"] = "c" * 40
        self.update_sums()
        with self.assertRaises(ValueError): c.check(self.root, verify_downloads=True, fetch=fetch)
        self.metadata["source_commit"] = "a" * 40
        self.metadata["minimum_portal_release"] = "v2026.43.1"
        self.update_sums()
        with self.assertRaises(ValueError): c.check(self.root, verify_downloads=True, fetch=fetch)

    def test_release_path_cannot_hide_extra_repository_segments(self):
        self.save([{**self.entry, "url": "https://github.com/example/apps/extra/releases/download/sample%2Fv1.0.0/sample.zip"}])
        with self.assertRaises(ValueError): c.check(self.root)

    def test_rehashed_archive_cannot_change_permissions_or_escape_paths(self):
        self.extension_release()
        for name, contents in [("app.json", json.dumps({**self.manifest, "scopes": ["query"]})),
                               ("../private.txt", "private")]:
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as z:
                z.writestr("index.html", "<!doctype html><title>Sample</title>")
                if name != "app.json": z.writestr("app.json", json.dumps(self.manifest))
                z.writestr(name, contents)
            self.bundle = data.getvalue()
            self.responses[self.entry["url"]] = self.bundle
            self.metadata["artifacts"]["sample.zip"] = hashlib.sha256(self.bundle).hexdigest()
            self.update_sums()
            with self.assertRaises(ValueError):
                c.check(self.root, verify_downloads=True, fetch=lambda url, limit: self.responses[url])

    def test_development_catalogue_versions_are_refused(self):
        for version in ["1.0.0-dev", "1.0.0-beta.dev", "1.0.0-snapshot"]:
            self.manifest["version"] = version
            (self.root / "apps/sample/app.json").write_text(json.dumps(self.manifest))
            self.save([{**self.entry, "version": version, "url": "https://github.com/example/apps/releases/download/sample%2Fv" + version + "/sample.zip"}])
            with self.assertRaises(ValueError): c.check(self.root)
