"""Push a .portalapp to an OCI registry as an artifact (plain registry HTTP, no extra tools).

Manifest: application/vnd.oci.image.manifest.v1+json with artifactType
application/vnd.portal.app.package.v2, the OCI empty descriptor as config and exactly one layer,
application/vnd.portal.app.package.v2+zip, holding the .portalapp bytes unchanged.
The tag is a convenience for people; consumers pin the manifest digest this prints.
Credentials come from REGISTRY_USER and REGISTRY_PASSWORD (never printed); a registry that
needs none (a local test registry) is used anonymously.
"""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MANIFEST_TYPE = "application/vnd.oci.image.manifest.v1+json"
ARTIFACT_TYPE = "application/vnd.portal.app.package.v2"
LAYER_TYPE = "application/vnd.portal.app.package.v2+zip"
EMPTY_TYPE = "application/vnd.oci.empty.v1+json"
EMPTY_DIGEST = "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
# The Portal's repository grammar (SplitOCIRepository): host[:443]/path, lower case, path components with
# single separators or `__` or runs of `-`. A local test registry (127.0.0.1 or localhost) may use any port.
PATH_PART = r"[a-z0-9]+(?:(?:\.|_|__|-+)[a-z0-9]+)*"
HOST = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*"
REPOSITORY = re.compile("(?:" + HOST + r"(?::443)?|(?:127\.0\.0\.1|localhost):[0-9]+)/" + PATH_PART + "(?:/" + PATH_PART + ")*")
TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


def file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def build_manifest(layer_digest, layer_size, annotations=None):
    """Return (manifest bytes, manifest digest). Compact, key-sorted JSON so the bytes are reproducible."""
    manifest = {
        "schemaVersion": 2,
        "mediaType": MANIFEST_TYPE,
        "artifactType": ARTIFACT_TYPE,
        "config": {"mediaType": EMPTY_TYPE, "digest": EMPTY_DIGEST, "size": 2},
        "layers": [{"mediaType": LAYER_TYPE, "digest": layer_digest, "size": layer_size}],
    }
    if annotations:
        manifest["annotations"] = dict(sorted(annotations.items()))
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return raw, "sha256:" + hashlib.sha256(raw).hexdigest()


class Registry:
    def __init__(self, repository):
        if len(repository) > 255 or not REPOSITORY.fullmatch(repository):
            raise SystemExit("repository must be a lowercase registry/path name")
        self.host, _, self.name = repository.partition("/")
        bare = self.host.split(":")[0]
        if not bare.strip("0123456789."):  # a dotted all-digit host is an IPv4 literal; it must be well formed
            try:
                ipaddress.IPv4Address(bare)
            except ValueError:
                raise SystemExit("repository host is not a valid IPv4 address") from None
        local = self.host.split(":")[0] in ("127.0.0.1", "localhost")
        self.base = ("http://" if local else "https://") + self.host
        self.token = None
        self.user = os.environ.get("REGISTRY_USER", "")
        self.password = os.environ.get("REGISTRY_PASSWORD", "")

    def login(self):
        try:
            urllib.request.urlopen(self.base + "/v2/")
            return
        except urllib.error.HTTPError as err:
            if err.code != 401:
                raise
            challenge = err.headers.get("WWW-Authenticate", "")
        if not challenge.lower().startswith("bearer "):
            raise SystemExit("registry demands an unsupported authentication scheme")
        params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        query = urllib.parse.urlencode({"service": params.get("service", ""), "scope": "repository:" + self.name + ":pull,push"})
        realm = params["realm"]
        if urllib.parse.urlsplit(realm).scheme != "https" and not realm.startswith("http://127.0.0.1"):
            raise SystemExit("registry token realm must be https")
        request = urllib.request.Request(realm + "?" + query)
        if self.user:
            request.add_header("Authorization", "Basic " + base64.b64encode((self.user + ":" + self.password).encode()).decode())
        with urllib.request.urlopen(request) as response:
            self.token = json.load(response)["token"]

    def call(self, method, url, headers=None, data=None):
        request = urllib.request.Request(url if url.startswith("http") else self.base + url, data=data, method=method)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if self.token:
            request.add_header("Authorization", "Bearer " + self.token)
        return urllib.request.urlopen(request)

    def tag_exists(self, tag):
        try:
            self.call("HEAD", "/v2/" + self.name + "/manifests/" + tag, {"Accept": MANIFEST_TYPE}).close()
            return True
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return False
            raise

    def blob_exists(self, digest):
        try:
            self.call("HEAD", "/v2/" + self.name + "/blobs/" + digest).close()
            return True
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return False
            raise

    def push_blob(self, digest, size, body):
        if self.blob_exists(digest):
            return
        with self.call("POST", "/v2/" + self.name + "/blobs/uploads/", {"Content-Length": "0"}, b"") as response:
            location = response.headers["Location"]
        location = urllib.parse.urljoin(self.base + "/", location)
        location += ("&" if "?" in location else "?") + urllib.parse.urlencode({"digest": digest})
        with self.call("PUT", location, {"Content-Type": "application/octet-stream", "Content-Length": str(size)}, body) as response:
            if response.status != 201:
                raise SystemExit("blob upload refused")

    def push_manifest(self, tag, raw):
        headers = {"Content-Type": MANIFEST_TYPE, "Content-Length": str(len(raw))}
        with self.call("PUT", "/v2/" + self.name + "/manifests/" + tag, headers, raw) as response:
            if response.status != 201:
                raise SystemExit("manifest upload refused")
            return response.headers.get("Docker-Content-Digest")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, help="registry/path, for example ghcr.io/owner/apps/name")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--package", type=Path, help=".portalapp to push; omit with --check-absent")
    parser.add_argument("--annotation", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--check-absent", action="store_true", help="only fail when the tag already exists")
    parser.add_argument("--tolerate-denied", action="store_true",
                        help="with --check-absent: a 401/403 (for example a package that does not exist yet) is not a failure; "
                             "the push itself re-checks with write access")
    parser.add_argument("--digest-out", type=Path, help="file to write the manifest digest to")
    args = parser.parse_args(argv)
    if not TAG.match(args.tag):
        raise SystemExit("invalid tag")
    registry = Registry(args.repository)
    try:
        registry.login()
        exists = registry.tag_exists(args.tag)
    except urllib.error.HTTPError as err:
        if args.check_absent and args.tolerate_denied and err.code in (401, 403):
            print("cannot tell whether " + args.tag + " exists (HTTP " + str(err.code) + "); the publish step checks again", file=sys.stderr)
            return 0
        raise
    if exists:
        print("tag " + args.tag + " already exists in " + args.repository + "; packages are immutable", file=sys.stderr)
        return 1
    if args.check_absent:
        return 0
    if args.package is None:
        raise SystemExit("--package is required")
    annotations = dict(item.split("=", 1) for item in args.annotation)
    size = args.package.stat().st_size
    layer = file_digest(args.package)
    raw, digest = build_manifest(layer, size, annotations)
    registry.push_blob(EMPTY_DIGEST, 2, b"{}")
    with open(args.package, "rb") as stream:
        registry.push_blob(layer, size, stream)
    reported = registry.push_manifest(args.tag, raw)
    if reported not in (None, digest):
        raise SystemExit("registry computed a different manifest digest")
    if args.digest_out:
        args.digest_out.write_text(digest + "\n")
    print(digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
