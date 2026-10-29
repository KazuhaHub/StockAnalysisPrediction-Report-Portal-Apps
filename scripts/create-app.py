"""Create an unlisted application using the shared React/Ant Design foundation."""
import argparse
import json
import importlib.util
import unicodedata
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


spec = importlib.util.spec_from_file_location("app_authoring", Path(__file__).with_name("app_authoring.py"))
authoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(authoring)


def create(app_id, name, template="legacy", parent_origin=None, publisher="development-publisher"):
    if template not in {"legacy", "v2"}:
        raise ValueError("Unknown application template")
    if template == "v2":
        authoring.parent_origin(parent_origin)
        if not isinstance(name,str) or not name.strip() or len(name)>80 or any(unicodedata.category(c) in {"Cc","Cs"} or c in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069" for c in name):
            raise ValueError("Use a nonblank page name of at most 80 Unicode characters")
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", publisher):
            raise ValueError("Invalid publisher identifier")
    elif parent_origin is not None or publisher != "development-publisher":
        raise ValueError("Origin and publisher options require the v2 template")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", app_id):
        raise ValueError("Use a lowercase application identifier")
    target = authoring.app_folder(ROOT, app_id)
    if target.exists():
        raise ValueError("Refusing to overwrite an existing application")
    source = ROOT / "templates" / ("react-app-v2" if template == "v2" else "react-app")
    shutil.copytree(source, target)
    replacements={"APP_ID":app_id,"APP_NAME_JSON":json.dumps(name),"PARENT_ORIGIN_JSON":json.dumps(parent_origin),"PUBLISHER_JSON":json.dumps(publisher)}
    markers=re.compile("|".join(re.escape(marker) for marker in sorted(replacements,key=len,reverse=True)))
    for path in target.rglob("*"):
        if path.is_file():
            path.write_text(markers.sub(lambda match:replacements[match.group(0)],path.read_text()))
    if template == "v2":
        print(f"Created development v2 {target.relative_to(ROOT)}; run npm install, checks and scripts/build-app-v2.py {app_id}. No catalogue or trust change.")
    else:
        print(f"Created {target.relative_to(ROOT)}; review permissions, run npm install, then validate/build/test. The catalogue was not changed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_id")
    parser.add_argument("--name", required=True)
    parser.add_argument("--template", choices=["legacy", "v2"], default="legacy")
    parser.add_argument("--parent-origin", help="Immutable trusted Portal origin; required for development v2")
    parser.add_argument("--publisher", default="development-publisher")
    args = parser.parse_args()
    create(args.app_id, args.name, args.template, args.parent_origin, args.publisher)
