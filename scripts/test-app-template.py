"""Generate, typecheck, test and build a fresh application without publishing it."""
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("create_app", ROOT / "scripts/create-app.py")
creator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(creator)

with tempfile.TemporaryDirectory(prefix="portal-template-") as directory:
    target = Path(directory)
    shutil.copytree(ROOT / "templates", target / "templates")
    (target / "node_modules").symlink_to(ROOT / "node_modules", target_is_directory=True)
    creator.ROOT = target
    creator.create("template-check", "Template check")
    frontend = target / "apps/template-check/frontend"
    for command in ["typecheck", "test", "build"]:
        subprocess.run(["npm", "run", command], cwd=frontend, check=True)
    if not (frontend / "dist/app.js").is_file():
        raise ValueError("Generated application did not produce its classic-script bundle")
