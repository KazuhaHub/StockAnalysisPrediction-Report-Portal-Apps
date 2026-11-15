"""The licence evaluator is a copy of the Portal's; check_licence_copy.py fails when the copies drift, and the
workflow builds the Go SBOM for every status release target."""
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


copy = load("check_licence_copy", "check_licence_copy.py")

SOURCE = '"""Portal wording of the docstring."""\nimport json\n\n\ndef f():\n    # a comment\n    return 1\n'
SHA = "a" * 40


class EvaluatorComparison(unittest.TestCase):
    def test_identical_apart_from_the_docstring_matches(self):
        other = SOURCE.replace("Portal wording", "Apps wording, longer\n\nover several lines")
        self.assertEqual(copy.evaluator_differences(other, SOURCE), [])

    def test_a_changed_line_is_reported(self):
        other = SOURCE.replace("return 1", "return 2")
        self.assertTrue(copy.evaluator_differences(other, SOURCE))

    def test_a_changed_comment_is_reported(self):
        other = SOURCE.replace("# a comment", "# another comment")
        self.assertTrue(copy.evaluator_differences(other, SOURCE))

    def test_an_added_function_is_reported(self):
        self.assertTrue(copy.evaluator_differences(SOURCE + "\n\ndef g():\n    return 3\n", SOURCE))

    def test_a_missing_docstring_does_not_hide_a_difference(self):
        other = SOURCE.split("\n", 1)[1].replace("return 1", "return 9")
        self.assertTrue(copy.evaluator_differences(other, SOURCE))


POLICY = {"allow": ["MIT"], "deny": ["SSPL-1.0"], "election_only": ["FTL"], "own": {"licences": ["AGPL-3.0-only"], "components": ["x/"]},
          "reviewed": [{"components": ["a"], "sha256": "0" * 64}], "elections": [{"component": "p"}], "exclusions": []}


class PolicyComparison(unittest.TestCase):
    def test_shared_sections_match_and_portal_only_sections_are_ignored(self):
        local = dict(POLICY, elections=[], own={"licences": ["AGPL-3.0-only"], "components": ["y"]})
        self.assertEqual(copy.policy_differences(local, POLICY), [])

    def test_each_shared_section_is_compared(self):
        for key, value in {"allow": ["MIT", "GPL-2.0-only"], "deny": [], "election_only": [],
                           "reviewed": [{"components": ["a"], "sha256": "1" * 64}]}.items():
            with self.subTest(key=key):
                self.assertTrue(copy.policy_differences(dict(POLICY, **{key: value}), POLICY), key)

    def test_the_own_licences_are_compared(self):
        local = dict(POLICY, own={"licences": ["GPL-2.0-only"], "components": []})
        self.assertTrue(copy.policy_differences(local, POLICY))


class Pin(unittest.TestCase):
    def test_the_checked_in_pin_is_a_full_commit_sha(self):
        pin = (ROOT / "scripts" / "licence-scan.pin").read_text().strip()
        self.assertRegex(pin, r"^[0-9a-f]{40}$")

    def test_a_malformed_pin_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pin"
            for bad in ("main", "abc123", "", "g" * 40):
                path.write_text(bad)
                with self.assertRaises(ValueError):
                    copy.read_pin(path)
            path.write_text(SHA + "\n")
            self.assertEqual(copy.read_pin(path), SHA)

    def test_the_failure_message_says_how_to_bump_the_pin(self):
        self.assertIn("licence-scan.pin", copy.BUMP_HELP)


class FakePortal:
    """The Portal repository as the check sees it: files by ref, and which branches contain which commits."""

    def __init__(self, files_by_ref, contains=()):
        self.files_by_ref, self.contains, self.asked = files_by_ref, set(contains), []

    def fetch(self, ref, path):
        self.asked.append((ref, path))
        return self.files_by_ref.get(ref, {}).get(path)

    def reachable(self, branch, sha):
        return (branch, sha) in self.contains


def portal_files(source=SOURCE, policy=POLICY):
    return {"scripts/licence_scan.py": source, "scripts/licence-policy.json": json.dumps(policy)}


INTEGRATION, MAIN = "integration/app-platform", "main"


