"""Run a v2 app's backend image on this machine the way Portal's runner does, and call it.

DEVELOPMENT ONLY. This is not Portal and holds no Portal authority. It starts the
image with the same container constraints the runner uses (user 65532, read-only
root, no network, a 16 MiB noexec /tmp, only /data and the socket directory
writable, capabilities dropped), writes a registration with an invented dev key,
and lets you call the backend's Unix socket with a dev-signed viewer assertion.
A backend started this way trusts that dev key only, so nothing here can act on a
real installation. It is close to the runner's policy, not identical: Docker's default
seccomp profile applies (the runner has its own), there is no CPU pinning, no XFS quota
on /data and no broker unless you pass --broker-socket. See docs/backend-service-v2.md.

  run-backend-local.py my-app --build          build apps/my-app/service/Dockerfile, then start
  run-backend-local.py my-app                  start the image my-app:dev (detached)
  run-backend-local.py my-app --call GET /v1/hello [--role admin] [--ou ou-a]
  run-backend-local.py my-app --task '{"job":"example"}'
  run-backend-local.py my-app --logs
  run-backend-local.py my-app --stop
  run-backend-local.py my-app --clean          stop and empty .development/local

Needs Docker, and Go on the host to build the dev client (a static binary that is
mounted into a throwaway container, because the socket belongs to uid 65532).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The runner's container policy. Source of truth: the Portal repository,
# internal/apprunner/driver/container.go, planCandidateContainer. Keep in step.
USER = "65532:65532"
HTTP_TARGET = "/run/portal-app/http"
BROKER_TARGET = "/run/portal-app/broker"
SOCKET = HTTP_TARGET + "/app.sock"
BROKER_SOCKET = BROKER_TARGET + "/broker.sock"
REGISTRATION = BROKER_TARGET + "/registration.json"
CPU_SHARES = "256"
PROXY_LISTEN = "127.0.0.1:3128"
PROXY_URL = "http://" + PROXY_LISTEN
NO_PROXY = "127.0.0.1,localhost"
CLIENT_TARGET = "/portal-dev-client"
ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,63}")


class LocalRunError(Exception):
    pass


def app_id_checked(app_id):
    if not isinstance(app_id, str) or not ID_PATTERN.fullmatch(app_id):
        raise LocalRunError("Use a lowercase application identifier")
    return app_id


def container_name(app_id, directory):
    """One name per checkout and app, so two developers (or two checkouts) sharing a Docker daemon
    do not stop each other's container."""
    return f"portal-local-{app_id}-{hashlib.sha256(str(directory).encode()).hexdigest()[:6]}"


def local_dir(app_id, root=ROOT):
    return root / "apps" / app_id / ".development" / "local"


def read_backend(app_id, root=ROOT):
    """The descriptor facts the runner turns into the container's limits and environment."""
    path = root / "apps" / app_id / "app.v2.json"
    if not path.is_file() or path.is_symlink():
        raise LocalRunError(f"apps/{app_id}/app.v2.json not found")
    declaration = json.loads(path.read_text())
    backend = declaration.get("backend")
    if not isinstance(backend, dict):
        raise LocalRunError(f"apps/{app_id} declares no backend; generate it with --template v2-backend")
    resources = backend["resources"]
    optional = (declaration.get("capabilities") or {}).get("optional") or []
    return {
        "platform": backend["platforms"][0],
        "memory_mib": resources["memory_mib"],
        "cpu_millis": resources["cpu_millis"],
        "pids": resources["pids"],
        # Doc 184: the proxy environment is set for a release that declares network.proxy
        # (optional only), whether or not an administrator has granted it.
        "proxy": "network.proxy" in optional,
    }


