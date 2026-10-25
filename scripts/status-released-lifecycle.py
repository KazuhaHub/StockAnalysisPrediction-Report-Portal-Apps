"""Drill immutable app upgrades and rollback with disposable local API fixtures.

Inputs must first be downloaded and verified from their official releases. This
tool never opens a browser, contacts providers or accepts a production URL.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import http.cookiejar
import ipaddress
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import sqlite3
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def free_port():
    with socket.socket() as listener:
        listener.bind(("0.0.0.0", 0))
        return listener.getsockname()[1]


def release(root, destination):
    metadata = json.loads((root / "release.json").read_text())
    require(metadata["app_id"] == "status", "Unexpected release identity")
    target = {"Darwin": "darwin", "Linux": "linux"}[platform.system()]
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}[platform.machine()]
    archive_name = f"status-v{metadata['version']}-{target}-{arch}.tar.gz"
    for name in (archive_name, "status.zip"):
        require(hashlib.sha256((root / name).read_bytes()).hexdigest() == metadata["artifacts"][name],
                f"Release artifact checksum mismatch: {name}")
    with zipfile.ZipFile(root / "status.zip") as bundle:
        manifest = json.loads(bundle.read("app.json"))
    require(manifest["id"] == "status" and manifest["version"] == metadata["version"],
            "ZIP and release identities differ")
    require(set(manifest["scopes"]) == {"extension.read", "extension.manage"},
            "Unexpected permission change")
    destination.mkdir(mode=0o700)
    with tarfile.open(root / archive_name) as archive:
        members = archive.getmembers()
        require(len(members) == 1 and members[0].name == "status" and members[0].isfile(),
                "Unexpected service archive contents")
        archive.extractall(destination, filter="data")
    return metadata["version"], destination / "status", root / "status.zip"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portal", type=Path, required=True)
    parser.add_argument("--old-artifacts", type=Path, required=True)
    parser.add_argument("--new-artifacts", type=Path, required=True)
    parser.add_argument("--private-address", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    address = ipaddress.ip_address(args.private_address)
    require(address.version == 4 and address.is_private and not address.is_loopback,
            "A local private IPv4 interface is required; loopback bypasses are forbidden")
    with socket.socket() as local_interface:
        local_interface.bind((str(address), 0))
    require(not args.receipt.exists(), "Refusing to overwrite an existing receipt")
    args.portal = args.portal.resolve(strict=True)
    old_root, new_root = args.old_artifacts.resolve(), args.new_artifacts.resolve()
    environment = {k: v for k, v in os.environ.items() if not k.startswith("RP_")}
    processes = []
    with tempfile.TemporaryDirectory(prefix="status-release-lifecycle-") as folder:
        root = Path(folder)
        root.chmod(0o700)
        old_version, old_binary, old_zip = release(old_root, root / "old")
        new_version, new_binary, new_zip = release(new_root, root / "new")
        require(old_version != new_version, "Two distinct release versions are required")
        portal_port, service_port = free_port(), free_port()
        base = f"http://127.0.0.1:{portal_port}"
        service_base = f"http://127.0.0.1:{service_port}"
        config = root / "portal.yaml"
        config.write_text(f'listen: "127.0.0.1:{portal_port}"\nsecret_key: "{secrets.token_hex(32)}"\n'
                          f'db_driver: "sqlite"\ndb_path: "{root / "portal.db"}"\n')
        config.chmod(0o600)
        environment["RP_CONFIG"] = str(config)
        password = "Disposable-" + secrets.token_hex(16)
        key = base64.b64encode(secrets.token_bytes(32)).decode()
        storage_key = root / "storage.key"
        storage_key.write_text(base64.b64encode(secrets.token_bytes(32)).decode())
        storage_key.chmod(0o600)
        pairing = root / "pairing.json"
        database = root / "status.db"
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

        def command(*command_args):
            return subprocess.run([str(x) for x in command_args], cwd=root, env=environment,
                                  check=True, capture_output=True, text=True, timeout=30)

        def start(binary, *command_args):
            process = subprocess.Popen([str(binary), *map(str, command_args)], cwd=root,
                                       env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(process)
            return process

        def stop(process):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    raise RuntimeError("Fixture required forced termination")

        def api(method, path, payload=None, token=None, raw=None, content_type=None, expected=200):
            data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
            headers = {"Content-Type": content_type or "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + token
            request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
            try:
                response = opener.open(request, timeout=15)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                require(response.status == expected, f"Unexpected status for {method} {path}: {response.status}")
                body = response.read()
                return json.loads(body) if expected == 200 and body else None

        def ready(url, process):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                require(process.poll() is None, "Fixture process exited before readiness")
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:
                        if response.status == 200:
                            return
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(0.1)
            raise RuntimeError("Fixture readiness timed out")

        def install(bundle):
            boundary = secrets.token_hex(16)
            raw = (f'--{boundary}\r\nContent-Disposition: form-data; name="bundle"; filename="status.zip"'
                   '\r\nContent-Type: application/zip\r\n\r\n').encode()
            raw += bundle.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
            api("POST", "/api/admin/apps/install", raw=raw,
                content_type="multipart/form-data; boundary=" + boundary)
            with zipfile.ZipFile(bundle) as archive:
                manifest = json.loads(archive.read("app.json"))
                installed = [x for x in api("GET", "/api/apps")["apps"] if x["id"] == "status"]
                require(len(installed) == 1 and installed[0]["version"] == manifest["version"],
                        "Installed registry version differs from the reviewed release")
                for name in archive.namelist():
                    if name == "app.json" or name.endswith("/"):
                        continue
                    with opener.open(base + "/app-assets/status/" + name, timeout=15) as response:
                        require(response.read() == archive.read(name), "Installed asset differs from release: " + name)

        def proxy(method, path, body=None):
            token = api("POST", "/api/apps/status/token")["token"]
            return api("POST", "/api/v1/extensions/status/request", token=token,
                       payload={"method": method, "path": path, **({"body": body} if body is not None else {})})

        endpoint = "/api/admin/apps/status/backend"

        def pair(binary, revision=0):
            registration = api("PUT", endpoint, {
                "revision": revision, "label": "Isolated release fixture", "enabled": False,
                "base_url": f"http://{address}:{service_port}", "audience": "status",
                "key_id": "fixture-key", "signing_key": key,
                "policy": {"version": 1, "plain_http": True, "networks": [str(address) + "/32"],
                           "ports": [service_port], "routes": [{"method": m, "prefix": "/v1/"}
                                                                  for m in ["GET", "PUT", "POST", "DELETE"]]}})
            pairing.write_text(json.dumps({k: registration[k] for k in
                                           ["issuer", "audience", "app_id", "instance_id"]} |
                                          {"key_id": "fixture-key", "signing_key": key}))
            pairing.chmod(0o600)
            process = start(binary, "serve", "-listen", f"0.0.0.0:{service_port}",
                            "-database", database, "-storage-key-file", storage_key, "-pairing-file", pairing)
            ready(service_base + "/readyz", process)
            api("PUT", endpoint, {k: registration[k] for k in
                                  ["revision", "label", "base_url", "audience", "policy"]} |
                                 {"enabled": True, "key_id": "", "signing_key": ""})
            return process, registration["instance_id"]

        def fingerprint():
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
                require(connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Store integrity failed")
                return {table: hashlib.sha256(repr(connection.execute(
                    "SELECT * FROM " + table + " ORDER BY 1").fetchall()).encode()).hexdigest()
                        for table in ["components", "monitors", "credentials", "component_grants"]}

        try:
            command(args.portal, "adduser", "admin", password, "admin")
            portal = start(args.portal)
            ready(base + "/healthz", portal)
            api("POST", "/api/login", {"username": "admin", "password": password})
            portal_version = api("GET", "/api/version")["version"]
            install(old_zip)
            service, first_instance = pair(old_binary)
            settings = {"public_enabled": False, "probes_paused": True, "outbox_paused": True,
                        "portal_url": "", "portal_networks": []}
            proxy("PUT", "/v1/manage/settings", settings)
            credential = proxy("PUT", "/v1/manage/credentials", {
                "kind": "postgres", "label": "Disposable encrypted fixture", "revision": 0,
                "secret": {"username": "fixture", "password": secrets.token_hex(16)}})["item"]
            component = proxy("PUT", "/v1/manage/components", {
                "label": "Release continuity fixture", "revision": 0, "enabled": True,
                "public_enabled": False, "public_label": "", "grants": [], "monitors": [{
                    "label": "Disabled fixture readiness", "kind": "http", "enabled": False,
                    "interval_seconds": 60, "timeout_seconds": 5,
                    "config": {"url": "https://fixture.invalid/health"}}]})["item"]
            require(len(component["monitors"]) == 1, "Fixture monitor was not saved")
            require(credential["id"] and component["id"], "Fixture identities are missing")
            baseline = fingerprint()
            instances = [first_instance]
            for version, binary, bundle in [(new_version, new_binary, new_zip),
                                             (old_version, old_binary, old_zip)]:
                old_token = api("POST", "/api/apps/status/token")["token"]
                stop(service)
                command(old_binary if version == new_version else new_binary, "backup",
                        "-database", database, "-storage-key-file", storage_key,
                        "-file", root / ("before-" + version + ".db"))
                install(bundle)
                cleared = api("GET", endpoint)
                require(not cleared["enabled"] and not cleared["has_key"], "Replacement retained old authority")
                require(cleared["instance_id"] not in instances, "Replacement reused installation identity")
                api("POST", "/api/v1/extensions/status/request", {"method": "GET", "path": "/v1/components"},
                    token=old_token, expected=403)
                service, instance = pair(binary, cleared["revision"])
                instances.append(instance)
                require(fingerprint() == baseline, "Upgrade or rollback changed configuration or sealed credentials")
                require(any(x["id"] == component["id"] for x in proxy("GET", "/v1/components")["items"]),
                        "Preserved component is inaccessible after re-pairing")
                actual = proxy("GET", "/v1/manage/operations")["settings"]
                require(all(actual[k] == v for k, v in settings.items()), "Upgrade or rollback changed safety settings")
                print(f"Verified installed {version}, new pairing, stale-token denial and retained store", flush=True)
            api("DELETE", "/api/admin/apps/status")
            api("GET", endpoint, expected=404)
            api("GET", "/app-assets/status/index.html", expected=404)
            for path in ["/healthz", "/api/me", "/api/home", "/api/admin/batch/queue"]:
                api("GET", path)
            ready(service_base + "/readyz", service)
            receipt = {"time": datetime.now(timezone.utc).isoformat(),
                       "portal_version": portal_version, "upgrade": new_version, "rollback": old_version,
                       "official_artifact_checksums": "verified", "distinct_installations": len(set(instances)),
                       "stale_tokens": "denied after each replacement", "sealed_credentials": "unchanged",
                       "component_and_monitor_configuration": "unchanged", "installed_assets": "match each release ZIP",
                       "work": "paused", "public": "disabled",
                       "uninstall": "revokes host registration and assets; independent service remains ready",
                       "scope": "disposable local API fixture; no browser, provider access or production mutation"}
        finally:
            cleanup_errors = []
            for process in reversed(processes):
                try:
                    stop(process)
                except Exception as error:
                    cleanup_errors.append(error)
            if cleanup_errors:
                raise RuntimeError("Fixture cleanup failed; no success receipt will be written") from cleanup_errors[0]
    with args.receipt.open("x", encoding="utf-8") as output:
        os.chmod(args.receipt, 0o600)
        json.dump(receipt, output, indent=2)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
