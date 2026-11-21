"""Refuse a release from a commit that is not on main or that main's check workflow has not passed.

Checked once, never polled: when the run is still going, the answer is to wait for it and dispatch
again. The same policy as the Portal's release guard (check-ci).
"""
import argparse
import json
import subprocess
import sys


class GateError(RuntimeError):
    pass


def require_on_branch(compare_status, branch, sha):
    """compare_status is GitHub's status of `branch...sha`: identical or behind means sha is on branch."""
    if compare_status not in ("identical", "behind"):
        raise GateError(sha + " is not on " + branch + " (compare status " + str(compare_status) + "); dispatch from " + branch)


def require_check_passed(runs, sha, workflow):
    """runs: workflow runs for exactly this commit, as the Actions API lists them."""
    pushes = [run for run in runs if run.get("head_sha") == sha and run.get("event") == "push"]
    if any(run.get("status") == "completed" and run.get("conclusion") == "success" for run in pushes):
        return
    if any(run.get("status") != "completed" for run in pushes):
        raise GateError(workflow + " is still running for " + sha + "; wait for it to finish on main, then dispatch again")
    if pushes:
        raise GateError(workflow + " did not succeed for " + sha + "; fix main and dispatch again")
    raise GateError("no push run of " + workflow + " for " + sha + "; wait for main's " + workflow + ", then dispatch again")


def gh_json(path, *extra):
    return json.loads(subprocess.check_output(["gh", "api", path, *extra], text=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--workflow", default="check.yml")
    args = parser.parse_args(argv)
    try:
        status = gh_json("repos/" + args.repo + "/compare/" + args.branch + "..." + args.sha)["status"]
        require_on_branch(status, args.branch, args.sha)
        runs = gh_json("repos/" + args.repo + "/actions/workflows/" + args.workflow + "/runs?head_sha=" + args.sha + "&event=push&per_page=50")["workflow_runs"]
        require_check_passed(runs, args.sha, args.workflow)
    except GateError as err:
        print("release refused: " + str(err), file=sys.stderr)
        return 1
    except (subprocess.CalledProcessError, KeyError, ValueError) as err:
        print("release refused: could not read the commit's state (" + type(err).__name__ + ")", file=sys.stderr)
        return 1
    print(args.sha + " is on " + args.branch + " and " + args.workflow + " passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
