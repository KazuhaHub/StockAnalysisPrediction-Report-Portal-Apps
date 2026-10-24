"""Validate the catalogue and build bounded reproducible app archives."""
import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlsplit, unquote, quote
from urllib.request import HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?")
SCOPES = {"query", "ingest", "notify", "extension.read", "extension.manage"}
PORTAL_REPO = "KazuhaHub/StockAnalysisPrediction-Report-Portal"


class ArtifactRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        u = urlsplit(newurl)
        if u.scheme != "https" or u.username or u.password or u.hostname not in {
            "github.com", "api.github.com", "raw.githubusercontent.com",
            "objects.githubusercontent.com", "release-assets.githubusercontent.com",
        }:
            raise ValueError("refused artifact redirect")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download(url, limit):
    with build_opener(ArtifactRedirect()).open(url, timeout=30) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("remote artifact exceeded its bound")
    return raw


def extension_record(root, m):
    version = m["version"]
    path = root / "apps" / m["id"] / "releases" / (version + ".json")
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("unsafe acceptance record path")
    try:
        record = json.loads(path.read_text())
    except OSError:
        raise ValueError("extension applications require a version-specific acceptance record") from None
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1 or record.get("app_id") != m["id"] or record.get("version") != version:
        raise ValueError("acceptance record identity mismatch")
    minimum = record.get("minimum_portal_release", "")
    match = re.fullmatch(r"v([0-9]{4})\.([1-9]|[1-4][0-9]|5[0-3])(?:\.([1-9][0-9]*))?", minimum)
    if not match or tuple(int(value or 0) for value in match.groups()) < (2026, 43, 2):
        raise ValueError("extension capabilities require Portal v2026.43.2 or later")
    return record


