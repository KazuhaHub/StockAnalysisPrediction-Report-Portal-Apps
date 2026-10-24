"""Verify publication gates and hostile release artifacts without network writes."""
import copy
import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
import stat
import zipfile
from unittest import mock
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "status-publish.py"
spec = importlib.util.spec_from_file_location("status_publish", SCRIPT)
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / "apps/status"
        (self.folder / "releases").mkdir(parents=True)
        self.manifest = {"id": "status", "name": "Status", "entry": "index.html", "version": "1.2.3", "scopes": ["extension.read", "extension.manage"]}
        self.approval = {"schema_version": 1, "app_id": "status", "version": "1.2.3", "minimum_portal_release": "v2026.44", "runtime_image": "gcr.io/distroless/static-debian12:nonroot@sha256:" + "a" * 64, "evidence": {key: "https://example.test/review/123" for key in publish.EVIDENCE}}
        self.save()

    def save(self):
        (self.folder / "app.json").write_text(json.dumps(self.manifest))
        (self.folder / "releases/1.2.3.json").write_text(json.dumps(self.approval))

    def test_release_requires_exact_version_confirmation_and_review(self):
        result = publish.release_contract(self.root, "1.2.3", "status/v1.2.3")
        self.assertEqual(result["minimum_portal_release"], "v2026.44")
        for version, confirmation in [("../escape", "status/v1.2.3"), ("1.2.4", "status/v1.2.4"), ("1.2.3", "yes")]:
            with self.assertRaises(ValueError): publish.release_contract(self.root, version, confirmation)
        (self.folder / "releases/1.2.3.json").unlink()
        with self.assertRaises(ValueError): publish.release_contract(self.root, "1.2.3", "status/v1.2.3")

    def test_development_or_placeholder_acceptance_cannot_publish(self):
        for value in ["0.1.0-dev", "0.1.0-dev.1", "0.1.0-dev-preview", "0.1.0-snapshot-build", "0.1.0-snapshot", "1.2.3-01", "1.2.3;echo", "1.2.3+metadata"]:
            with self.assertRaises(ValueError): publish.validate_version(value)
        for key in publish.EVIDENCE:
            bad = copy.deepcopy(self.approval)
            bad["evidence"][key] = "pending"
            (self.folder / "releases/1.2.3.json").write_text(json.dumps(bad))
            with self.assertRaises(ValueError): publish.release_contract(self.root, "1.2.3", "status/v1.2.3")
        self.save()
        for runtime in ["gcr.io/distroless/static-debian12:nonroot", "docker.io/other/image@sha256:" + "a" * 64]:
            self.approval["runtime_image"] = runtime
            self.save()
            with self.assertRaises(ValueError): publish.release_contract(self.root, "1.2.3", "status/v1.2.3")

    def test_exact_main_push_ci_and_every_required_job_are_mandatory(self):
        sha = "b" * 40
        run = {"id": 7, "head_sha": sha, "head_branch": "main", "event": "push", "path": ".github/workflows/check.yml", "status": "completed", "conclusion": "success"}
        self.assertEqual(publish.verified_ci([run], sha), 7)
        for change in [{"head_sha": "c" * 40}, {"head_branch": "feature"}, {"event": "pull_request"}, {"path": ".github/workflows/other.yml"}, {"conclusion": "failure"}, {"status": "in_progress"}]:
            with self.assertRaises(ValueError): publish.verified_ci([{**run, **change}], sha)
        jobs = [{"name": name, "status": "completed", "conclusion": "success"} for name in publish.REQUIRED_JOBS]
        publish.verified_jobs(jobs)
        with self.assertRaises(ValueError): publish.verified_jobs(jobs[:-1])
        for conclusion in ["skipped", "failure", "cancelled"]:
            with self.assertRaises(ValueError): publish.verified_jobs([{**jobs[0], "conclusion": conclusion}, *jobs[1:]])

    def test_checksum_duplicates_and_path_entries_are_refused(self):
        digest = hashlib.sha256(b"fixture").hexdigest()
        self.assertEqual(publish.checksums(digest + "  archive.tar.gz\n"), {"archive.tar.gz": digest})
        for bad in [digest + "  ../outside\n", digest + "  same\n" + digest + "  same\n", "bad  archive.tar.gz\n"]:
            with self.assertRaises(ValueError): publish.checksums(bad)

    def tar(self, entries):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, kind, content in entries:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.size = len(content) if kind == tarfile.REGTYPE else 0
                if kind == tarfile.SYMTYPE: info.linkname = "/outside"
                archive.addfile(info, io.BytesIO(content) if info.size else None)
        return stream.getvalue()

    def test_extracts_only_regular_exact_executable_without_writing_paths(self):
        name = "report-portal_v2026.44_linux_amd64/report-portal"
        good = self.tar([(name, tarfile.REGTYPE, b"fixture-binary"), ("report-portal_v2026.44_linux_amd64/README.md", tarfile.REGTYPE, b"notes")])
        self.assertEqual(publish.tar_binary(good, name), b"fixture-binary")
        for entries in [[(name, tarfile.SYMTYPE, b"")], [(name, tarfile.REGTYPE, b"one"), (name, tarfile.REGTYPE, b"two")], [("../outside", tarfile.REGTYPE, b"x"), (name, tarfile.REGTYPE, b"binary")]]:
            with self.assertRaises(ValueError): publish.tar_binary(self.tar(entries), name)
        self.assertFalse((self.root / "outside").exists())

    def test_redirects_never_forward_authorization_outside_github_api(self):
        from urllib.request import Request
        redirect = publish.GitHubRedirect()
        request = Request("https://api.github.com/repos/example/assets/1", headers={"Authorization": "Bearer fixture-only"})
        redirected = redirect.redirect_request(request, None, 302, "", {}, "https://release-assets.githubusercontent.com/asset")
        self.assertIsNone(redirected.get_header("Authorization"))
        for destination in ["http://release-assets.githubusercontent.com/asset", "https://other.example/asset"]:
            with self.assertRaises(ValueError): redirect.redirect_request(request, None, 302, "", {}, destination)


    def plan(self):
        return {**publish.release_contract(self.root, "1.2.3", "status/v1.2.3"),
                "source_commit": "b" * 40, "ci_run_id": 7, "notes": "Reviewed release",
                "minimum_portal_release_id": 9, "minimum_portal_archive_sha256": "c" * 64,
                "minimum_portal_binary_sha256": "d" * 64}

    def artifacts(self, extra=None):
        folder = self.root / "artifacts"
        folder.mkdir(exist_ok=True)
        with zipfile.ZipFile(folder / "status.zip", "w") as bundle:
            for name, raw, mode in [("app.json", json.dumps(self.manifest).encode(), stat.S_IFREG),
                                    ("index.html", b"fixture", stat.S_IFREG), *(extra or [])]:
                item = zipfile.ZipInfo(name)
                item.external_attr = (mode | 0o644) << 16
                bundle.writestr(item, raw)
        build = {"app_id": "status", "version": "1.2.3", "source_commit": "b" * 40,
                 "source_dirty": False, "targets": sorted(publish.TARGETS), "publication": "not-published",
                 "required_portal_capabilities": ["extension.read", "extension.manage", "notification-publisher-identity"]}
        (folder / "build.json").write_text(json.dumps(build))
        for target in publish.TARGETS:
            if target.startswith("windows"):
                with zipfile.ZipFile(folder / ("status-v1.2.3-" + target + ".zip"), "w") as bundle:
                    item = zipfile.ZipInfo("status.exe")
                    item.external_attr = (stat.S_IFREG | 0o755) << 16
                    bundle.writestr(item, b"fixture")
            else:
                (folder / ("status-v1.2.3-" + target + ".tar.gz")).write_bytes(self.tar([("status", tarfile.REGTYPE, b"fixture")]))
        self.rehash(folder)
        return folder

    def rehash(self, folder):
        (folder / "SHA256SUMS").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
                                                     for p in sorted(folder.iterdir()) if p.name != "SHA256SUMS"))

    def test_approval_cannot_escape_through_a_symlinked_parent(self):
        outside = self.root / "outside"
        outside.mkdir()
        record = self.folder / "releases/1.2.3.json"
        record.rename(outside / record.name)
        record.parent.rmdir()
        record.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            publish.release_contract(self.root, "1.2.3", "status/v1.2.3")

    def test_artifact_plan_targets_and_complete_checksums_are_bound(self):
        folder = self.artifacts()
        plan = self.plan()
        publish.verified_artifacts(plan, folder)
        for key, bad in [("version", "../1.2.3"), ("source_commit", "bad"), ("tag", "other/v1.2.3"), ("image", "ghcr.io/other:1.2.3")]:
            with self.assertRaises(ValueError): publish.verified_artifacts({**plan, key: bad}, folder)
        build = json.loads((folder / "build.json").read_text())
        build["targets"] = dict.fromkeys(publish.TARGETS, True)
        (folder / "build.json").write_text(json.dumps(build)); self.rehash(folder)
        with self.assertRaises(ValueError): publish.verified_artifacts(plan, folder)

    def test_rehashed_private_or_nonregular_frontend_entries_are_refused(self):
        for entry in [(".env", b"private", stat.S_IFREG), ("secrets.key", b"private", stat.S_IFREG),
                      ("src/code.js", b"development", stat.S_IFREG), ("device.json", b"device", stat.S_IFCHR),
                      ("directory/", b"", stat.S_IFDIR)]:
            with self.subTest(name=entry[0]):
                folder = self.artifacts([entry])
                with self.assertRaises(ValueError): publish.verified_artifacts(self.plan(), folder)

    def test_tampered_final_metadata_cannot_be_rehashed_into_a_valid_release(self):
        folder = self.artifacts(); plan = self.plan()
        publish.finalize(plan, folder, "sha256:" + "e" * 64)
        publish.verified_artifacts(plan, folder, True)
        path = folder / "release.json"; metadata = json.loads(path.read_text())
        metadata["artifacts"]["status.zip"] = "0" * 64
        path.write_text(json.dumps(metadata)); self.rehash(folder)
        with self.assertRaises(ValueError): publish.verified_artifacts(plan, folder, True)

    def test_publication_requires_workflow_source_before_any_write(self):
        folder = self.artifacts(); plan = self.plan()
        publish.finalize(plan, folder, "sha256:" + "e" * 64)
        github = mock.Mock()
        with mock.patch.dict(publish.os.environ, {}, clear=True):
            with self.assertRaises(ValueError): publish.publish(plan, folder, github, "reviewer")
        github.api.assert_not_called(); github.absent.assert_not_called()

    def test_source_admission_checks_the_committed_contract_and_exact_ci(self):
        plan = self.plan()
        github = mock.Mock()
        run = {"id": 7, "head_sha": plan["source_commit"], "head_branch": "main", "event": "push",
               "path": ".github/workflows/check.yml", "status": "completed", "conclusion": "success"}
        jobs = [{"name": name, "status": "completed", "conclusion": "success"} for name in publish.REQUIRED_JOBS]
        github.api.side_effect = [{"workflow_runs": [run]}, {"jobs": jobs}]
        with mock.patch.object(publish, "workflow_context", return_value=plan["source_commit"]), mock.patch.dict(publish.os.environ, {"RELEASE_NOTES": plan["notes"]}):
            publish.verified_source(plan, github, self.root)
            self.assertEqual(github.api.call_count, 2)
            with self.assertRaises(ValueError): publish.verified_source({**plan, "manifest": {**plan["manifest"], "name": "changed"}}, github, self.root)
            github.api.side_effect = [{"workflow_runs": [{**run, "id": 8}]}]
            with self.assertRaises(ValueError): publish.verified_source(plan, github, self.root)

    def test_workflow_context_requires_manual_main_exact_clean_commit(self):
        values = {"GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": publish.APPS_REPO,
                  "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": "b" * 40}
        with mock.patch.dict(publish.os.environ, values, clear=True), mock.patch.object(publish.subprocess, "check_output", side_effect=["b" * 40 + "\n", ""]):
            self.assertEqual(publish.workflow_context(self.root), "b" * 40)
        for change in [{"GITHUB_EVENT_NAME": "pull_request"}, {"GITHUB_REF": "refs/heads/other"}, {"GITHUB_REPOSITORY": "other/repo"}]:
            with mock.patch.dict(publish.os.environ, {**values, **change}, clear=True):
                with self.assertRaises(ValueError): publish.workflow_context(self.root)
        for output in [["c" * 40 + "\n"], ["b" * 40 + "\n", " M file\n"]]:
            with mock.patch.dict(publish.os.environ, values, clear=True), mock.patch.object(publish.subprocess, "check_output", side_effect=output):
                with self.assertRaises(ValueError): publish.workflow_context(self.root)

    def test_publication_switches_draft_only_after_every_verified_upload(self):
        folder = self.artifacts(); plan = self.plan()
        publish.finalize(plan, folder, "sha256:" + "e" * 64)
        calls = []
        class GitHubFixture:
            def absent(self, tag): calls.append(("absent", tag))
            def api(self, path, data=None, method="GET", **kwargs):
                calls.append((method, path, data))
                if path.startswith("users/"): return {"type": "User", "login": "reviewer", "id": 42}
                if path.endswith("/git/tags"): return {"sha": "f" * 40}
                if path.endswith("/releases"): return {"id": 10, "draft": True}
                return {}
            def upload(self, release_id, file): calls.append(("upload", file.name))
        with mock.patch.object(publish, "verified_source"), mock.patch.object(publish, "verify_public") as public:
            publish.publish(plan, folder, GitHubFixture(), "reviewer")
        public.assert_called_once()
        uploads = [item[1] for item in calls if item[0] == "upload"]
        self.assertEqual(set(uploads), {file.name for file in folder.iterdir()})
        self.assertEqual(len(uploads), len(set(uploads)))
        self.assertEqual(calls[-1][0], "PATCH")
        self.assertIs(calls[-1][2]["draft"], False)
        tagger = next(item[2]["tagger"] for item in calls if item[0] == "POST" and item[1].endswith("/git/tags"))
        self.assertEqual(tagger["name"], "reviewer")

    def test_duplicate_public_assets_are_refused_before_downloading(self):
        folder = self.artifacts(); plan = self.plan()
        publish.finalize(plan, folder, "sha256:" + "e" * 64)
        assets = [{"name": path.name} for path in folder.iterdir()]
        github = mock.Mock()
        github.api.return_value = {"tag_name": plan["tag"], "draft": False, "assets": [*assets, assets[0]]}
        with mock.patch.object(publish, "fetch") as download:
            with self.assertRaises(ValueError): publish.verify_public(plan, folder, github)
        download.assert_not_called()

    def test_publish_keeps_draft_when_an_asset_verification_fails(self):
        folder = self.artifacts(); plan = self.plan()
        publish.finalize(plan, folder, "sha256:" + "e" * 64)
        calls = []
        class GitHubFixture:
            def absent(self, tag): calls.append(("absent", tag))
            def api(self, path, data=None, method="GET", **kwargs):
                calls.append((method, path, data))
                if path.startswith("users/"): return {"type": "User", "login": "reviewer", "id": 42}
                if path.endswith("/git/tags"): return {"sha": "f" * 40}
                if path.endswith("/releases"): return {"id": 10, "draft": True}
                return {}
            def upload(self, release_id, file):
                calls.append(("upload", file.name))
                raise ValueError("fixture asset download mismatch")
        with mock.patch.object(publish, "verified_source") as source:
            with self.assertRaises(ValueError): publish.publish(plan, folder, GitHubFixture(), "reviewer")
        source.assert_called_once()
        self.assertTrue(any(item[0] == "upload" for item in calls))
        self.assertFalse(any(item[0] == "PATCH" for item in calls))
        self.assertFalse(any(item[0] == "DELETE" for item in calls))


if __name__ == "__main__": unittest.main()
