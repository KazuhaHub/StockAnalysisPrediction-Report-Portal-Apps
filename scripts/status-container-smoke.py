"""Exercise the non-root image with isolated random secrets and a temporary volume."""
import base64
import json
import os
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=90)


with tempfile.TemporaryDirectory(prefix="status-image-") as folder:
    root = Path(folder)
    root.chmod(0o700)
    key = root / "storage.key"
    key.write_text(base64.b64encode(secrets.token_bytes(32)).decode())
    key.chmod(0o600)
    pairing = root / "pairing.json"
    pairing.write_text(json.dumps({"issuer": "image-fixture", "audience": "status", "app_id": "status", "instance_id": "fixture-registration", "key_id": "fixture-key", "signing_key": base64.b64encode(secrets.token_bytes(32)).decode()}))
    pairing.chmod(0o600)
    name = "status-smoke-" + secrets.token_hex(6)
    user = f"{os.getuid()}:{os.getgid()}"
    shared = ["--user", user, "-v", f"{root}:/data", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true"]
    try:
        run("docker", "run", "-d", "--name", name, *shared, "-p", "127.0.0.1:18791:8791", "status-development", "serve", "-listen", ":8791", "-database", "/data/status.db", "-storage-key-file", "/data/storage.key", "-pairing-file", "/data/pairing.json")
        ready = False
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:18791/readyz", timeout=2) as response:
                    ready = response.status == 200
                if ready:
                    break
            except (OSError, urllib.error.URLError):
                time.sleep(0.5)
        if not ready:
            raise RuntimeError("Status image did not become ready")
        try:
            urllib.request.urlopen("http://127.0.0.1:18791/", timeout=3)
            raise RuntimeError("Public page was enabled by default")
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
        run("docker", "stop", "--time", "35", name)
        for command in ["backup", "restore"]:
            run("docker", "run", "--rm", *shared, "status-development", command, "-database", "/data/status.db", "-storage-key-file", "/data/storage.key", "-file", "/data/backup.db")
        if not (root / "status.db.pre-restore").is_file():
            raise RuntimeError("Image restore did not preserve rollback snapshot")
        print("PASS non-root image readiness, default-private page and offline backup/restore")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=40)
