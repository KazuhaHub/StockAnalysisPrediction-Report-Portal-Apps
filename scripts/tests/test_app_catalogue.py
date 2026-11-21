"""The catalogue writer refuses what the Portal's ParseCatalogue would refuse, and the OCI package layout is exact."""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


catalogue = load("app_catalogue", "app-catalogue.py")
push = load("push_oci_package", "push-oci-package.py")

BASE = "https://raw.githubusercontent.com/Owner/Apps/0123456789abcdef0123456789abcdef01234567/packages/market-monitor"
REPOSITORY = "ghcr.io/owner/apps/market-monitor"
DIGEST = "sha256:" + "ab" * 32


def descriptor(version="0.1.0-beta.1", app="market-monitor"):
    return json.dumps({"format": "portal.app/v2", "id": app, "version": version, "publisher": "kazuha-hub"}).encode()


def add(current, version="0.1.0-beta.1", digest=DIGEST):
    return catalogue.add_release(current, descriptor(version), BASE + "/" + version + "/descriptor.json",
                                 BASE + "/" + version + "/descriptor.sig", REPOSITORY, digest)


class AddTests(unittest.TestCase):
    def test_first_release_starts_an_empty_catalogue(self):
        doc = json.loads(add(None))
        self.assertEqual(doc["format"], "portal.catalogue/2-dev.3")
        release = doc["releases"][0]
        self.assertEqual(release["descriptor_sha256"], hashlib.sha256(descriptor()).hexdigest())
        self.assertEqual(release["publisher_id"], "kazuha-hub")
        self.assertEqual(release["package_oci"], {"repository": REPOSITORY, "digest": DIGEST})
        self.assertNotIn("package_url", release)

    def test_appends_and_keeps_earlier_entries(self):
        second = json.loads(add(add(None), "0.1.0-beta.2"))
        self.assertEqual([r["version"] for r in second["releases"]], ["0.1.0-beta.1", "0.1.0-beta.2"])

    def test_duplicate_app_and_version_refused(self):
        with self.assertRaises(catalogue.CatalogueError):
            add(add(None))

    def test_full_catalogue_refused(self):
        current = None
        for index in range(catalogue.MAX_RELEASES):
            current = add(current, "1.0." + str(index))
        with self.assertRaises(catalogue.CatalogueError):
            add(current, "2.0.0")

    def test_older_format_is_not_extended(self):
        old = json.dumps({"format": "portal.catalogue/2-dev.2", "releases": []}).encode()
        with self.assertRaises(catalogue.CatalogueError):
            add(old)

    def test_bad_digest_or_repository_refused(self):
        for repository, digest in [(REPOSITORY, "sha256:abc"), (REPOSITORY, "ab" * 32), ("Ghcr.io/Owner/x", DIGEST), ("ghcr.io", DIGEST)]:
            with self.subTest(repository=repository, digest=digest), self.assertRaises(catalogue.CatalogueError):
                catalogue.add_release(None, descriptor(), BASE + "/d.json", BASE + "/d.sig", repository, digest)


class ParseTests(unittest.TestCase):
    def doc(self, fmt="portal.catalogue/2-dev.3", **release):
        entry = {"app_id": "a", "publisher_id": "p", "version": "1.0.0", "descriptor_sha256": "0" * 64,
                 "descriptor_url": BASE + "/d.json", "signature_url": BASE + "/d.sig"}
        entry.update(release)
        return json.dumps({"format": fmt, "releases": [entry]}).encode()

    def test_valid(self):
        catalogue.parse(self.doc(package_oci={"repository": REPOSITORY, "digest": DIGEST}))
        catalogue.parse(self.doc(fmt="portal.catalogue/2-dev.2", package_url=BASE + "/a.portalapp"))
        catalogue.parse(self.doc())

    def test_refusals(self):
        oci = {"repository": REPOSITORY, "digest": DIGEST}
        for case in [
            self.doc(version="01.0.0"), self.doc(version="1.0.0-01"), self.doc(app_id="A"), self.doc(descriptor_sha256="x"),
            self.doc(descriptor_url="http://example.com/d"), self.doc(descriptor_url=BASE + "/d?x=1"),
            self.doc(descriptor_url="https://u@example.com/d"), self.doc(descriptor_url="https://example.com:8443/d"),
            self.doc(descriptor_url="https://example.com/a/../d"), self.doc(descriptor_url="https://example.com/a%20b"),
            self.doc(extra="x"), b"", b"[]", b'{"format":"portal.catalogue/2-dev.3","releases":null}',
            b'{"format":"portal.catalogue/2-dev.3","releases":[],"releases":[]}',
            b'{"format":"portal.catalogue/1","releases":[]}',
            self.doc(package_oci={"repository": REPOSITORY}), self.doc(package_oci=dict(oci, extra="x")),
            self.doc(package_oci="ghcr.io/x/y"), self.doc(package_oci=dict(oci, digest="sha512:" + "a" * 128)),
            self.doc(fmt="portal.catalogue/2-dev.2", package_oci=oci), self.doc(package_url=BASE + "/a"),
            self.doc(package_oci=oci, package_url=BASE + "/a"),
        ]:
            with self.subTest(case=case[:90]), self.assertRaises(catalogue.CatalogueError):
                catalogue.parse(case)

    def test_duplicate_identity_or_digest_refused(self):
        doc = json.loads(self.doc())
        doc["releases"].append(dict(doc["releases"][0], version="1.0.1"))
        with self.assertRaises(catalogue.CatalogueError):
            catalogue.parse(json.dumps(doc).encode())


class ManifestTests(unittest.TestCase):
    def test_layout(self):
        raw, digest = push.build_manifest("sha256:" + "cd" * 32, 123, {"org.opencontainers.image.version": "1"})
        manifest = json.loads(raw)
        self.assertEqual(digest, "sha256:" + hashlib.sha256(raw).hexdigest())
        self.assertEqual(manifest["mediaType"], "application/vnd.oci.image.manifest.v1+json")
        self.assertEqual(manifest["artifactType"], "application/vnd.portal.app.package.v2")
        self.assertEqual(manifest["config"], {"mediaType": "application/vnd.oci.empty.v1+json", "digest": push.EMPTY_DIGEST, "size": 2})
        self.assertEqual(manifest["layers"], [{"mediaType": "application/vnd.portal.app.package.v2+zip", "digest": "sha256:" + "cd" * 32, "size": 123}])

    def test_empty_descriptor_is_the_hash_of_braces(self):
        self.assertEqual(push.EMPTY_DIGEST, "sha256:" + hashlib.sha256(b"{}").hexdigest())

    def test_reproducible(self):
        self.assertEqual(push.build_manifest("sha256:" + "cd" * 32, 1, {"b": "2", "a": "1"}), push.build_manifest("sha256:" + "cd" * 32, 1, {"a": "1", "b": "2"}))

    def test_repository_names(self):
        for bad in ["ghcr.io", "GHCR.io/a/b", "ghcr.io/a b/c", "ghcr.io//b"]:
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                push.Registry(bad)


if __name__ == "__main__":
    unittest.main()