def environment(proxy):
    env = [
        f"PORTAL_APP_HTTP_SOCKET={SOCKET}",
        f"PORTAL_APP_BROKER_SOCKET={BROKER_SOCKET}",
    ]
    if proxy:
        env += [
            f"HTTPS_PROXY={PROXY_URL}", f"https_proxy={PROXY_URL}",
            f"NO_PROXY={NO_PROXY}", f"no_proxy={NO_PROXY}",
            f"PORTAL_APP_PROXY_LISTEN={PROXY_LISTEN}",
        ]
    return env


def bind(source, target, readonly=False):
    if "," in str(source) or "\n" in str(source):
        raise LocalRunError("A mount source path may not contain a comma or newline")
    value = f"type=bind,source={source},target={target},bind-propagation=rprivate"
    return value + ",readonly" if readonly else value


def sandbox_args(user=USER):
    """What every container here shares: no network, nothing writable, no capabilities."""
    return [
        "--user", user, "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=16777216,mode=1777",
    ]


def run_args(app_id, image, backend, directory, *, broker_socket=None, data_readonly=False, detach=True):
    """The `docker run` argument list. Pure: no Docker, no filesystem."""
    memory = f"{backend['memory_mib']}m"
    args = ["docker", "run", "--name", container_name(app_id, directory), "--label", "portal-local-dev=" + app_id,
            "--platform", backend["platform"]]
    args += ["--detach"] if detach else ["--rm"]
    args += sandbox_args()
    args += [
        "--hostname", "app", "--workdir", "/",
        "--memory", memory, "--memory-swap", memory,
        "--cpus", f"{backend['cpu_millis'] / 1000:g}",
        "--cpu-shares", CPU_SHARES, "--pids-limit", str(backend["pids"]),
        "--shm-size", "16m", "--cgroupns", "private", "--ipc", "private",
        "--init", "--restart", "no", "--no-healthcheck",
        "--stop-signal", "SIGTERM", "--stop-timeout", "10",
        "--log-driver", "json-file", "--log-opt", "max-size=5m", "--log-opt", "max-file=2",
        "--ulimit", "nofile=1024:1024",
    ]
    for item in environment(backend["proxy"]):
        args += ["--env", item]
    args += ["--mount", bind(directory / "data", "/data", data_readonly)]
    args += ["--mount", bind(directory / "http", HTTP_TARGET)]
    args += ["--mount", bind(directory / "broker", BROKER_TARGET, readonly=True)]
    if broker_socket is not None:
        # Portal's runner creates broker.sock inside the broker directory. Locally you supply one.
        args += ["--mount", bind(broker_socket, BROKER_SOCKET)]
    return args + [image]


def helper_args(image, backend, directory, client, tool_args, *, root_user=False):
    """A throwaway container from the same image that runs the dev client.

    The backend's socket is owned by uid 65532 with mode 0600, so only that user can
    connect. The client is mounted over the entrypoint; the image's own files are unused.
    """
    args = ["docker", "run", "--rm", "--platform", backend["platform"]]
    args += sandbox_args("0:0" if root_user else USER)
    args += ["--mount", bind(directory / "http", HTTP_TARGET),
             "--mount", bind(directory / "broker", BROKER_TARGET, readonly=True),
             "--mount", bind(client, CLIENT_TARGET, readonly=True)]
    if root_user:
        # Purge deletes files the container user owns, in sticky directories the host user owns, so
        # root needs DAC_OVERRIDE and FOWNER; the sandbox is otherwise unchanged and still has no network.
        args += ["--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER", "--mount", bind(directory, "/work")]
    return args + ["--entrypoint", CLIENT_TARGET, image] + tool_args


def call_tool_args(method, path, *, role="user", subject=None, ous=(), body_file=None):
    args = ["call", "--socket", SOCKET, "--registration", REGISTRATION, "--role", role]
    if subject:
        args += ["--subject", subject]
    for ou in ous:
        args += ["--ou", ou]
    if body_file:
        args += ["--body-file", body_file]
    return args + [method, path]


