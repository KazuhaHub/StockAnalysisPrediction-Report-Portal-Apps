"""Generate, typecheck, test and build a fresh application without publishing it."""
import argparse
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("create_app", ROOT / "scripts/create-app.py")
creator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(creator)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--v2-fixture-output", type=Path, help="New directory for public v2 frontend/descriptor browser-fixture bytes")
args=parser.parse_args()
if args.v2_fixture_output and (args.v2_fixture_output.exists() or args.v2_fixture_output.is_symlink()):
    raise ValueError("Fixture output already exists")
builder_spec=importlib.util.spec_from_file_location("build_v2",ROOT/"scripts/build-app-v2.py")
builder=importlib.util.module_from_spec(builder_spec)
builder_spec.loader.exec_module(builder)

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

    creator.create("template-v2-check", "Template v2 check", template="v2", parent_origin="http://127.0.0.1:31935")
    frontend=target/"apps/template-v2-check/frontend"
    for command in ["typecheck", "test"]:
        subprocess.run(["npm", "run", command], cwd=frontend, check=True)
    candidate=builder.build("template-v2-check",root=target)
    if args.v2_fixture_output:
        output=args.v2_fixture_output
        output.mkdir(parents=True,exist_ok=False)
        shutil.copytree(frontend/"dist",output/"child")
        for name in ["frontend.zip", "descriptor.json"]:
            shutil.copyfile(candidate/name,output/name)
