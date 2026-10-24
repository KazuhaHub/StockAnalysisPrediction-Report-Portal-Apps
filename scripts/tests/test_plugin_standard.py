import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("plugin_standard", Path(__file__).parents[1] / "plugin-standard.py")
standard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(standard)


class PluginStandardTests(unittest.TestCase):
    def test_generator_creates_an_unlisted_standard_workspace_and_refuses_overwrite(self):
        creator_spec = importlib.util.spec_from_file_location("create_app", Path(__file__).parents[1] / "create-app.py")
        creator = importlib.util.module_from_spec(creator_spec)
        creator_spec.loader.exec_module(creator)
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(Path(__file__).parents[2] / "templates", root / "templates")
            creator.ROOT = root
            creator.create("fixture-app", "A quoted \"name\"")
            manifest = json.loads((root / "apps/fixture-app/app.json").read_text())
            self.assertEqual(manifest["scopes"], [])
            self.assertEqual(manifest["name"], 'A quoted "name"')
            self.assertFalse((root / "index.json").exists())
            self.assertTrue(standard.check(root))
            with self.assertRaisesRegex(ValueError, "overwrite"):
                creator.create("fixture-app", "Another name")
            with self.assertRaisesRegex(ValueError, "identifier"):
                creator.create("../escape", "Invalid")

    def test_unregistered_application_cannot_bypass_shared_foundation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "apps/new/frontend").mkdir(parents=True)
            (root / "apps/new/app.json").write_text(json.dumps({"id": "new"}))
            with self.assertRaisesRegex(ValueError, "frontend/package.json"):
                standard.check(root)

    def test_alternate_ui_versions_and_missing_sdk_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            p = root / "apps/new/frontend"
            p.mkdir(parents=True)
            (p.parent / "app.json").write_text(json.dumps({"id": "new"}))
            (p / "package.json").write_text(json.dumps({"dependencies": {"react": "18.0.0", "antd": "5.0.0"}}))
            with self.assertRaisesRegex(ValueError, "react"):
                standard.check(root)
