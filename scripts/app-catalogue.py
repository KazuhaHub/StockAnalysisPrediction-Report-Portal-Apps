"""Append one release to the online application catalogue (portal.catalogue/2-dev.3).

The rules mirror the Portal's ParseCatalogue and ValidateCatalogueURL
(internal/appplatform/catalogue.go): a catalogue is a discovery hint only, the
Portal still verifies each descriptor's signature against an enrolled key.
"""
import argparse
import hashlib
import json
import posixpath
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

FORMAT = "portal.catalogue/2-dev.3"
ACCEPTED_FORMATS = ("portal.catalogue/2-dev.1", "portal.catalogue/2-dev.2", FORMAT)
MAX_BYTES = 1 << 20
MAX_RELEASES = 256
SLUG = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
DIGEST = re.compile(r"^[a-f0-9]{64}$")
VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$")
RELEASE_KEYS = {"app_id", "publisher_id", "version", "descriptor_sha256", "descriptor_url", "signature_url", "package_url", "package_oci"}
REQUIRED_KEYS = RELEASE_KEYS - {"package_url", "package_oci"}
REPOSITORY = re.compile(r"^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9]+([._-][a-z0-9]+)*)+$")
OCI_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


class CatalogueError(ValueError):
    pass


def valid_version(value):
    if len(value) > 128 or not VERSION.match(value):
        return False
    prerelease = value.split("+", 1)[0].partition("-")[2]
    for part in prerelease.split(".") if prerelease else []:
        if len(part) > 1 and part[0] == "0" and part.isdigit():
            return False
    return True


def validate_url(raw):
    """Canonical public HTTPS URL: no credentials, query, fragment, escapes or odd port."""
    if not isinstance(raw, str) or not raw or len(raw) > 2048 or any(c in raw for c in "\\\x00\r\n\t %"):
        raise CatalogueError("invalid catalogue URL")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise CatalogueError("invalid catalogue URL") from None
    if (parts.scheme != "https" or not parts.hostname or "@" in parts.netloc or parts.query or parts.fragment
            or raw.endswith("?") or (port not in (None, 443)) or not parts.path.startswith("/")
            or posixpath.normpath(parts.path) != parts.path):
        raise CatalogueError("invalid catalogue URL")


def _no_duplicate_keys(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise CatalogueError("duplicate JSON key")
    return dict(pairs)


def parse(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise CatalogueError("catalogue size")
    try:
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CatalogueError("catalogue is not strict JSON") from None
    if not isinstance(doc, dict) or set(doc) != {"format", "releases"} or doc["format"] not in ACCEPTED_FORMATS:
        raise CatalogueError("catalogue format")
    releases = doc["releases"]
    if not isinstance(releases, list) or len(releases) > MAX_RELEASES:
        raise CatalogueError("catalogue releases")
    seen = set()
    for release in releases:
        if not isinstance(release, dict) or not REQUIRED_KEYS <= set(release) <= RELEASE_KEYS:
            raise CatalogueError("release fields")
        if not all(isinstance(release[key], str) for key in release if key != "package_oci"):
            raise CatalogueError("release field types")
        identity = release["publisher_id"] + "/" + release["app_id"] + "/" + release["version"]
        if (not SLUG.match(release["app_id"]) or not SLUG.match(release["publisher_id"]) or not valid_version(release["version"])
                or not DIGEST.match(release["descriptor_sha256"]) or identity in seen or release["descriptor_sha256"] in seen):
            raise CatalogueError("release identity")
        validate_url(release["descriptor_url"])
        validate_url(release["signature_url"])
        if "package_url" in release:
            if doc["format"] != "portal.catalogue/2-dev.2" or not release["package_url"]:
                raise CatalogueError("package_url")
            validate_url(release["package_url"])
        if "package_oci" in release:
            oci = release["package_oci"]
            if (doc["format"] != FORMAT or "package_url" in release or not isinstance(oci, dict) or set(oci) != {"repository", "digest"}
                    or not isinstance(oci["repository"], str) or len(oci["repository"]) > 255 or not REPOSITORY.match(oci["repository"])
                    or not isinstance(oci["digest"], str) or not OCI_DIGEST.match(oci["digest"])):
                raise CatalogueError("package_oci")
        seen.update((identity, release["descriptor_sha256"]))
    return doc


def add_release(current, descriptor_bytes, descriptor_url, signature_url, repository, digest):
    """Return the new catalogue bytes: `current` (None when absent) plus this descriptor's release."""
    doc = parse(current) if current is not None else {"format": FORMAT, "releases": []}
    if doc["format"] != FORMAT:
        raise CatalogueError("catalogue is " + doc["format"] + ", not " + FORMAT)
    descriptor = json.loads(descriptor_bytes.decode("utf-8"))
    app_id, version = descriptor["id"], descriptor["version"]
    if any(r["app_id"] == app_id and r["version"] == version for r in doc["releases"]):
        raise CatalogueError("catalogue already lists " + app_id + " " + version)
    if len(doc["releases"]) >= MAX_RELEASES:
        raise CatalogueError("catalogue is full (" + str(MAX_RELEASES) + " releases)")
    doc["releases"].append({
        "app_id": app_id,
        "publisher_id": descriptor["publisher"],
        "version": version,
        "descriptor_sha256": hashlib.sha256(descriptor_bytes).hexdigest(),
        "descriptor_url": descriptor_url,
        "signature_url": signature_url,
        "package_oci": {"repository": repository, "digest": digest},
    })
    out = (json.dumps(doc, indent=2) + "\n").encode()
    parse(out)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, help="existing catalogue.json; absent starts an empty catalogue")
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--descriptor-url", required=True)
    parser.add_argument("--signature-url", required=True)
    parser.add_argument("--repository", required=True, help="OCI repository of the package, without a tag or digest")
    parser.add_argument("--digest", required=True, help="manifest digest of the pushed package, sha256:...")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        current = args.current.read_bytes() if args.current is not None and args.current.exists() else None
        args.output.write_bytes(add_release(current, args.descriptor.read_bytes(), args.descriptor_url, args.signature_url, args.repository, args.digest))
    except (CatalogueError, KeyError, ValueError, OSError) as err:
        print("catalogue refused: " + str(err), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
