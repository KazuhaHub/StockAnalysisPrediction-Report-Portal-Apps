"""Validate the catalogue and build bounded reproducible app archives."""
import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?")
SCOPES = {"query", "ingest", "notify", "extension.read", "extension.manage"}


def manifest(root, app_id):
    if not SLUG.fullmatch(app_id):
        raise ValueError("invalid application ID")
    folder = root / "apps" / app_id
    data = json.loads((folder / "app.json").read_text())
    if data.get("id") != app_id or not VERSION.fullmatch(data.get("version", "")):
        raise ValueError("manifest identity/version mismatch")
    if not data.get("name") or data.get("entry") != "index.html":
        raise ValueError("name and root HTML entry required")
    scopes = data.get("scopes")
    if not isinstance(scopes, list) or any(s not in SCOPES for s in scopes) or len(set(scopes)) != len(scopes):
        raise ValueError("invalid capability declaration")
    return data


def check(root=ROOT):
    data = json.loads((root / "index.json").read_text())
    if set(data) != {"apps"} or not isinstance(data["apps"], list):
        raise ValueError("invalid catalogue envelope")
    ids = set()
    for entry in data["apps"]:
        app_id = entry.get("id", "")
        if app_id in ids:
            raise ValueError("duplicate application ID")
        ids.add(app_id)
        m = manifest(root, app_id)
        if entry.get("version") != m["version"] or entry.get("scopes") != m["scopes"]:
            raise ValueError("catalogue and package declarations disagree")
        from urllib.parse import urlsplit, unquote
        u = urlsplit(entry.get("url", ""))
        if u.scheme != "https" or u.username or u.password or u.query or u.fragment or not u.hostname:
            raise ValueError("invalid download URL")
        immutable = (u.hostname == "github.com" and unquote(u.path).endswith(
            "/releases/download/" + app_id + "/v" + m["version"] + "/" + app_id + ".zip"))
        # The original demo archive has an explicitly pinned immutable source commit.
        legacy = u.hostname == "raw.githubusercontent.com" and re.search(r"/[a-f0-9]{40}/apps/demo-symbols\.zip$", u.path)
        if not (immutable or legacy) or not u.path.endswith(".zip"):
            raise ValueError("download must reference an immutable ZIP")
        if any(s.startswith("extension.") for s in m["scopes"]):
            raise ValueError("unreleased extension capabilities cannot enter the catalogue")
    return len(ids)


def package(app_id, root=ROOT):
    m = manifest(root, app_id)
    folder = root / "apps" / app_id
    assets = folder / "frontend" / "dist"
    if not assets.is_dir():
        # Static reference apps do not need a compiler.
        assets = folder / "frontend"
    if folder.is_symlink() or (folder / "app.json").is_symlink() or (folder / "frontend").is_symlink() or assets.is_symlink():
        raise ValueError("symlinked package roots are forbidden")
    files = [("app.json", folder / "app.json")]
    for f in sorted(assets.rglob("*")):
        if f.is_symlink():
            raise ValueError("symlinks are forbidden")
        if not f.is_file():
            continue
        rel = f.relative_to(assets)
        if any(part.startswith(".") or part in {"node_modules", "src"} for part in rel.parts):
            raise ValueError("development/private file in assets")
        if f.suffix.lower() not in {".html", ".js", ".css", ".svg", ".png", ".jpg", ".webp", ".woff2", ".json"}:
            raise ValueError("unsupported/private asset")
        if rel.as_posix() == "app.json":
            raise ValueError("duplicate manifest")
        files.append((rel.as_posix(), f))
    if not any(name == m["entry"] for name, _ in files):
        raise ValueError("missing entry asset")
    if len(files) > 200 or sum(f.stat().st_size for _, f in files) > 10 * 1024 * 1024:
        raise ValueError("package limit exceeded")
    out = root / "dist" / app_id / m["version"]
    out.mkdir(parents=True, exist_ok=True)
    target = out / (app_id + ".zip")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, file in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(info, file.read_bytes())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (out / "SHA256SUMS").write_text(digest + "  " + target.name + "\n")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "package"])
    parser.add_argument("app_id", nargs="?")
    args = parser.parse_args()
    try:
        if args.command == "check":
            print(f"Validated {check()} catalogue entries")
        elif not args.app_id:
            parser.error("package requires an application ID")
        else:
            print(package(args.app_id))
    except (ValueError, OSError, KeyError, TypeError) as err:
        print(f"Validation failed: {err}", file=sys.stderr)
        sys.exit(1)