class DriftCheck(unittest.TestCase):
    def check(self, portal, source=SOURCE, policy=POLICY):
        return copy.check(SHA, source, policy, portal.fetch, portal.reachable)

    def test_matching_the_pin_with_no_live_copy_yet_passes_and_says_so(self):
        # Before the Portal merges the licence gate there is nothing live to compare with.
        drift, notes = self.check(FakePortal({SHA: portal_files()}))
        self.assertEqual(drift, [])
        self.assertTrue(any("not merged" in n for n in notes))

    def test_a_drifted_evaluator_is_reported_against_the_pin(self):
        drift, _ = self.check(FakePortal({SHA: portal_files()}), source=SOURCE.replace("return 1", "return 2"))
        self.assertTrue(any("licence_scan.py" in d and SHA[:7] in d for d in drift))

    def test_a_drifted_shared_policy_section_is_reported(self):
        drift, _ = self.check(FakePortal({SHA: portal_files()}), policy=dict(POLICY, allow=["MIT", "ISC"]))
        self.assertTrue(any("allow" in d for d in drift))

    def test_a_missing_pin_commit_is_reported(self):
        drift, _ = self.check(FakePortal({}))
        self.assertTrue(any("pinned commit" in d for d in drift))

    def test_branches_that_differ_pass_when_the_pin_matches_one_of_them(self):
        # integration/app-platform and main can differ for weeks; the pin only has to be one of them.
        newer = portal_files(SOURCE.replace("return 1", "return 7"))
        for matching in (INTEGRATION, MAIN):
            with self.subTest(matching=matching):
                other = MAIN if matching == INTEGRATION else INTEGRATION
                portal = FakePortal({SHA: portal_files(), matching: portal_files(), other: newer},
                                    contains={(matching, SHA)})
                self.assertEqual(self.check(portal), ([], []))

    def test_branches_that_differ_fail_when_the_pin_matches_neither(self):
        a = portal_files(SOURCE.replace("return 1", "return 7"))
        b = portal_files(SOURCE.replace("return 1", "return 8"))
        portal = FakePortal({SHA: portal_files(), INTEGRATION: a, MAIN: b}, contains={(INTEGRATION, SHA)})
        drift, _ = self.check(portal)
        self.assertTrue(any(INTEGRATION in d and MAIN in d for d in drift) or
                        (any(INTEGRATION in d for d in drift) and any(MAIN in d for d in drift)))

    def test_the_shared_policy_of_the_pin_may_match_a_different_branch_than_the_evaluator_does(self):
        # Each live branch is judged as a whole: matching the evaluator of one and the policy of the other is no match.
        a = portal_files(SOURCE, dict(POLICY, deny=[]))
        b = portal_files(SOURCE.replace("return 1", "return 8"), POLICY)
        portal = FakePortal({SHA: portal_files(), INTEGRATION: a, MAIN: b}, contains={(INTEGRATION, SHA)})
        self.assertTrue(self.check(portal)[0])

    def test_a_branch_that_contains_the_pin_but_lost_the_file_fails(self):
        # The file once reached the branch (the pin is in its history) and is gone: that is a removal, not "not merged yet".
        portal = FakePortal({SHA: portal_files(), INTEGRATION: portal_files()}, contains={(INTEGRATION, SHA), (MAIN, SHA)})
        drift, _ = self.check(portal)
        self.assertTrue(any(MAIN in d and "no longer" in d for d in drift))

    def test_a_branch_that_never_had_the_file_is_not_a_removal(self):
        portal = FakePortal({SHA: portal_files(), INTEGRATION: portal_files()}, contains={(INTEGRATION, SHA)})
        self.assertEqual(self.check(portal)[0], [])

    def test_when_every_branch_lost_the_file_after_containing_the_pin_it_fails(self):
        portal = FakePortal({SHA: portal_files()}, contains={(INTEGRATION, SHA)})
        drift, _ = self.check(portal)
        self.assertTrue(any(INTEGRATION in d and "no longer" in d for d in drift))

    def test_the_live_integration_branch_is_compared_too(self):
        live = portal_files(SOURCE.replace("return 1", "return 7"))
        portal = FakePortal({SHA: portal_files(), INTEGRATION: live}, contains={(INTEGRATION, SHA)})
        drift, _ = self.check(portal)
        self.assertTrue(any(INTEGRATION in d and "licence_scan.py" in d for d in drift))

    def test_the_live_main_branch_is_compared_when_the_file_exists_there(self):
        live = portal_files(policy=dict(POLICY, deny=[]))
        portal = FakePortal({SHA: portal_files(), MAIN: live}, contains={(MAIN, SHA)})
        drift, _ = self.check(portal)
        self.assertTrue(any(MAIN in d and "deny" in d for d in drift))

    def test_matching_live_branches_and_a_reachable_pin_pass(self):
        portal = FakePortal({SHA: portal_files(), INTEGRATION: portal_files(), MAIN: portal_files()},
                            contains={(INTEGRATION, SHA)})
        self.assertEqual(self.check(portal), ([], []))

    def test_a_pin_no_live_branch_contains_is_reported(self):
        # What a squash merge does to a pin on a feature-branch commit: the content matches, the commit is gone.
        portal = FakePortal({SHA: portal_files(), INTEGRATION: portal_files()})
        drift, _ = self.check(portal)
        self.assertTrue(any("reachable" in d for d in drift))

    def test_one_branch_containing_the_pin_is_enough(self):
        portal = FakePortal({SHA: portal_files(), INTEGRATION: portal_files(), MAIN: portal_files()},
                            contains={(MAIN, SHA)})
        self.assertEqual(self.check(portal)[0], [])

    def test_a_branch_without_the_file_is_skipped_not_failed(self):
        portal = FakePortal({SHA: portal_files(), INTEGRATION: portal_files()}, contains={(INTEGRATION, SHA)})
        drift, _ = self.check(portal)
        self.assertEqual(drift, [])
        self.assertNotIn((MAIN, "scripts/licence-policy.json"), portal.asked)

    def test_the_pin_is_fetched_by_commit_and_branches_by_name(self):
        portal = FakePortal({SHA: portal_files()})
        self.check(portal)
        self.assertIn((SHA, "scripts/licence_scan.py"), portal.asked)
        self.assertIn((INTEGRATION, "scripts/licence_scan.py"), portal.asked)
        self.assertIn((MAIN, "scripts/licence_scan.py"), portal.asked)


