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

    def test_check_fetches_the_pinned_commit_and_reports_drift(self):
        asked = []

        def fetch(sha, path):
            asked.append((sha, path))
            return {"scripts/licence_scan.py": SOURCE, "scripts/licence-policy.json": json.dumps(POLICY)}[path]

        local_policy = dict(POLICY)
        self.assertEqual(copy.check(SHA, SOURCE, local_policy, fetch), [])
        self.assertEqual({a[0] for a in asked}, {SHA})
        drift = copy.check(SHA, SOURCE.replace("return 1", "return 2"), local_policy, fetch)
        self.assertTrue(any("licence_scan.py" in d for d in drift))
        drift = copy.check(SHA, SOURCE, dict(POLICY, allow=["MIT", "ISC"]), fetch)
        self.assertTrue(any("allow" in d for d in drift))

    def test_the_failure_message_says_how_to_bump_the_pin(self):
        self.assertIn("licence-scan.pin", copy.BUMP_HELP)


class TheWorkflow(unittest.TestCase):
    def test_the_go_sbom_covers_every_status_release_target(self):
        build = load("build_status_release", "build-status-release.py")
        targets = {(goos, goarch, goarm) for goos, goarch, goarm in build.TARGETS.values()}
        workflow = (ROOT / ".github" / "workflows" / "check.yml").read_text()
        job = re.search(r"(?m)^  licence:\n(.*?)(?=^  [a-z-]+:\n)", workflow, re.S)[1]
        listed = set(re.findall(r"\b(linux|darwin|windows)/(amd64|arm64|arm)(?:/(\d))?\b", job))
        self.assertEqual({(a, b, c or "") for a, b, c in listed}, targets)

    def test_the_licence_job_runs_the_copy_check(self):
        workflow = (ROOT / ".github" / "workflows" / "check.yml").read_text()
        self.assertIn("scripts/check_licence_copy.py", workflow)


if __name__ == "__main__":
    unittest.main()
