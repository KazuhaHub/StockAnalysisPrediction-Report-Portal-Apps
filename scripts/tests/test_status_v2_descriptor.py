import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
APP = ROOT / "apps/status"


class StatusV2DescriptorTests(unittest.TestCase):
    def descriptor(self):
        return json.loads((APP / "app.v2.json").read_text())

    def test_status_declares_only_the_v2_manifest(self):
        self.assertTrue((APP / "app.v2.json").is_file())
        self.assertFalse((APP / "app.json").exists())

    def test_identity_and_version(self):
        value = self.descriptor()
        self.assertEqual(value["format"], "portal.app/v2")
        self.assertEqual(value["id"], "status")
        self.assertEqual(value["version"], "0.2.0-beta.1")
        self.assertEqual(value["presentation"]["display"]["icon"], "dashboard")
        locales = [item["locale"] for item in value["presentation"]["display"]["texts"]]
        self.assertEqual(sorted(locales), ["en-US", "zh-CN", "zh-TW"])
        self.assertEqual(value["presentation"]["locales"], ["en-US", "zh-CN", "zh-TW"])

    def test_capabilities_are_declared_as_the_plan_requires(self):
        capabilities = self.descriptor()["capabilities"]
        self.assertEqual(
            sorted(capabilities["required"]),
            ["background.run", "notifications.publish", "secrets.use", "tasks.schedule"],
        )
        self.assertEqual(capabilities["optional"], ["network.http"])

    def test_backend_and_data_declaration(self):
        value = self.descriptor()
        backend = value["backend"]
        self.assertEqual(backend["kind"], "oci")
        self.assertEqual(backend["protocol"], "portal.backend/1")
        self.assertEqual(backend["platforms"], ["linux/amd64", "linux/arm64"])
        self.assertRegex(backend["image"], r"@sha256:[a-f0-9]{64}$")
        self.assertEqual(
            value["data"], {"schema": 1, "readable_schemas": [1], "writes_on_startup": False}
        )
        self.assertNotIn("migrations", value["data"])

    def test_routes_cover_the_three_private_surfaces(self):
        routes = self.descriptor()["presentation"]["routes"]
        self.assertEqual([item["path"] for item in routes], ["/", "/incidents", "/manage"])

    def test_shared_strict_descriptor_validator_accepts_it(self):
        subprocess.run(
            ["node", str(ROOT / "scripts/validate-descriptor-v2.mjs"), str(APP / "app.v2.json")],
            cwd=ROOT,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
