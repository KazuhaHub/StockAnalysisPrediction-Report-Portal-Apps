"""Decide which jobs of check.yml a pull request needs, from the files it changes.

Reads changed paths (one per line) on stdin and prints `area=true|false` lines for $GITHUB_OUTPUT.
`--all` prints every area as true: pushes to main and manual runs always run everything, because the
release gates require every job of a main push run to have succeeded.

A path that no rule below knows about turns every area on. A new app, package or top-level file
therefore runs the whole suite until a rule is written for it; nothing is skipped by omission.
"""
import sys

AREAS = (
    "platform",     # frontend-standard: contract, plugin standard, typecheck of every workspace, SDK and demo tests
    "templates",    # the backend template's Go service and root-v2 tests inside frontend-standard
    "protocol",     # packages/extensionprotocol
    "proxy",        # packages/proxy
    "sd",           # scheduled-digest
    "mm_frontend",  # market-monitor-frontend
    "mm_service",   # market-monitor: vet and unit tests
    "mm_image",     # market-monitor: backend image build and its checks
    "mm_pipeline",  # market-monitor-pipeline
    "status",       # status and status-container
    "status_browser",  # status-browser (a pull request runs it only when its own harness changed)
)

MM = "apps/kazuha-hub-market-monitor/"
EVERYWHERE = frozenset(AREAS)
# Frontends reach every job that builds a frontend; the shared scripts reach every consumer of them.
SCRIPT_CONSUMERS = frozenset({"platform", "templates", "sd", "mm_frontend", "status"})
IMAGE_INPUTS = ("service/Dockerfile", "service/go.mod", "service/go.sum", "service/testdata/", "service/history", "service/rlimit", "pipeline/requirements")


def areas_of(path):
    """The areas a changed path affects, or EVERYWHERE for a path nothing describes."""
    name = path.rsplit("/", 1)[-1]
    if path in (".github/workflows/check.yml", "scripts/ci_changes.py", "package.json", "package-lock.json"):
        return EVERYWHERE
    if path.startswith(".github/workflows/") or path.startswith("docs/") or path.startswith("scripts/tests/"):
        return frozenset()
    if path in ("index.json", ".gitignore", ".gitattributes", ".prettierignore", "LICENSE") or name.endswith(".md") or name.startswith("LICENSE"):
        return frozenset()
    if path == ".dockerignore":
        return frozenset({"mm_image", "sd", "status"})
    if path.startswith("scripts/"):
        return SCRIPT_CONSUMERS
    if path.startswith("packages/app-sdk/"):
        return frozenset({"platform", "sd", "mm_frontend", "status"})
    if path.startswith("packages/extensionprotocol/"):
        return frozenset({"protocol", "templates", "platform", "sd", "mm_service"})
    if path.startswith("packages/proxy/"):
        return frozenset({"proxy", "templates", "platform", "mm_service"})
    if path.startswith("templates/"):
        return frozenset({"platform", "templates"})
    if path.startswith(("apps/demo-symbols/", "apps/notes-sample/")):
        return frozenset({"platform"})
    if path.startswith("apps/scheduled-digest/"):
        return frozenset({"platform", "sd"}) if path.startswith(("apps/scheduled-digest/frontend/", "apps/scheduled-digest/app.")) else frozenset({"sd"})
    if path.startswith("apps/status/"):
        if path.startswith("apps/status/tests/"):
            return frozenset({"status_browser"})
        return frozenset({"platform", "status"}) if path.startswith(("apps/status/frontend/", "apps/status/app.")) else frozenset({"status"})
    if path.startswith(MM):
        rest = path[len(MM):]
        found = set()
        if rest.startswith("frontend/"):
            found |= {"platform", "mm_frontend"}
        elif rest == "app.v2.json":
            found |= {"platform", "mm_frontend", "mm_service"}
        elif rest.startswith("service/"):
            found.add("mm_service")
        elif rest.startswith("pipeline/"):
            found.add("mm_pipeline")
        elif not rest.startswith("docs/"):
            return EVERYWHERE
        if rest.startswith(IMAGE_INPUTS):
            found.add("mm_image")
        return frozenset(found)
    return EVERYWHERE


def classify(paths):
    """{area: bool}. paths=None means a run that always does everything."""
    if paths is None:
        return {area: True for area in AREAS}
    hit = set()
    for path in paths:
        hit |= areas_of(path)
    return {area: area in hit for area in AREAS}


def main(argv):
    every = "--all" in argv
    paths = None if every else [line.strip() for line in sys.stdin if line.strip()]
    for area, value in classify(paths).items():
        print(area + "=" + ("true" if value else "false"))


if __name__ == "__main__":
    main(sys.argv[1:])
