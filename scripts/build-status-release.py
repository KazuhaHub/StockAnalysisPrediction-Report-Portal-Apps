"""Build app-qualified Status artifacts without publishing or changing the catalogue."""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"linux-amd64": ("linux", "amd64", ""), "linux-arm64": ("linux", "arm64", ""),
           "linux-armv7": ("linux", "arm", "7"), "darwin-amd64": ("darwin", "amd64", ""),
           "darwin-arm64": ("darwin", "arm64", ""), "windows-amd64": ("windows", "amd64", "")}


def archive(binary, target, output):
    name = "status.exe" if target.startswith("windows-") else "status"
    if name.endswith(".exe"):
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100755 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, binary.read_bytes())
    else:
        with output.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as bundle:
                info = tarfile.TarInfo(name)
                info.size = binary.stat().st_size
                info.mode = 0o755
                bundle.addfile(info, io.BytesIO(binary.read_bytes()))


def build(targets, destination):
    manifest = json.loads((ROOT / "apps/status/app.json").read_text())
    version = manifest["version"]
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("invalid Status version")
    if len(set(targets)) != len(targets) or any(target not in TARGETS for target in targets):
        raise ValueError("invalid or duplicate build target")
    output = destination / "status" / version
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("refusing to overwrite existing artifact directory")
    subprocess.run(["python3", str(ROOT / "scripts/build-status-frontend.py")], cwd=ROOT, check=True)
    spec = importlib.util.spec_from_file_location("catalogue", ROOT / "scripts/catalogue.py")
    catalogue = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalogue)
    frontend = catalogue.package("status")
    (output / "status.zip").write_bytes(frontend.read_bytes())
    env = {**os.environ, "GOWORK": "off", "CGO_ENABLED": "0"}
    with tempfile.TemporaryDirectory(prefix="status-release-build-") as temporary:
        for target in targets:
            goos, goarch, goarm = TARGETS[target]
            binary = Path(temporary) / ("status.exe" if goos == "windows" else "status")
            build_env = {**env, "GOOS": goos, "GOARCH": goarch, "GOARM": goarm}
            subprocess.run(["go", "build", "-trimpath", "-buildvcs=false", "-ldflags", "-s -w -buildid= -X main.version=" + version, "-o", str(binary), "./cmd/status"], cwd=ROOT / "apps/status/service", env=build_env, check=True)
            suffix = ".zip" if goos == "windows" else ".tar.gz"
            archive(binary, target, output / ("status-v" + version + "-" + target + suffix))
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, text=True).strip())
    metadata = {"app_id": "status", "version": version, "source_commit": revision,
                "source_dirty": dirty, "targets": sorted(targets), "publication": "not-published",
                "required_portal_capabilities": ["extension.read", "extension.manage", "notification-publisher-identity"],
                "minimum_released_portal_version": None}
    (output / "build.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    sums = [hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name for path in sorted(output.iterdir()) if path.is_file()]
    (output / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", action="append", choices=sorted(TARGETS), help="Repeat for selected targets; default builds all six")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/artifacts")
    args = parser.parse_args()
    print(build(args.target or list(TARGETS), args.output.resolve()))
