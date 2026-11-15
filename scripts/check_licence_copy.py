#!/usr/bin/env python3
"""Fail when this repository's licence evaluator or policy drifts from the Portal's.

scripts/licence_scan.py is a copy of the file of the same name in KazuhaHub/StockAnalysisPrediction-Report-Portal,
and the allow, deny, election-only, own-licence and reviewed-as sections of scripts/licence-policy.json are a copy of
that repository's policy. Both repositories are public, so this reads the Portal without credentials and compares:

  * the Portal commit pinned in scripts/licence-scan.pin;
  * the live files on the Portal branches integration/app-platform and main, each one only once the file exists there.

The evaluator must match line for line apart from its module docstring, and the shared policy sections must be
equal. Elections and exclusions are Portal-only and are not compared. Once a live branch carries the file, the pin
must also be a commit that branch contains: a pin on a feature-branch commit that a squash merge orphans fails here,
which is the reminder to move it. Until the Portal has merged the licence gate there is no live branch to compare
with, and only the pin is checked.

A copy that quietly differs is a gate that judges differently in the two repositories. To change the evaluator or
the shared policy, change the Portal first, merge it, then in this repository copy the files from that commit,
write the commit's full SHA into scripts/licence-scan.pin, and run this script.

    python3 scripts/check_licence_copy.py
"""
import ast
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL = "KazuhaHub/StockAnalysisPrediction-Report-Portal"
BRANCHES = ("integration/app-platform", "main")
EVALUATOR, POLICY = "scripts/licence_scan.py", "scripts/licence-policy.json"
BUMP_HELP = (
    "To bump the pin: merge the change in the Portal repository, copy scripts/licence_scan.py and the shared sections "
    "of scripts/licence-policy.json from that commit (the module docstring may differ), write the commit's full SHA "
    "to scripts/licence-scan.pin, and run python3 scripts/check_licence_copy.py."
)
SHARED_LISTS = ("allow", "deny", "election_only", "reviewed")


def read_pin(path):
    pin = Path(path).read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", pin):
        raise ValueError(f"{path} must hold one full 40-character commit SHA, not {pin!r}")
    return pin


def without_docstring(source):
    """The source after its module docstring (all of it when there is none), leading blank lines dropped."""
    tree = ast.parse(source)
    lines = source.splitlines()
    first = tree.body[0] if tree.body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        lines = lines[first.end_lineno:]
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


def evaluator_differences(local, upstream):
    a, b = without_docstring(local), without_docstring(upstream)
    if a == b:
        return []
    for n, (x, y) in enumerate(zip(a, b), 1):
        if x != y:
            return [f"scripts/licence_scan.py differs from the Portal's after its docstring, first at line {n}: "
                    f"{x!r} here, {y!r} there"]
    return [f"scripts/licence_scan.py differs from the Portal's after its docstring: {len(a)} lines here, "
            f"{len(b)} there"]


def policy_differences(local, upstream):
    out = []
    for key in SHARED_LISTS:
        if local.get(key) != upstream.get(key):
            out.append(f"scripts/licence-policy.json section {key!r} differs from the Portal's")
    if (local.get("own") or {}).get("licences") != (upstream.get("own") or {}).get("licences"):
        out.append("scripts/licence-policy.json section 'own.licences' differs from the Portal's")
    return out


def _compare(label, local_source, local_policy, upstream_source, upstream_policy_text):
    drift = [d.replace("the Portal's", f"the Portal's at {label}") for d in evaluator_differences(local_source, upstream_source)]
    drift += [d.replace("the Portal's", f"the Portal's at {label}")
              for d in policy_differences(local_policy, json.loads(upstream_policy_text))]
    return drift


def check(sha, local_source, local_policy, fetch, reachable):
    """(drift, notes). `fetch(ref, path)` returns a Portal file at a commit or branch, or None when it is not there;
    `reachable(branch, sha)` says whether the branch contains the commit."""
    drift, notes = [], []
    pinned = fetch(sha, EVALUATOR), fetch(sha, POLICY)
    if None in pinned:
        drift.append(f"the pinned commit {sha} has no {EVALUATOR} or {POLICY} in the Portal repository")
    else:
        drift += _compare(sha[:7], local_source, local_policy, *pinned)
    live = []
    for branch in BRANCHES:
        evaluator = fetch(branch, EVALUATOR)
        if evaluator is None:
            continue  # the Portal has not merged the gate into this branch yet
        live.append(branch)
        policy = fetch(branch, POLICY)
        if policy is None:
            drift.append(f"{POLICY} is missing on the Portal branch {branch}, which has {EVALUATOR}")
        else:
            drift += _compare(branch, local_source, local_policy, evaluator, policy)
    if not live:
        notes.append("the Portal has not merged the licence gate into integration/app-platform or main yet: "
                     "only the pinned commit was compared")
    elif not any(reachable(branch, sha) for branch in live):
        drift.append(f"the pinned commit {sha} is not reachable from {' or '.join(live)}: move the pin to a commit "
                     f"those branches contain")
    return drift, notes


def _get(url, headers=()):
    """(status, body). A Python without a CA bundle (a stock macOS framework build) cannot verify GitHub; curl can."""
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        return err.code, ""
    except urllib.error.URLError:
        args = ["curl", "--silent", "--show-error", "--location", "--write-out", "\n%{http_code}", url]
        for name, value in headers:
            args[1:1] = ["--header", f"{name}: {value}"]
        out = subprocess.run(args, check=True, capture_output=True, text=True, timeout=60).stdout
        body, _, status = out.rpartition("\n")
        return int(status), body


def fetch_from_github(ref, path):
    """The file at a commit or a branch of the Portal, or None when it does not exist there."""
    ref = ref if re.fullmatch(r"[0-9a-f]{40}", ref) else f"refs/heads/{ref}"
    status, body = _get(f"https://raw.githubusercontent.com/{PORTAL}/{ref}/{path}")
    if status == 404:
        return None
    if status != 200:
        raise RuntimeError(f"GitHub answered {status} for {path} at {ref}")
    return body


def reachable_on_github(branch, sha):
    """Whether the Portal branch contains the commit (the branch is identical to it or ahead of it)."""
    status, body = _get(f"https://api.github.com/repos/{PORTAL}/compare/{sha}...{branch}",
                        headers=(("Accept", "application/vnd.github+json"),))
    if status == 404:
        return False
    if status != 200:
        raise RuntimeError(f"GitHub answered {status} comparing {sha} with {branch}")
    return json.loads(body).get("status") in ("ahead", "identical")


def main():
    sha = read_pin(ROOT / "scripts" / "licence-scan.pin")
    local_source = (ROOT / "scripts" / "licence_scan.py").read_text(encoding="utf-8")
    local_policy = json.loads((ROOT / "scripts" / "licence-policy.json").read_text(encoding="utf-8"))
    drift, notes = check(sha, local_source, local_policy, fetch_from_github, reachable_on_github)
    for note in notes:
        print(f"licence copy check: note: {note}")
    if drift:
        print("licence copy check: this repository has drifted from the Portal:")
        for line in drift:
            print(f"  {line}")
        print(BUMP_HELP)
        return 1
    print(f"licence copy check: evaluator and shared policy match the Portal (pin {sha})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