def task_tool_args(payload, occurrence=None):
    args = ["task", "--socket", SOCKET, "--registration", REGISTRATION]
    if occurrence:
        args += ["--occurrence", occurrence]
    return args + [payload]


def sh(args, **options):
    return subprocess.run(args, check=True, **options)


def docker_image_exists(image):
    return subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0


def build_image(app_id, image, backend, root=ROOT):
    dockerfile = root / "apps" / app_id / "service" / "Dockerfile"
    if not dockerfile.is_file():
        raise LocalRunError(f"{dockerfile.relative_to(root)} not found")
    sh(["docker", "build", "--platform", backend["platform"], "-f", str(dockerfile), "-t", image, "."], cwd=root)


def build_client(directory, backend=None, root=ROOT):
    """Compile the dev client; the host needs Go. With a backend it is built for the
    image's platform (it runs in a container); without, for the host (it writes the
    registration here)."""
    if shutil.which("go") is None:
        raise LocalRunError("Go is required on the host to build the dev client")
    env = {**os.environ, "CGO_ENABLED": "0", "GOWORK": "off"}
    name = "portal-dev-client-host"
    if backend is not None:
        env["GOOS"], env["GOARCH"] = backend["platform"].split("/")
        name = "portal-dev-client"
    client = directory / "bin" / name
    client.parent.mkdir(parents=True, exist_ok=True)
    sh(["go", "build", "-trimpath", "-o", str(client), "./cmd/portal-dev-client"],
       cwd=root / "packages" / "extensionprotocol", env=env)
    return client


def prepare(directory, broker_socket=None):
    """Create the mount sources. They are scratch space for one developer, so the
    container user (65532) is given write access by mode rather than by owner; the
    sticky bit keeps other host users from replacing what it creates."""
    for name in ("data", "http", "broker"):
        path = directory / name
        path.mkdir(parents=True, exist_ok=True)
    for name in ("data", "http"):
        os.chmod(directory / name, 0o1777)
    os.chmod(directory / "broker", 0o755)
    # The broker directory is mounted read-only, and runc cannot create a mount point inside a
    # read-only mount, so the file the broker socket is mounted over must already exist.
    placeholder = directory / "broker" / "broker.sock"
    if broker_socket is not None:
        placeholder.touch()
    elif placeholder.exists() and not placeholder.is_socket():
        placeholder.unlink()
    # A socket left by a previous run makes the next bind fail; the directory is writable, so unlink it.
    (directory / "http" / "app.sock").unlink(missing_ok=True)


def run_helper(image, backend, directory, client, tool_args, **options):
    return subprocess.run(helper_args(image, backend, directory, client, tool_args, **options))


def remove_container(app_id, directory):
    """Remove this checkout's container, if any. Name and label must both match."""
    name = container_name(app_id, directory)
    found = subprocess.run(["docker", "ps", "--all", "--quiet", "--filter", f"name=^{name}$",
                            "--filter", f"label=portal-local-dev={app_id}"], capture_output=True, text=True)
    if found.stdout.strip():
        subprocess.run(["docker", "rm", "--force", name], capture_output=True)


