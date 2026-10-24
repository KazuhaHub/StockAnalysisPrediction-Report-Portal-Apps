"""Prepare, verify and explicitly publish immutable Status release artifacts."""
import argparse
import base64
import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APPS_REPO = "KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps"
PORTAL_REPO = "KazuhaHub/StockAnalysisPrediction-Report-Portal"
IMAGE = "ghcr.io/" + APPS_REPO.lower() + "/status"
TARGETS = {"linux-amd64", "linux-arm64", "linux-armv7", "darwin-amd64", "darwin-arm64", "windows-amd64"}
EVIDENCE = {"provider_capabilities", "authority", "storage_recovery", "fault_drills", "accessibility", "operator_review"}
REQUIRED_JOBS = {"catalogue", "protocol", "status", "status-browser", "status-container", "workflow-lint"} | {"status-artifacts (" + target + ")" for target in TARGETS}
SHA = re.compile(r"[a-f0-9]{40}")
DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
CALVER = re.compile(r"v[0-9]{4}\.(?:[1-9]|[1-4][0-9]|5[0-3])(?:\.[1-9][0-9]*)?")
LIMIT = 256 * 1024 * 1024


def validate_version(version):
    if not isinstance(version, str) or len(version) > 64 or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("invalid release version")
    suffix = version.partition("-")[2]
    if suffix and any(not part or (part.isdigit() and len(part) > 1 and part.startswith("0")) or part.lower() in {"dev", "snapshot"} for part in re.split(r"[.-]", suffix)):
        raise ValueError("development or invalid prerelease version")
    return version