def verify_download(entry, m, record, fetch):
    raw = fetch(entry["url"], 10 * 1024 * 1024)
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        entries = bundle.infolist()
        names = [item.filename for item in entries]
        if len(entries) > 200 or len(set(names)) != len(names) or sum(item.file_size for item in entries) > 10 * 1024 * 1024 or m["entry"] not in names or "app.json" not in names:
            raise ValueError("invalid marketplace archive")
        for item in entries:
            path = Path(item.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("unsafe marketplace archive entry")
        if json.loads(bundle.read("app.json")) != m:
            raise ValueError("published archive and source manifest disagree")
    if record is None:
        return
    u = urlsplit(entry["url"])
    owner, repo = unquote(u.path).strip("/").split("/")[:2]
    tag = m["id"] + "/v" + m["version"]
    for repository, release_tag in [(owner + "/" + repo, tag), (PORTAL_REPO, record["minimum_portal_release"])]:
        release = json.loads(fetch("https://api.github.com/repos/" + repository + "/releases/tags/" + quote(release_tag, safe=""), 2 * 1024 * 1024))
        if release.get("draft") is not False or not release.get("published_at") or release.get("tag_name") != release_tag:
            raise ValueError("application and compatible Portal releases must both be published")
    base = entry["url"].rsplit("/", 1)[0]
    metadata_raw = fetch(base + "/release.json", 1024 * 1024)
    metadata = json.loads(metadata_raw)
    for key, value in record.items():
        actual = metadata.get("image", {}).get("runtime_image") if key == "runtime_image" else metadata.get(key)
        if actual != value:
            raise ValueError("published metadata and acceptance record disagree")
    if metadata.get("tag") != tag or not re.fullmatch(r"[a-f0-9]{40}", metadata.get("source_commit", "")):
        raise ValueError("invalid published release provenance")
    api = "https://api.github.com/repos/" + owner + "/" + repo
    ref = json.loads(fetch(api + "/git/ref/tags/" + quote(tag, safe=""), 65536)).get("object", {})
    for _ in range(3):
        if ref.get("type") != "tag":
            break
        if not re.fullmatch(r"[a-f0-9]{40}", ref.get("sha", "")):
            raise ValueError("invalid annotated release tag")
        ref = json.loads(fetch(api + "/git/tags/" + ref["sha"], 65536)).get("object", {})
    if ref.get("type") != "commit" or ref.get("sha") != metadata["source_commit"]:
        raise ValueError("published tag and release source commit disagree")
    sums = {}
    for line in fetch(base + "/SHA256SUMS", 65536).decode().splitlines():
        match = re.fullmatch(r"([a-f0-9]{64}) [ *]([A-Za-z0-9_.-]+)", line)
        if not match or match[2] in sums:
            raise ValueError("invalid published checksum list")
        sums[match[2]] = match[1]
    name = m["id"] + ".zip"
    digest = hashlib.sha256(raw).hexdigest()
    if sums.get(name) != digest or metadata.get("artifacts", {}).get(name) != digest or sums.get("release.json") != hashlib.sha256(metadata_raw).hexdigest():
        raise ValueError("published catalogue artifact checksum mismatch")


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


def check(root=ROOT, verify_downloads=False, fetch=download):
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
        u = urlsplit(entry.get("url", ""))
        if u.scheme != "https" or u.username or u.password or u.query or u.fragment or not u.hostname:
            raise ValueError("invalid download URL")
        immutable = (u.hostname == "github.com" and re.fullmatch(
            r"/[^/]+/[^/]+/releases/download/" + re.escape(app_id + "/v" + m["version"] + "/" + app_id + ".zip"), unquote(u.path)))
        # The original demo archive has an explicitly pinned immutable source commit.
        legacy = app_id == "demo-symbols" and u.hostname == "raw.githubusercontent.com" and re.fullmatch(r"/" + PORTAL_REPO + r"/[a-f0-9]{40}/apps/demo-symbols\.zip", u.path)
        if not (immutable or legacy) or not u.path.endswith(".zip"):
            raise ValueError("download must reference an immutable ZIP")
        if any(part.lower() in {"dev", "snapshot"} for part in re.split(r"[.-]", m["version"])):
            raise ValueError("development versions cannot enter the catalogue")
        record = extension_record(root, m) if any(s.startswith("extension.") for s in m["scopes"]) else None
        if verify_downloads:
            verify_download(entry, m, record, fetch)
    return len(ids)


def export_legacy(portal_root, root=ROOT, fetch=download):
    """Refresh retained legacy entries without changing selection or archive bytes."""
    canonical_before = (root / "index.json").read_bytes()
    cache = {}

    def cached_fetch(url, limit):
        if url not in cache:
            cache[url] = fetch(url, limit)
        if len(cache[url]) > limit:
            raise ValueError("remote artifact exceeded its bound")
        return cache[url]

    check(root, verify_downloads=True, fetch=cached_fetch)
    if (root / "index.json").read_bytes() != canonical_before:
        raise ValueError("canonical catalogue changed during verification")
    canonical = {entry["id"]: entry for entry in json.loads(canonical_before)["apps"]}
    apps = Path(portal_root).resolve() / "apps"
    target = apps / "index.json"
    if apps.is_symlink() or target.is_symlink():
        raise ValueError("symlinked legacy catalogue is forbidden")
    before = target.read_bytes()
    legacy = json.loads(before)
    if set(legacy) != {"apps"} or not isinstance(legacy["apps"], list):
        raise ValueError("invalid legacy catalogue")
    output, seen = [], set()
    for entry in legacy["apps"]:
        app_id = entry.get("id")
        if app_id in seen or app_id not in canonical:
            raise ValueError("duplicate or missing canonical legacy identity")
        seen.add(app_id)
        source = canonical[app_id]
        if not set(source["scopes"]).issubset({"query", "ingest"}):
            raise ValueError("new capabilities cannot be exported to the legacy catalogue")
        relative = entry.get("path", "")
        if entry.get("url") or not isinstance(relative, str) or not relative:
            raise ValueError("legacy entries must retain their local ZIP paths")
        archive = apps / relative
        if archive.is_symlink() or not archive.resolve().is_relative_to(apps) or not archive.is_file() or archive.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("unsafe or missing legacy ZIP")
        published = cached_fetch(source["url"], 10 * 1024 * 1024)
        if hashlib.sha256(archive.read_bytes()).digest() != hashlib.sha256(published).digest():
            raise ValueError("legacy ZIP differs from the verified canonical download; review its sources and compatibility first")
        projected = {key: source[key] for key in ["id", "name", "icon", "version", "description", "scopes"] if key in source}
        projected["path"] = relative
        output.append(projected)
    rendered = (json.dumps({"apps": output}, indent=2, ensure_ascii=False) + "\n").encode()
    if target.is_symlink() or target.read_bytes() != before:
        raise ValueError("legacy catalogue changed during verification")
    if rendered == before:
        return target
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=apps, prefix=".legacy-index-", delete=False) as file:
            temporary = Path(file.name)
            file.write(rendered)
            os.fchmod(file.fileno(), stat.S_IMODE(target.stat().st_mode))
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target


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
    parser.add_argument("command", choices=["check", "package", "export-legacy"])
    parser.add_argument("app_id", nargs="?")
    parser.add_argument("--verify-downloads", action="store_true", help="verify published archives and extension release provenance")
    parser.add_argument("--portal-root", type=Path, help="Portal checkout for explicit legacy catalogue maintenance")
    args = parser.parse_args()
    try:
        if args.command == "check":
            print(f"Validated {check(verify_downloads=args.verify_downloads)} catalogue entries")
        elif args.command == "export-legacy":
            if args.portal_root is None:
                parser.error("export-legacy requires --portal-root")
            print(export_legacy(args.portal_root))
        elif not args.app_id:
            parser.error("package requires an application ID")
        else:
            print(package(args.app_id))
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as err:
        print(f"Validation failed: {err}", file=sys.stderr)
        sys.exit(1)
