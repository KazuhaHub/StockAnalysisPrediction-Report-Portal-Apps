"""Prepare a local checkout of the catalogue branch for the publish job.

`git ls-remote --exit-code` exits 2 when the branch is absent and with anything else (128 for a network or
authentication failure) when it cannot tell. Only 2 means "start an orphan branch"; every other failure aborts,
before anything is pushed, so a transient error can never reset the catalogue.
The remote's credentials come from the environment variable CATALOGUE_AUTH (an Authorization header value).
"""
import argparse
import os
import subprocess
import sys

BRANCH = "catalogue"


class BranchError(RuntimeError):
    pass


def interpret_ls_remote(returncode):
    """True when the branch exists, False when it is absent; anything else aborts."""
    if returncode == 0:
        return True
    if returncode == 2:
        return False
    raise BranchError("git ls-remote failed with status " + str(returncode) + "; refusing to guess whether the branch exists")


def git(directory, *args, check=True):
    command = ["git", "-C", directory]
    auth = os.environ.get("CATALOGUE_AUTH")
    if auth:
        command += ["-c", "http.https://github.com/.extraheader=" + auth]
    return subprocess.run(command + list(args), check=check, stdout=subprocess.DEVNULL if args[0] == "ls-remote" else None)


def prepare(directory, remote, run=git):
    run(directory, "init", "-q", "-b", BRANCH)
    run(directory, "remote", "add", "origin", remote)
    found = interpret_ls_remote(run(directory, "ls-remote", "--exit-code", "--heads", "origin", BRANCH, check=False).returncode)
    if found:
        run(directory, "fetch", "-q", "--depth", "1", "origin", BRANCH)
        run(directory, "reset", "-q", "--hard", "FETCH_HEAD")
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--remote", required=True)
    args = parser.parse_args(argv)
    try:
        print("catalogue branch " + ("found" if prepare(args.dir, args.remote) else "absent; starting an orphan branch"))
    except (BranchError, subprocess.CalledProcessError) as err:
        print("catalogue branch refused: " + str(err), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
