"""Tell the legacy Status line from the v2 line, so legacy-only tooling can step aside.

The legacy line ships apps/status/app.json. The v2 line ships apps/status/app.v2.json
instead, and an app folder never holds both. The legacy release build, container
smoke and browser acceptance assume the legacy manifest, its -listen/-pairing-file
flags and its own backup and restore, so they apply only while app.json is the
manifest.
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def uses_v2_line(root=ROOT):
    return (Path(root) / "apps/status/app.v2.json").is_file()


def skip_message(what):
    return (f"{what} skipped: apps/status/app.v2.json exists, so this is the Status v2 line. "
            "It targets the legacy app.json, flags, backup and restore. "
            "The v2 packaging step (OCI image export, scripts/build-app-v2.py, offline envelope "
            "and licence scan) replaces it once it lands.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--github-output", type=Path, help="Append legacy=true or legacy=false for later jobs")
    args = parser.parse_args(argv)
    legacy = not uses_v2_line(args.root)
    if not legacy:
        print("::notice title=Status v2 line::" + skip_message("The legacy Status release, container and browser jobs"))
    else:
        print("Status legacy line: the legacy release, container and browser jobs run.")
    if args.github_output:
        with args.github_output.open("a") as output:
            output.write(f"legacy={'true' if legacy else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
