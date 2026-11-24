import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("ci_changes", ROOT / "scripts" / "ci_changes.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)

MM = "apps/kazuha-hub-market-monitor/"


def on(*paths):
    return {name for name, value in ci.classify(paths).items() if value}


class Classify(unittest.TestCase):
    def test_nothing_changed_runs_nothing(self):
        self.assertEqual(on(), set())

    def test_documentation_runs_no_gated_job(self):
        self.assertEqual(on("docs/progress.md", "README.md", MM + "README.md", "LICENSE", "scripts/tests/test_app_icon.py"), set())

    def test_a_market_monitor_frontend_change_runs_its_frontend_and_the_shared_frontend_gate_only(self):
        self.assertEqual(on(MM + "frontend/src/App.tsx"), {"platform", "mm_frontend"})

    def test_a_market_monitor_service_change_runs_the_service_and_the_image_checks(self):
        self.assertEqual(on(MM + "service/api.go"), {"mm_service", "mm_image"})

    def test_the_image_checks_run_for_what_the_image_is_made_of(self):
        # The whole service and pipeline directories and both Go modules are COPYed into the image.
        for path in ("service/Dockerfile", "service/go.mod", "service/api.go", "service/history_child.go", "service/testdata/make_history.py",
                     "pipeline/requirements.lock", "pipeline/mm_job.py", "pipeline/workspace/panorama/data/code_name.csv"):
            self.assertIn("mm_image", on(MM + path), path)
        for path in (".dockerignore", "packages/extensionprotocol/frame.go", "packages/proxy/proxy.go"):
            self.assertIn("mm_image", on(path), path)
        # .dockerignore keeps these out of the image.
        for path in ("pipeline/tests/test_mm_job.py", "pipeline/systemd/x.service", "pipeline/install.sh"):
            self.assertNotIn("mm_image", on(MM + path), path)
        self.assertNotIn("mm_image", on(MM + "frontend/src/App.tsx", "packages/app-sdk/src/index.ts"))

    def test_the_descriptor_is_read_by_the_frontend_the_service_and_the_shared_gate(self):
        self.assertEqual(on(MM + "app.v2.json"), {"platform", "mm_frontend", "mm_service"})

    def test_a_pipeline_change_runs_the_pipeline_tests_and_the_image_checks(self):
        self.assertEqual(on(MM + "pipeline/mm_job.py"), {"mm_pipeline", "mm_image"})
        self.assertEqual(on(MM + "pipeline/tests/test_mm_job.py"), {"mm_pipeline"})

    def test_the_protocol_module_reaches_every_service_that_links_it_and_the_templates(self):
        self.assertEqual(on("packages/extensionprotocol/frame.go"), {"protocol", "templates", "sd", "mm_service", "mm_image", "platform"})

    def test_the_proxy_module_reaches_the_market_monitor_service_and_the_templates(self):
        self.assertEqual(on("packages/proxy/proxy.go"), {"proxy", "templates", "mm_service", "mm_image", "platform"})

    def test_the_sdk_reaches_every_frontend_and_the_template_tests(self):
        # Both templates depend on it and scripts/test-app-root-v2.py reads packages/app-sdk/tests/fixtures.
        self.assertEqual(on("packages/app-sdk/src/index.ts"), {"platform", "templates", "sd", "mm_frontend", "status"})
        self.assertIn("templates", on("packages/app-sdk/tests/fixtures/root-v2/main.tsx"))

    def test_a_scheduled_digest_service_change_runs_that_app_and_its_frontend_gate(self):
        self.assertEqual(on("apps/scheduled-digest/service/main.go"), {"sd"})
        self.assertEqual(on("apps/scheduled-digest/frontend/src/App.tsx"), {"platform", "sd"})

    def test_a_manifest_is_validated_by_the_shared_gate(self):
        self.assertEqual(on("apps/scheduled-digest/app.v2.json"), {"platform", "sd"})
        self.assertEqual(on("apps/status/app.json"), {"platform", "status"})
        self.assertEqual(on("apps/demo-symbols/app.json"), {"platform"})

    def test_status_service_runs_status_and_its_tests_run_the_browser_suite(self):
        self.assertEqual(on("apps/status/service/cmd/status/main.go"), {"status"})
        self.assertEqual(on("apps/status/tests/status.spec.cjs"), {"status_browser"})
        self.assertEqual(on("apps/status/frontend/src/App.tsx"), {"platform", "status"})

    def test_shared_scripts_run_every_consumer_but_not_the_go_module_jobs(self):
        got = on("scripts/build-app-v2.py")
        self.assertEqual(got, {"platform", "templates", "sd", "mm_frontend", "status"})

    def test_the_workflow_the_detector_and_the_lockfile_run_everything(self):
        for path in (".github/workflows/check.yml", "scripts/ci_changes.py", "package-lock.json", "package.json"):
            self.assertEqual(on(path), set(ci.AREAS), path)

    def test_other_workflows_do_not_run_the_check_jobs(self):
        self.assertEqual(on(".github/workflows/release-status.yml"), set())

    def test_an_unclassified_path_fails_closed(self):
        for path in ("apps/new-app/app.v2.json", "something-new.toml", "tools/x.py", "packages/new-pkg/a.go"):
            self.assertEqual(on(path), set(ci.AREAS), path)

    def test_the_demo_apps_and_templates_run_the_shared_gate(self):
        self.assertEqual(on("apps/demo-symbols/frontend/src/App.tsx"), {"platform"})
        self.assertEqual(on("templates/react-app-v2-backend/service/main.go"), {"platform", "templates"})

    def test_all_flag_runs_everything(self):
        self.assertEqual(set(ci.classify(None)), set(ci.AREAS))
        self.assertTrue(all(ci.classify(None).values()))


class Cli(unittest.TestCase):
    def run_cli(self, stdin, *args):
        return subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "ci_changes.py"), *args], input=stdin,
                              capture_output=True, text=True, check=True).stdout

    def test_it_prints_one_output_line_per_area(self):
        out = self.run_cli(MM + "pipeline/mm_job.py\n").splitlines()
        self.assertEqual(sorted(line.split("=")[0] for line in out), sorted(ci.AREAS))
        self.assertIn("mm_pipeline=true", out)
        self.assertIn("mm_service=false", out)

    def test_all_prints_everything_true(self):
        self.assertTrue(all(line.endswith("=true") for line in self.run_cli("", "--all").splitlines()))


if __name__ == "__main__":
    unittest.main()