def start(app_id, image, backend, directory, client, args):
    broker = Path(args.broker_socket).resolve() if args.broker_socket else None
    if broker is not None and not broker.is_socket():
        raise LocalRunError(f"{broker} is not a Unix socket")
    prepare(directory, broker)
    remove_container(app_id, directory)
    # The registration is written on the host with a host-native build of the client; it keeps an
    # existing key, so a restart does not change what earlier calls were signed with.
    host_client = build_client(directory)
    sh([str(host_client), "register", "--dir", str(directory / "broker"), "--app-id", app_id])
    command = run_args(app_id, image, backend, directory, broker_socket=broker,
                       data_readonly=args.data_readonly, detach=not args.foreground)
    if args.foreground:
        return subprocess.run(command).returncode
    sh(command, stdout=subprocess.DEVNULL)
    for _ in range(40):
        if run_helper(image, backend, directory, client, ["ready", "--socket", SOCKET]).returncode == 0:
            break
        time.sleep(0.5)
    else:
        sh(["docker", "logs", container_name(app_id, directory)])
        raise LocalRunError("the backend did not become ready; its log is above")
    print(f"\n{container_name(app_id, directory)} is running under the runner's container constraints "
          "(Docker's default seccomp profile, no CPU pinning, no quota).\n"
          f"  call:  python3 scripts/run-backend-local.py {app_id} --call GET /v1/hello\n"
          f"  logs:  python3 scripts/run-backend-local.py {app_id} --logs\n"
          f"  stop:  python3 scripts/run-backend-local.py {app_id} --stop")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("app_id")
    parser.add_argument("--image", help="image to run (default: <id>:dev)")
    parser.add_argument("--build", action="store_true", help="docker build apps/<id>/service/Dockerfile first")
    parser.add_argument("--foreground", action="store_true", help="run attached instead of detached")
    parser.add_argument("--data-readonly", action="store_true", help="mount /data read-only (a candidate start is read-only)")
    parser.add_argument("--broker-socket", help="host path of a Unix socket to mount as the broker socket")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--call", nargs=2, metavar=("METHOD", "PATH"), help="send one dev-signed viewer request")
    action.add_argument("--task", metavar="JSON", help="send one dev background task with this payload")
    action.add_argument("--logs", action="store_true", help="follow the container's log")
    action.add_argument("--stop", action="store_true")
    action.add_argument("--clean", action="store_true", help="stop and delete the local data, socket and registration")
    parser.add_argument("--role", default="user")
    parser.add_argument("--subject")
    parser.add_argument("--ou", action="append", default=[])
    parser.add_argument("--body-file")
    parser.add_argument("--occurrence")
    args = parser.parse_args(argv)
    app_id = app_id_checked(args.app_id)
    image = args.image or f"{app_id}:dev"
    directory = local_dir(app_id)
    try:
        if args.logs:
            return subprocess.run(["docker", "logs", "--follow", container_name(app_id, directory)]).returncode
        if args.stop or args.clean:
            remove_container(app_id, directory)
            if args.clean and directory.exists():
                # The container user owns what it wrote; empty the directory as root in a throwaway container.
                if docker_image_exists(image):
                    prepare(directory)  # the helper mounts these; a half-finished earlier clean may have removed them
                    backend = read_backend(app_id)
                    client = build_client(directory, backend)
                    run_helper(image, backend, directory, client, ["purge", "--dir", "/work"], root_user=True)
                shutil.rmtree(directory, ignore_errors=True)
                if directory.exists():
                    raise LocalRunError(f"{directory} could not be emptied (files owned by the container user remain; "
                                        "build the image and run --clean again)")
            return 0
        backend = read_backend(app_id)
        if args.build:
            build_image(app_id, image, backend)
        elif not docker_image_exists(image):
            raise LocalRunError(f"image {image} not found; build it with --build or pass --image")
        client = build_client(directory, backend)
        if args.call or args.task:
            if args.call:
                body_file = None
                if args.body_file:
                    # The helper container cannot see the host: stage the body in the socket directory.
                    staged = directory / "http" / "request-body"
                    shutil.copyfile(args.body_file, staged)
                    os.chmod(staged, 0o644)
                    body_file = HTTP_TARGET + "/request-body"
                tool = call_tool_args(args.call[0].upper(), args.call[1], role=args.role, subject=args.subject,
                                      ous=args.ou, body_file=body_file)
            else:
                tool = task_tool_args(args.task, args.occurrence)
            return run_helper(image, backend, directory, client, tool).returncode
        return start(app_id, image, backend, directory, client, args)
    except (LocalRunError, subprocess.CalledProcessError, OSError, KeyError, json.JSONDecodeError) as error:
        print("run-backend-local: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