def release_contract(root, version, confirmation):
    validate_version(version)
    if confirmation != "status/v" + version:
        raise ValueError("confirmation must match the exact app-qualified release tag")
    manifest_path = root / "apps/status/app.json"
    approval_dir = root / "apps/status/releases"
    for target in [manifest_path, approval_dir]:
        if any((root / Path(*target.relative_to(root).parts[:length])).is_symlink() for length in range(len(target.relative_to(root).parts) + 1)):
            raise ValueError("symlinked release source paths are forbidden")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("id") != "status" or manifest.get("version") != version or manifest.get("scopes") != ["extension.read", "extension.manage"]:
        raise ValueError("release and manifest identity/capabilities disagree")
    path = root / "apps/status/releases" / (version + ".json")
    if path.is_symlink() or not path.is_file():
        raise ValueError("a committed version-specific acceptance record is required")
    record = json.loads(path.read_text())
    if set(record) != {"schema_version", "app_id", "version", "minimum_portal_release", "runtime_image", "evidence"} or type(record.get("schema_version")) is not int or record["schema_version"] != 1 or record["app_id"] != "status" or record["version"] != version:
        raise ValueError("invalid acceptance record")
    if not isinstance(record["minimum_portal_release"], str) or not CALVER.fullmatch(record["minimum_portal_release"]):
        raise ValueError("a released Portal CalVer tag is required")
    if not isinstance(record["runtime_image"], str) or not re.fullmatch(r"gcr\.io/distroless/static-debian12:nonroot@sha256:[a-f0-9]{64}", record["runtime_image"]):
        raise ValueError("the approved runtime image must be pinned by digest")
    evidence = record["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != EVIDENCE:
        raise ValueError("every pre-publication acceptance gate needs evidence")
    for reference in evidence.values():
        if not isinstance(reference, str) or len(reference) > 2048:
            raise ValueError("invalid acceptance evidence reference")
        url = urllib.parse.urlsplit(reference)
        if url.scheme == "https" and url.hostname and not url.username and not url.password:
            continue
        target = (root / reference).resolve()
        if not reference.startswith("docs/") or not target.is_relative_to(root.resolve()) or not target.is_file():
            raise ValueError("evidence must reference a reviewed HTTPS page or repository document")
    return {**record, "tag": "status/v" + version, "manifest": manifest, "image": IMAGE + ":" + version}


def verified_ci(runs, sha):
    if not SHA.fullmatch(sha):
        raise ValueError("invalid source commit")
    for run in runs:
        if run.get("head_sha") == sha and run.get("head_branch") == "main" and run.get("event") == "push" and run.get("path") == ".github/workflows/check.yml" and run.get("status") == "completed" and run.get("conclusion") == "success" and type(run.get("id")) is int:
            return run["id"]
    raise ValueError("full main-branch push CI has not passed for the exact source commit")


def verified_jobs(jobs):
    if not REQUIRED_JOBS.issubset({job.get("name") for job in jobs}) or any(job.get("status") != "completed" or job.get("conclusion") != "success" for job in jobs):
        raise ValueError("all required CI jobs must have completed successfully")


def checksums(text):
    result = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([a-f0-9]{64}) [ *]([A-Za-z0-9_.-]+)", line)
        if not match or match[2] in {".", ".."} or match[2] in result:
            raise ValueError("invalid or duplicate checksum entry")
        result[match[2]] = match[1]
    if not result:
        raise ValueError("empty checksum file")
    return result


def tar_binary(raw, name):
    found, seen, total = None, set(), 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            total += member.size
            if len(seen) >= 32 or path.is_absolute() or ".." in path.parts or "\\" in member.name or member.name in seen or not (member.isfile() or member.isdir()) or total > LIMIT:
                raise ValueError("unsafe service archive")
            seen.add(member.name)
            if member.name == name:
                if not member.isfile() or not 0 < member.size <= LIMIT:
                    raise ValueError("invalid executable entry")
                found = archive.extractfile(member).read(LIMIT + 1)
    if found is None or len(found) > LIMIT:
        raise ValueError("missing or oversized executable")
    return found


class GitHubRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        url = urllib.parse.urlsplit(newurl)
        if url.scheme != "https" or url.hostname not in {"api.github.com", "github.com", "uploads.github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com", "ghcr.io"} or url.username or url.password:
            raise ValueError("refused artifact redirect")
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if redirected and url.hostname != urllib.parse.urlsplit(request.full_url).hostname:
            redirected.remove_header("Authorization")
        return redirected


def fetch(url, maximum, headers=None, data=None, method="GET", optional=False):
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.build_opener(GitHubRedirect()).open(request, timeout=120) as response:
            raw = response.read(maximum + 1)
            if len(raw) > maximum:
                raise ValueError("remote artifact exceeded its bound")
            return raw
    except urllib.error.HTTPError as error:
        if optional and error.code == 404:
            return None
        raise ValueError("remote request failed with HTTP " + str(error.code)) from None
    except urllib.error.URLError:
        raise ValueError("remote artifact request failed") from None


class GitHub:
    def __init__(self, token):
        self.token = token

    def headers(self, accept="application/vnd.github+json"):
        return {"Authorization": "Bearer " + self.token, "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}

    def api(self, path, data=None, method="GET", optional=False):
        headers = self.headers()
        if data is not None:
            headers["Content-Type"] = "application/json"
        raw = fetch("https://api.github.com/" + path, 2 * 1024 * 1024, headers, None if data is None else json.dumps(data).encode(), method, optional)
        return None if raw is None else json.loads(raw)

    def absent(self, tag):
        encoded = urllib.parse.quote(tag, safe="")
        if self.api("repos/" + APPS_REPO + "/releases/tags/" + encoded, optional=True) is not None or self.api("repos/" + APPS_REPO + "/git/ref/tags/" + encoded, optional=True) is not None:
            raise ValueError("release version is already reserved; existing tags/releases are never replaced")

    def upload(self, release_id, file):
        raw = file.read_bytes()
        if len(raw) > LIMIT:
            raise ValueError("oversized upload")
        url = "https://uploads.github.com/repos/" + APPS_REPO + "/releases/" + str(release_id) + "/assets?" + urllib.parse.urlencode({"name": file.name})
        headers = {**self.headers(), "Content-Type": "application/octet-stream"}
        asset = json.loads(fetch(url, 2 * 1024 * 1024, headers, raw, "POST"))
        if asset.get("name") != file.name or asset.get("size") != len(raw) or type(asset.get("id")) is not int:
            raise ValueError("upload metadata does not match the artifact")
        downloaded = fetch("https://api.github.com/repos/" + APPS_REPO + "/releases/assets/" + str(asset["id"]), LIMIT, self.headers("application/octet-stream"))
        if hashlib.sha256(downloaded).digest() != hashlib.sha256(raw).digest():
            raise ValueError("draft asset failed download verification")


def workflow_context(root):
    if os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get("GITHUB_REPOSITORY") != APPS_REPO or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise ValueError("publication must be explicitly dispatched from this repository's main branch")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if sha != os.environ.get("GITHUB_SHA") or subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root, text=True).strip():
        raise ValueError("publication requires the exact clean workflow source commit")
    return sha


def validated_plan(plan):
    validate_version(plan.get("version"))
    version = plan["version"]
    required = {"schema_version", "app_id", "version", "minimum_portal_release", "runtime_image", "evidence", "tag", "manifest", "image", "source_commit", "ci_run_id", "notes", "minimum_portal_release_id", "minimum_portal_archive_sha256", "minimum_portal_binary_sha256"}
    if set(plan) != required or type(plan["schema_version"]) is not int or plan["schema_version"] != 1 or plan["app_id"] != "status" or plan["tag"] != "status/v" + version or plan["image"] != IMAGE + ":" + version:
        raise ValueError("invalid release plan identity")
    if not isinstance(plan["source_commit"], str) or not SHA.fullmatch(plan["source_commit"]) or any(type(plan[key]) is not int or plan[key] <= 0 for key in ["ci_run_id", "minimum_portal_release_id"]):
        raise ValueError("invalid release plan provenance")
    if any(not isinstance(plan[key], str) or not re.fullmatch(r"[a-f0-9]{64}", plan[key]) for key in ["minimum_portal_archive_sha256", "minimum_portal_binary_sha256"]):
        raise ValueError("invalid released Portal verification hashes")
    if not isinstance(plan["minimum_portal_release"], str) or not CALVER.fullmatch(plan["minimum_portal_release"]) or not isinstance(plan["runtime_image"], str) or not re.fullmatch(r"gcr\.io/distroless/static-debian12:nonroot@sha256:[a-f0-9]{64}", plan["runtime_image"]):
        raise ValueError("invalid release compatibility or runtime pin")
    manifest = plan["manifest"]
    if not isinstance(manifest, dict) or manifest.get("id") != "status" or manifest.get("version") != version or manifest.get("scopes") != ["extension.read", "extension.manage"]:
        raise ValueError("release plan manifest mismatch")
    if not isinstance(plan["notes"], str) or not plan["notes"].strip() or len(plan["notes"]) > 32768 or not isinstance(plan["evidence"], dict) or set(plan["evidence"]) != EVIDENCE:
        raise ValueError("invalid release notes or acceptance evidence")


def verified_source(plan, github, root=ROOT):
    validated_plan(plan)
    sha = workflow_context(root)
    contract = release_contract(root, plan["version"], plan["tag"])
    if sha != plan["source_commit"] or any(plan[key] != value for key, value in contract.items()) or os.environ.get("RELEASE_NOTES", "").strip() != plan["notes"]:
        raise ValueError("release plan differs from the reviewed workflow source")
    runs = github.api("repos/" + APPS_REPO + "/actions/workflows/check.yml/runs?" + urllib.parse.urlencode({"head_sha": sha, "event": "push", "status": "success", "per_page": 100}))
    ci = verified_ci(runs.get("workflow_runs", []), sha)
    if ci != plan["ci_run_id"]:
        raise ValueError("release CI provenance differs from current exact-source evidence")
    verified_jobs(github.api("repos/" + APPS_REPO + "/actions/runs/" + str(ci) + "/jobs?filter=latest&per_page=100").get("jobs", []))


def prepare(root, version, confirmation, output, github):
    sha = workflow_context(root)
    contract = release_contract(root, version, confirmation)
    notes = os.environ.get("RELEASE_NOTES", "").strip()
    if not notes or len(notes) > 32768:
        raise ValueError("nonempty bounded release notes are required")
    runs = github.api("repos/" + APPS_REPO + "/actions/workflows/check.yml/runs?" + urllib.parse.urlencode({"head_sha": sha, "event": "push", "status": "success", "per_page": 100}))
    ci = verified_ci(runs.get("workflow_runs", []), sha)
    verified_jobs(github.api("repos/" + APPS_REPO + "/actions/runs/" + str(ci) + "/jobs?filter=latest&per_page=100").get("jobs", []))
    github.absent(contract["tag"])
    minimum = contract["minimum_portal_release"]
    portal = github.api("repos/" + PORTAL_REPO + "/releases/tags/" + minimum)
    if portal.get("tag_name") != minimum or portal.get("draft") is not False or not portal.get("published_at"):
        raise ValueError("minimum Portal version is not a published release")
    archive_name = "report-portal_" + minimum + "_linux_amd64.tar.gz"
    assets = {asset["name"]: asset for asset in portal.get("assets", [])}
    if len(assets) != len(portal.get("assets", [])) or any(name not in assets or type(assets[name].get("size")) is not int or not 0 < assets[name]["size"] <= LIMIT for name in [archive_name, "SHA256SUMS.txt"]):
        raise ValueError("published Portal release is missing bounded verification assets")
    prefix = "https://github.com/" + PORTAL_REPO + "/releases/download/" + minimum + "/"
    sums = checksums(fetch(prefix + "SHA256SUMS.txt", 1024 * 1024).decode("ascii"))
    archive = fetch(prefix + archive_name, LIMIT)
    digest = hashlib.sha256(archive).hexdigest()
    if sums.get(archive_name) != digest or len(archive) != assets[archive_name]["size"]:
        raise ValueError("released Portal archive failed checksum/size verification")
    binary = tar_binary(archive, "report-portal_" + minimum + "_linux_amd64/report-portal")
    output.mkdir(parents=True, exist_ok=False)
    target = output / "report-portal"
    target.write_bytes(binary)
    target.chmod(0o700)
    plan = {**contract, "source_commit": sha, "ci_run_id": ci, "notes": notes, "minimum_portal_release_id": portal["id"], "minimum_portal_archive_sha256": digest, "minimum_portal_binary_sha256": hashlib.sha256(binary).hexdigest()}
    (output / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as stream:
            for key, value in {"version": version, "tag": plan["tag"], "image": plan["image"], "runtime_image": plan["runtime_image"], "portal_binary": str(target.resolve())}.items():
                stream.write(key + "=" + value + "\n")
    return plan


def artifact_names(version):
    return {"status.zip", "build.json"} | {"status-v" + version + "-" + target + (".zip" if target.startswith("windows") else ".tar.gz") for target in TARGETS}


def verified_artifacts(plan, folder, finalized=False):
    validated_plan(plan)
    expected = artifact_names(plan["version"]) | ({"release.json"} if finalized else set())
    if {entry.name for entry in folder.iterdir()} != expected | {"SHA256SUMS"} or any(entry.is_symlink() or not entry.is_file() for entry in folder.iterdir()):
        raise ValueError("artifact directory contains missing or unexpected files")
    sums = checksums((folder / "SHA256SUMS").read_text())
    if set(sums) != expected:
        raise ValueError("artifact checksum set is incomplete")
    for name, digest in sums.items():
        file = folder / name
        if file.stat().st_size > LIMIT or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError("artifact checksum mismatch")
    build = json.loads((folder / "build.json").read_text())
    if build.get("app_id") != "status" or build.get("version") != plan["version"] or build.get("source_commit") != plan["source_commit"] or build.get("source_dirty") is not False or not isinstance(build.get("targets"), list) or sorted(build.get("targets", [])) != sorted(TARGETS) or build.get("publication") != "not-published" or build.get("required_portal_capabilities") != ["extension.read", "extension.manage", "notification-publisher-identity"]:
        raise ValueError("build provenance/complete target set does not match the reviewed source")
    with zipfile.ZipFile(folder / "status.zip") as bundle:
        entries = bundle.infolist()
        names = [item.filename for item in entries]
        extensions = {".html", ".js", ".css", ".svg", ".png", ".jpg", ".webp", ".woff2", ".json"}
        if len(entries) > 200 or len(names) != len(set(names)) or sum(item.file_size for item in entries) > 10 * 1024 * 1024 or "index.html" not in names or "app.json" not in names:
            raise ValueError("invalid frontend archive")
        for item in entries:
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename or any(part.startswith(".") or part in {"node_modules", "src"} for part in path.parts) or path.suffix.lower() not in extensions or item.is_dir() or not stat.S_ISREG(item.external_attr >> 16):
                raise ValueError("private, development or nonregular frontend asset")
        if json.loads(bundle.read("app.json")) != plan["manifest"]:
            raise ValueError("frontend manifest changed during packaging")
    for target in TARGETS:
        file = folder / ("status-v" + plan["version"] + "-" + target + (".zip" if target.startswith("windows") else ".tar.gz"))
        if target.startswith("windows"):
            with zipfile.ZipFile(file) as bundle:
                if bundle.namelist() != ["status.exe"] or not 0 < bundle.infolist()[0].file_size <= LIMIT or stat.S_ISLNK(bundle.infolist()[0].external_attr >> 16):
                    raise ValueError("invalid Windows service archive")
                bundle.read("status.exe")
        else:
            with tarfile.open(file) as bundle:
                if bundle.getnames() != ["status"]:
                    raise ValueError("service archive contains unexpected entries")
            tar_binary(file.read_bytes(), "status")
    if finalized:
        metadata = json.loads((folder / "release.json").read_text())
        digest = metadata.get("image", {}).get("digest", "")
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest) or metadata != release_metadata(plan, {key: value for key, value in sums.items() if key != "release.json"}, digest):
            raise ValueError("final metadata is not bound to the complete reviewed release")
    return sums


def image_context(plan, artifacts, output):
    verified_artifacts(plan, artifacts)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(ROOT / "apps/status/deploy/Dockerfile.release", output / "Dockerfile")
    for target in ["linux-amd64", "linux-arm64"]:
        directory = output / target
        directory.mkdir()
        binary = tar_binary((artifacts / ("status-v" + plan["version"] + "-" + target + ".tar.gz")).read_bytes(), "status")
        (directory / "status").write_bytes(binary)
        (directory / "status").chmod(0o755)


def image_absent(plan, token, actor):
    validated_plan(plan)
    if not token or not actor:
        raise ValueError("registry credentials and operator are required")
    if plan["image"] != IMAGE + ":" + plan["version"]:
        raise ValueError("unexpected image destination")
    path = IMAGE.removeprefix("ghcr.io/")
    credentials = base64.b64encode((actor + ":" + token).encode()).decode()
    auth = json.loads(fetch("https://ghcr.io/token?" + urllib.parse.urlencode({"service": "ghcr.io", "scope": "repository:" + path + ":pull,push"}), 65536, {"Authorization": "Basic " + credentials}))
    bearer = auth.get("token") or auth.get("access_token")
    if not isinstance(bearer, str) or not bearer:
        raise ValueError("registry authorization failed")
    existing = fetch("https://ghcr.io/v2/" + path + "/manifests/" + plan["version"], 2 * 1024 * 1024, {"Authorization": "Bearer " + bearer, "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json"}, optional=True)
    if existing is not None:
        raise ValueError("image version already exists and must not be repointed")


def release_metadata(plan, sums, digest):
    release = {key: plan[key] for key in ["schema_version", "app_id", "version", "minimum_portal_release", "source_commit", "ci_run_id", "minimum_portal_release_id", "minimum_portal_archive_sha256", "minimum_portal_binary_sha256", "evidence"]}
    release.update({"tag": plan["tag"], "image": {"reference": plan["image"], "digest": digest, "platforms": ["linux/amd64", "linux/arm64"], "runtime_image": plan["runtime_image"]}, "artifacts": dict(sums)})
    return release


def finalize(plan, artifacts, digest):
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise ValueError("invalid immutable image digest")
    sums = verified_artifacts(plan, artifacts)
    path = artifacts / "release.json"
    release = release_metadata(plan, sums, digest)
    path.write_text(json.dumps(release, indent=2, sort_keys=True) + "\n")
    sums["release.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (artifacts / "SHA256SUMS").write_text("".join(sums[name] + "  " + name + "\n" for name in sorted(sums)))


def verify_public(plan, artifacts, github):
    verified_artifacts(plan, artifacts, True)
    release = github.api("repos/" + APPS_REPO + "/releases/tags/" + urllib.parse.quote(plan["tag"], safe=""))
    expected = artifact_names(plan["version"]) | {"release.json", "SHA256SUMS"}
    if release.get("tag_name") != plan["tag"] or release.get("draft") is not False or len(release.get("assets", [])) != len(expected) or {item["name"] for item in release.get("assets", [])} != expected:
        raise ValueError("published release is incomplete")
    prefix = "https://github.com/" + APPS_REPO + "/releases/download/" + urllib.parse.quote(plan["tag"], safe="") + "/"
    for name in sorted(expected):
        raw = fetch(prefix + name, LIMIT)
        if hashlib.sha256(raw).digest() != hashlib.sha256((artifacts / name).read_bytes()).digest():
            raise ValueError("public artifact checksum mismatch")


def publish(plan, artifacts, github, actor):
    verified_source(plan, github)
    verified_artifacts(plan, artifacts, True)
    metadata = json.loads((artifacts / "release.json").read_text())
    if metadata.get("source_commit") != plan["source_commit"] or metadata.get("minimum_portal_release") != plan["minimum_portal_release"] or metadata.get("image", {}).get("reference") != plan["image"] or not DIGEST.fullmatch(metadata.get("image", {}).get("digest", "")):
        raise ValueError("final release metadata disagrees with the reviewed plan")
    github.absent(plan["tag"])
    profile = github.api("users/" + urllib.parse.quote(actor, safe=""))
    if profile.get("type") != "User" or profile.get("login", "").lower() != actor.lower() or type(profile.get("id")) is not int:
        raise ValueError("an identified human release operator is required")
    tag = github.api("repos/" + APPS_REPO + "/git/tags", {"tag": plan["tag"], "message": plan["notes"], "object": plan["source_commit"], "type": "commit", "tagger": {"name": profile["login"], "email": str(profile["id"]) + "+" + profile["login"] + "@users.noreply.github.com", "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}}, "POST")
    github.api("repos/" + APPS_REPO + "/git/refs", {"ref": "refs/tags/" + plan["tag"], "sha": tag["sha"]}, "POST")
    body = plan["notes"] + "\n\nMinimum verified Portal release: `" + plan["minimum_portal_release"] + "`.\n\nBackend image: `" + IMAGE + "@" + metadata["image"]["digest"] + "`.\n\nVerify all downloaded files with `sha256sum -c SHA256SUMS`. Compatibility and operator evidence are recorded in `release.json`. No rolling image tag or marketplace default is changed.\n"
    release = github.api("repos/" + APPS_REPO + "/releases", {"tag_name": plan["tag"], "name": "Status " + plan["version"], "body": body, "draft": True, "prerelease": "-" in plan["version"], "make_latest": "false"}, "POST")
    if type(release.get("id")) is not int or release.get("draft") is not True:
        raise ValueError("release reservation did not produce a private draft")
    for file in sorted(artifacts.iterdir()):
        github.upload(release["id"], file)
    github.api("repos/" + APPS_REPO + "/releases/" + str(release["id"]), {"draft": False, "make_latest": "false"}, "PATCH")
    verify_public(plan, artifacts, github)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "verify-source", "verify", "image-context", "image-absent", "finalize", "publish", "verify-public"])
    parser.add_argument("--version")
    parser.add_argument("--confirmation")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    github = GitHub(os.environ.get("GH_TOKEN", ""))
    if args.command == "prepare":
        if not args.version or not args.confirmation or not args.output:
            parser.error("prepare requires version, confirmation and output")
        prepare(ROOT, args.version, args.confirmation, args.output, github)
        return
    if not args.plan:
        parser.error("plan is required")
    plan = json.loads(args.plan.read_text())
    if args.command == "verify-source":
        verified_source(plan, github)
        github.absent(plan["tag"])
        return
    if args.command == "image-absent":
        image_absent(plan, github.token, os.environ.get("GITHUB_ACTOR", ""))
        return
    if not args.artifacts:
        parser.error("artifacts are required")
    if args.command == "verify":
        verified_artifacts(plan, args.artifacts)
    elif args.command == "image-context":
        if not args.output:
            parser.error("image-context requires output")
        image_context(plan, args.artifacts, args.output)
    elif args.command == "finalize":
        finalize(plan, args.artifacts, os.environ.get("IMAGE_DIGEST", ""))
    elif args.command == "publish":
        publish(plan, args.artifacts, github, os.environ.get("GITHUB_ACTOR", ""))
    elif args.command == "verify-public":
        verify_public(plan, args.artifacts, github)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, json.JSONDecodeError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise SystemExit(str(error)) from None
