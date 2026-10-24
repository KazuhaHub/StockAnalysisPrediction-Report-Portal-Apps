"""Build a self-contained standard app without publishing it."""
import argparse
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(app_id):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", app_id):
        raise ValueError("Invalid application identifier")
    frontend = ROOT / "apps" / app_id / "frontend"
    if not (frontend / "package.json").is_file():
        raise ValueError("Application frontend workspace is missing")
    subprocess.run(["npm", "run", "build", "--workspace=apps/" + app_id + "/frontend"], cwd=ROOT, check=True)
    shutil.copyfile(frontend / "src/index.html", frontend / "dist/index.html")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_id")
    build(parser.parse_args().app_id)
