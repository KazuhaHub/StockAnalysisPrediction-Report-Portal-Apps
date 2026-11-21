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
branch = load("catalogue_branch", "catalogue-branch.py")
gate = load("release_gate", "release-gate.py")

BASE = "https://raw.githubusercontent.com/Owner/Apps/0123456789abcdef0123456789abcdef01234567/packages/kazuha-hub-market-monitor"
REPOSITORY = "ghcr.io/owner/apps/kazuha-hub-market-monitor"
DIGEST = "sha256:" + "ab" * 32


def descriptor(version="0.1.0-beta.1", app="kazuha-hub-market-monitor"):
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
        catalogue.parse(self.doc(package_url=BASE + "/a.portalapp"))  # 2-dev.3 accepts package_url, as the Portal does

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
            self.doc(fmt="portal.catalogue/2-dev.2", package_oci=oci), self.doc(fmt="portal.catalogue/2-dev.1", package_url=BASE + "/a"),
            self.doc(package_oci=None), self.doc(package_url=""),
            self.doc(package_oci=oci, package_url=BASE + "/a"),
        ]:
            with self.subTest(case=case[:90]), self.assertRaises(catalogue.CatalogueError):
                catalogue.parse(case)

    def test_duplicate_identity_or_digest_refused(self):
        doc = json.loads(self.doc())
        doc["releases"].append(dict(doc["releases"][0], version="1.0.1"))
        with self.assertRaises(catalogue.CatalogueError):
            catalogue.parse(json.dumps(doc).encode())


class RepositoryGrammarTests(unittest.TestCase):
    """SplitOCIRepository: host[:443]/path, lower case, no localhost, a well-formed IPv4 literal."""

    GOOD = ["ghcr.io/owner/apps/name", "ghcr.io:443/owner/name", "ghcr.io/a__b/c--d/e.f_g", "registry.example.com/x", "1.2.3.4/x"]
    BAD = ["ghcr.io", "ghcr.io/", "ghcr.io:8443/a/b", "ghcr.io:/a/b", "GHCR.io/a/b", "ghcr.io/A/b", "ghcr.io/a/b/", "ghcr.io//b",
           "ghcr.io/a___b", "ghcr.io/a._b", "ghcr.io/a-", "ghcr.io/-a", "localhost/a", "localhost:443/a", "999.1.1.1/a", "1.2.3/a",
           "-ghcr.io/a", "ghcr..io/a", "ghcr.io/a b", "ghcr.io/a\n", "x" * 256, "ghcr.io/" + "a" * 250]

    def test_good(self):
        for repository in self.GOOD:
            with self.subTest(repository=repository):
                catalogue.split_oci_repository(repository)
                push.Registry(repository)

    def test_bad(self):
        for repository in self.BAD:
            with self.subTest(repository=repository), self.assertRaises(catalogue.CatalogueError):
                catalogue.split_oci_repository(repository)

    def test_push_script_applies_the_same_grammar_to_remote_hosts(self):
        for repository in self.BAD:
            if repository.startswith("localhost"):
                continue
            with self.subTest(repository=repository), self.assertRaises(SystemExit):
                push.Registry(repository)

    def test_local_test_registry_may_use_any_port(self):
        push.Registry("127.0.0.1:25999/kazuhahub/portal-apps/x")


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


class CheckAbsentTests(unittest.TestCase):
    def test_token_endpoint_denial_is_tolerated_too(self):
        import urllib.error
        from unittest import mock

        def denied(self):
            raise urllib.error.HTTPError("https://ghcr.io/token", 403, "x", {}, None)

        with mock.patch.object(push.Registry, "login", denied):
            self.assertEqual(push.main(["--repository", REPOSITORY, "--tag", "1.0.0", "--check-absent", "--tolerate-denied"]), 0)
            with self.assertRaises(urllib.error.HTTPError):
                push.main(["--repository", REPOSITORY, "--tag", "1.0.0", "--check-absent"])

    def run_check(self, error, extra):
        import urllib.error
        from unittest import mock

        def denied(self, tag):
            raise urllib.error.HTTPError("https://ghcr.io", error, "x", {}, None)

        with mock.patch.object(push.Registry, "login", lambda self: None), mock.patch.object(push.Registry, "tag_exists", denied):
            return push.main(["--repository", REPOSITORY, "--tag", "1.0.0", "--check-absent"] + extra)

    def test_denied_is_tolerated_only_when_asked(self):
        import urllib.error
        self.assertEqual(self.run_check(403, ["--tolerate-denied"]), 0)
        with self.assertRaises(urllib.error.HTTPError):
            self.run_check(403, [])

    def test_server_errors_are_never_tolerated(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError):
            self.run_check(500, ["--tolerate-denied"])


class CatalogueBranchTests(unittest.TestCase):
    def test_only_status_two_means_absent(self):
        self.assertTrue(branch.interpret_ls_remote(0))
        self.assertFalse(branch.interpret_ls_remote(2))
        for status in (1, 128, 255, -9):
            with self.subTest(status=status), self.assertRaises(branch.BranchError):
                branch.interpret_ls_remote(status)

    def prepare(self, ls_status):
        import subprocess
        calls = []

        def run(directory, *args, check=True):
            calls.append(args[0])
            return subprocess.CompletedProcess(args, ls_status if args[0] == "ls-remote" else 0)

        return calls, run

    def test_existing_branch_is_fetched(self):
        calls, run = self.prepare(0)
        self.assertTrue(branch.prepare("d", "https://example.com/r.git", run))
        self.assertEqual(calls, ["init", "remote", "ls-remote", "fetch", "reset"])

    def test_absent_branch_starts_orphan_without_fetching(self):
        calls, run = self.prepare(2)
        self.assertFalse(branch.prepare("d", "https://example.com/r.git", run))
        self.assertEqual(calls, ["init", "remote", "ls-remote"])

    def test_failed_ls_remote_aborts_before_anything_else(self):
        calls, run = self.prepare(128)
        with self.assertRaises(branch.BranchError):
            branch.prepare("d", "https://example.com/r.git", run)
        self.assertEqual(calls, ["init", "remote", "ls-remote"])


class GateTests(unittest.TestCase):
    SHA = "a" * 40

    def run_of(self, status="completed", conclusion="success", event="push", sha=None):
        return {"head_sha": sha or self.SHA, "event": event, "status": status, "conclusion": conclusion}

    def test_on_branch(self):
        for status in ("identical", "behind"):
            gate.require_on_branch(status, "main", self.SHA)
        for status in ("ahead", "diverged", None):
            with self.subTest(status=status), self.assertRaises(gate.GateError):
                gate.require_on_branch(status, "main", self.SHA)

    def test_success_passes(self):
        gate.require_check_passed([self.run_of()], self.SHA, "check.yml")
        gate.require_check_passed([self.run_of(conclusion="failure"), self.run_of()], self.SHA, "check.yml")

    def test_refusals_say_what_to_do(self):
        for runs, text in [([], "no push run"), ([self.run_of(status="in_progress", conclusion=None)], "still running"),
                           ([self.run_of(conclusion="failure")], "did not succeed"),
                           ([self.run_of(event="pull_request")], "no push run"), ([self.run_of(sha="b" * 40)], "no push run")]:
            with self.subTest(text=text), self.assertRaises(gate.GateError) as caught:
                gate.require_check_passed(runs, self.SHA, "check.yml")
            self.assertIn(text, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