class Token(unittest.TestCase):
    def test_the_token_is_sent_only_to_the_github_api(self):
        env = {"GITHUB_TOKEN": "t0ken"}
        api = dict(copy.request_headers("https://api.github.com/repos/x/y/compare/a...b", env))
        self.assertEqual(api["Authorization"], "Bearer t0ken")
        for url in ("https://raw.githubusercontent.com/x/y/main/f", "https://example.com/", "http://api.github.com/x"):
            self.assertNotIn("Authorization", dict(copy.request_headers(url, env)), url)

    def test_without_a_token_the_request_is_anonymous(self):
        self.assertNotIn("Authorization", dict(copy.request_headers("https://api.github.com/x", {})))
        self.assertNotIn("Authorization", dict(copy.request_headers("https://api.github.com/x", {"GITHUB_TOKEN": ""})))

    def test_the_workflow_passes_the_read_only_job_token_to_the_copy_check(self):
        workflow = (ROOT / ".github" / "workflows" / "check.yml").read_text()
        self.assertRegex(workflow, r"(?m)^permissions:\n  contents: read\n")
        step = re.search(r"- name: Evaluator and policy match the Portal copy\n(.*?)(?=\n      - name:)", workflow, re.S)[1]
        self.assertIn("GITHUB_TOKEN: ${{ github.token }}", step)
        self.assertIn("scripts/check_licence_copy.py", step)


class TheWorkflow(unittest.TestCase):
    def test_the_go_sbom_covers_every_status_release_target(self):
        build = load("build_status_release", "build-status-release.py")
        targets = {(goos, goarch, goarm) for goos, goarch, goarm in build.TARGETS.values()}
        workflow = (ROOT / ".github" / "workflows" / "check.yml").read_text()
        job = re.search(r"(?m)^  licence:\n(.*?)(?=^  [a-z-]+:\n)", workflow, re.S)[1]
        listed = set(re.findall(r"\b(linux|darwin|windows)/(amd64|arm64|arm)(?:/(\d))?\b", job))
        self.assertEqual({(a, b, c or "") for a, b, c in listed}, targets)

    def test_the_npm_sbom_is_cross_checked_against_the_installed_tree(self):
        # The SBOM is built from package-lock.json, whose licence fields integrity does not cover, so the scan is
        # given the installed node_modules and npm ci runs first.
        workflow = (ROOT / ".github" / "workflows" / "check.yml").read_text()
        job = re.search(r"(?m)^  licence:\n(.*?)(?=^  [a-z-]+:\n)", workflow, re.S)[1]
        self.assertIn("npm ci --ignore-scripts", job)
        self.assertLess(job.index("npm ci --ignore-scripts"), job.index("scripts/licence_scan.py --policy"))
        self.assertIn("--node-modules node_modules", job)

    def test_the_licence_job_runs_the_copy_check(self):
        workflow = (ROOT / ".github" / "workflows" / "check.yml").read_text()
        self.assertIn("scripts/check_licence_copy.py", workflow)


if __name__ == "__main__":
    unittest.main()
