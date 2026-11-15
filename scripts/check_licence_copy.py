#!/usr/bin/env python3
"""Fail when this repository's licence evaluator or policy drifts from the Portal's.

scripts/licence_scan.py is a copy of the file of the same name in KazuhaHub/StockAnalysisPrediction-Report-Portal,
and the allow, deny, election-only, own-licence and reviewed-as sections of scripts/licence-policy.json are a copy of
that repository's policy. This compares both against the Portal commit pinned in scripts/licence-scan.pin: the
evaluator must match line for line apart from its module docstring, and the shared policy sections must be equal.
Elections and exclusions are Portal-only and are not compared.

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


def check(sha, local_source, local_policy, fetch):
    drift = evaluator_differences(local_source, fetch(sha, "scripts/licence_scan.py"))
    drift += policy_differences(local_policy, json.loads(fetch(sha, "scripts/licence-policy.json")))
    return drift


def fetch_from_github(sha, path):
    url = f"https://raw.githubusercontent.com/{PORTAL}/{sha}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read().decode("utf-8")
    except urllib.error.URLError:
        # A Python without a CA bundle (a stock macOS framework build) cannot verify GitHub; curl can.
        return subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location", url], check=True,
                              capture_output=True, text=True, timeout=60).stdout


def main():
    sha = read_pin(ROOT / "scripts" / "licence-scan.pin")
    local_source = (ROOT / "scripts" / "licence_scan.py").read_text(encoding="utf-8")
    local_policy = json.loads((ROOT / "scripts" / "licence-policy.json").read_text(encoding="utf-8"))
    drift = check(sha, local_source, local_policy, fetch_from_github)
    if drift:
        print(f"licence copy check: this repository has drifted from the Portal at {sha}:")
        for line in drift:
            print(f"  {line}")
        print(BUMP_HELP)
        return 1
    print(f"licence copy check: evaluator and shared policy match the Portal at {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
