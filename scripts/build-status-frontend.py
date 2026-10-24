"""Build a self-contained classic-script app compatible with a null-origin iframe."""
import json
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "apps" / "status" / "frontend"
locales = {name: json.loads((root / "locales" / f"{name}.json").read_text()) for name in ["en-US", "zh-CN", "zh-TW"]}
keys = set(locales["en-US"])
if any(set(value) != keys for value in locales.values()):
    raise ValueError("Status locale keys differ")
output = root / "dist"
subprocess.run(["npm", "run", "build", "--workspace=portal-status-ui"], cwd=root.parents[2], check=True)
output.mkdir(parents=True, exist_ok=True)
shutil.copyfile(root / "src" / "index.html", output / "index.html")

public = root.parents[0] / "service" / "internal" / "status" / "public"
public.mkdir(parents=True, exist_ok=True)
subprocess.run(["npm", "run", "build:public", "--workspace=portal-status-ui"], cwd=root.parents[2], check=True)
shutil.copyfile(root / "public-src" / "index.html", public / "index.html")
