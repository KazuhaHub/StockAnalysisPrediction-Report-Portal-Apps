"""Exercise the non-root image with isolated random secrets and a temporary volume."""
import base64
import json
import os
import secrets
import sqlite3
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
    network = name + "-network"
    gateway = name + "-gateway"
    user = f"{os.getuid()}:{os.getgid()}"
    shared = ["--user", user, "-v", f"{root}:/data", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true"]
    try:
        run("docker", "network", "create", network)
        run("docker", "run", "-d", "--name", name, "--network", network, "--network-alias", "status-service", *shared, "-p", "127.0.0.1:18791:8791", "status-development", "serve", "-listen", ":8791", "-database", "/data/status.db", "-storage-key-file", "/data/storage.key", "-pairing-file", "/data/pairing.json")
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
        # Seed only public fixture metadata while the service is offline.
        with sqlite3.connect(root / "status.db") as database:
            database.execute("UPDATE settings SET value='1' WHERE key='public_enabled'")
            database.execute("INSERT INTO components(id,label,public_label,public_enabled,enabled,revision,created_at,updated_at) VALUES(?,?,?,1,1,1,?,?)", ("a" * 32, "Private fixture label", "Public fixture", int(time.time() * 1000), int(time.time() * 1000)))
        config = root / "nginx.conf"
        template = Path("apps/status/deploy/nginx-public.conf").read_text()
        config.write_text("pid /tmp/nginx.pid; error_log /dev/stderr warn; events {} http { access_log off; proxy_temp_path /tmp/proxy; server { listen 8080; " + template + "} }")
        config.chmod(0o644)
        run("docker", "start", name)
        run("docker", "run", "-d", "--name", gateway, "--network", network,
            "--user", user, "--entrypoint", "nginx", "--read-only", "--tmpfs", "/tmp", "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true", "-p", "127.0.0.1:18792:8080",
            "-v", f"{config}:/etc/nginx/nginx.conf:ro", "nginx:stable-alpine",
            "-g", "daemon off;")
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:18792/status/", timeout=2) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.5)
        else:
            raise RuntimeError("Public nginx gateway did not become ready")
        for path in ["/status/app.js", "/status/style.css", "/status/public/v1/status", "/status/public/v1/incidents", "/status/public/v1/history?component_id=" + "a" * 32]:
            request = urllib.request.Request("http://127.0.0.1:18792" + path, headers={"Cookie": "fixture=unused", "Authorization": "Bearer unused"})
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = response.read().decode()
                if response.status != 200 or response.headers.get("Set-Cookie"):
                    raise RuntimeError("Invalid public gateway response")
                if "Private fixture label" in payload:
                    raise RuntimeError("Gateway exposed private component metadata")
        for path in ["/status/v1/manage/operations", "/status/v1/handshake", "/status/ingest/v1/heartbeats/fixture", "/status/readyz", "/status/unknown"]:
            for method in ["GET", "POST"]:
                try:
                    urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:18792" + path, method=method), timeout=5)
                    raise RuntimeError("Gateway exposed a non-public route")
                except urllib.error.HTTPError as error:
                    if error.code != 404:
                        raise
        print("PASS non-root image, offline restore and real nginx public allowlist/history/assets")
    finally:
        subprocess.run(["docker", "rm", "-f", gateway, name], capture_output=True, timeout=40)
        subprocess.run(["docker", "network", "rm", network], capture_output=True, timeout=40)
