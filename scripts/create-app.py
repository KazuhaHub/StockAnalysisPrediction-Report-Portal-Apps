"""Create an unlisted application using the shared React/Ant Design foundation."""
import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def create(app_id, name):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", app_id):
        raise ValueError("Use a lowercase application identifier")
    target = ROOT / "apps" / app_id
    if target.exists():
        raise ValueError("Refusing to overwrite an existing application")
    source = ROOT / "templates" / "react-app"
    shutil.copytree(source, target)
    for path in target.rglob("*"):
        if path.is_file():
            path.write_text(path.read_text().replace("APP_ID", app_id).replace("APP_NAME_JSON", json.dumps(name)))
    print(f"Created {target.relative_to(ROOT)}; review permissions, run npm install, then validate/build/test. The catalogue was not changed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_id")
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    create(args.app_id, args.name)
