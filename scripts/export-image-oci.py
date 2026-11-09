"""Export an OCI image layout into descriptor image entries and flat blob files.

Input is an OCI layout directory or a .tar (for example the output of
`docker buildx build --platform linux/amd64 --output type=oci,dest=image.tar .`).
Output is a new directory holding `images.json` (the `backend.images` entries)
and `blobs/<sha256>` for every manifest, config and layer. The publisher's
index.json, manifest.json and oci-layout are never forwarded.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

def shared_oci_image():
    """Load oci_image.py once per process so every script raises the same ImageError class."""
    cached = sys.modules.get('oci_image')
    if cached is None:
        spec = importlib.util.spec_from_file_location('oci_image', Path(__file__).with_name('oci_image.py'))
        cached = importlib.util.module_from_spec(spec)
        sys.modules['oci_image'] = cached
        spec.loader.exec_module(cached)
    return cached


oci = shared_oci_image()
ImageError = oci.ImageError
MAX_DEPTH = 3


class DirLayout:
    def __init__(self, root):
        root = Path(root)
        if root.is_symlink() or not root.is_dir():
            raise ImageError('OCI layout must be a real directory')
        self.root = root

    def _path(self, relative):
        path = self.root / relative
        if path.is_symlink() or not path.is_file():
            raise ImageError('OCI layout is missing ' + relative)
        return path

    def read_small(self, relative, limit=oci.MAX_METADATA_BYTES):
        path = self._path(relative)
        if path.stat().st_size > limit:
            raise ImageError(relative + ' exceeds its bound')
        return path.read_bytes()

    def blob_size(self, digest):
        return self._path('blobs/sha256/' + digest).stat().st_size

    def open_blob(self, digest):
        return self._path('blobs/sha256/' + digest).open('rb')

    def close(self):
        pass


class TarLayout:
    def __init__(self, path):
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise ImageError('OCI layout archive must be a regular file')
        try:
            self.tar = tarfile.open(path, 'r:')
        except tarfile.TarError as err:
            raise ImageError('OCI layout archive is unreadable: ' + str(err)) from None
        self.members = {}
        for info in self.tar.getmembers():
            name = info.name[2:] if info.name.startswith('./') else info.name
            if name.startswith('/') or '..' in name.split('/'):
                raise ImageError('OCI layout archive has an unsafe member name')
            if info.isdir():
                continue
            if not info.isreg() or name in self.members:
                raise ImageError('OCI layout archive may hold only unique regular files')
            self.members[name] = info

    def _member(self, relative):
        info = self.members.get(relative)
        if info is None:
            raise ImageError('OCI layout is missing ' + relative)
        return info

    def read_small(self, relative, limit=oci.MAX_METADATA_BYTES):
        info = self._member(relative)
        if info.size > limit:
            raise ImageError(relative + ' exceeds its bound')
        return self.tar.extractfile(info).read()

    def blob_size(self, digest):
        return self._member('blobs/sha256/' + digest).size

    def open_blob(self, digest):
        return self.tar.extractfile(self._member('blobs/sha256/' + digest))

    def close(self):
        self.tar.close()


def open_layout(source):
    source = Path(source)
    layout = DirLayout(source) if source.is_dir() else TarLayout(source)
    try:
        marker = oci.strict_json(layout.read_small('oci-layout'), False)
        if marker.get('imageLayoutVersion') != '1.0.0':
            raise ImageError('unsupported OCI layout version')
    except BaseException:
        layout.close()
        raise
    return layout


def read_blob_bytes(layout, digest, limit=oci.MAX_METADATA_BYTES):
    if layout.blob_size(digest) > limit:
        raise ImageError('metadata blob exceeds its bound')
    with layout.open_blob(digest) as stream:
        raw = stream.read(limit + 1)
    if oci.sha256_hex(raw) != digest:
        raise ImageError('layout blob does not match its digest')
    return raw


def descriptor_platform(item):
    value = item.get('platform')
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ImageError('descriptor platform is malformed')
    return value


def is_attestation(item):
    platform = descriptor_platform(item)
    annotations = item.get('annotations') if isinstance(item.get('annotations'), dict) else {}
    return ((platform or {}).get('os') == 'unknown' or
            annotations.get('vnd.docker.reference.type') == 'attestation-manifest')


def find_manifest(layout, entries, platform, depth=0, found=None):
    """Collect the distinct manifest digests whose platform matches. An index is
    followed to resolve down to manifests; attestation entries are skipped."""
    found = {} if found is None else found
    if depth >= MAX_DEPTH:
        raise ImageError('image index nesting is too deep')
    want_os, want_arch = platform.split('/', 1)
    for item in entries:
        if not isinstance(item, dict):
            raise ImageError('index entry is malformed')
        media_type = item.get('mediaType')
        digest = oci.digest_hex(item.get('digest'))
        if is_attestation(item):
            continue
        if media_type in oci.INDEX_TYPES:
            index = oci.strict_json(read_blob_bytes(layout, digest), True)
            nested = index.get('manifests')
            if not isinstance(nested, list):
                raise ImageError('image index has no manifests')
            find_manifest(layout, nested, platform, depth + 1, found)
        elif media_type in oci.MANIFEST_TYPES:
            declared = descriptor_platform(item)
            if declared is not None:
                matches = declared.get('os') == want_os and declared.get('architecture') == want_arch
            else:
                matches = config_matches(layout, digest, platform)
            if matches:
                found[digest] = media_type
        else:
            raise ImageError('index entry has an unsupported media type')
    return found


def config_matches(layout, manifest_digest, platform):
    _, config_desc, _ = oci.parse_manifest(read_blob_bytes(layout, manifest_digest))
    raw = read_blob_bytes(layout, oci.digest_hex(config_desc['digest']))
    config = oci.strict_json(raw, False)
    return config.get('os') == 'linux' and config.get('architecture') == oci.architecture(platform)


def index_entries(layout):
    index = oci.strict_json(layout.read_small('index.json'), True)
    entries = index.get('manifests')
    if not isinstance(entries, list) or not entries:
        raise ImageError('index.json has no manifests')
    return entries


def copy_blob(layout, digest, destination, expected_size):
    """Copy one blob while hashing it, so a blob is never trusted by name."""
    if expected_size > oci.MAX_BLOB_BYTES or layout.blob_size(digest) != expected_size:
        raise ImageError('blob size differs from its descriptor or exceeds its bound')
    target = Path(destination) / digest
    if target.exists():
        return
    hasher, total = hashlib.sha256(), 0
    with layout.open_blob(digest) as source, target.open('wb') as out:
        for chunk in iter(lambda: source.read(oci.CHUNK), b''):
            total += len(chunk)
            if total > expected_size:
                raise ImageError('blob is longer than declared')
            hasher.update(chunk)
            out.write(chunk)
    if total != expected_size or hasher.hexdigest() != digest:
        raise ImageError('layout blob does not match its digest')


def export_platform(layout, platform, blobs_dir):
    found = find_manifest(layout, index_entries(layout), platform)
    if not found:
        raise ImageError('no image manifest for ' + platform)
    if len(found) > 1:
        raise ImageError('more than one image manifest for ' + platform)
    manifest_digest = next(iter(found))
    manifest_raw = read_blob_bytes(layout, manifest_digest)
    _, config_desc, layers = oci.parse_manifest(manifest_raw)
    config_digest = oci.digest_hex(config_desc['digest'])
    config_raw = read_blob_bytes(layout, config_digest)
    if len(config_raw) != config_desc['size']:
        raise ImageError('config size differs from the manifest')
    diff_ids = oci.parse_config(config_raw, platform)
    if len(diff_ids) != len(layers):
        raise ImageError('layer count differs between manifest and config')
    entry_layers, total = [], 0
    for layer, expected_diff in zip(layers, diff_ids):
        digest = oci.digest_hex(layer['digest'])
        copy_blob(layout, digest, blobs_dir, layer['size'])
        with (Path(blobs_dir) / digest).open('rb') as stream:
            diff_id, size = oci.measure_layer(stream, layer['mediaType'])
        if diff_id != expected_diff:
            raise ImageError('layer content does not match the config diff_id')
        total += size
        entry_layers.append({'diff_id': diff_id, 'uncompressed_bytes': size})
    if total > oci.MAX_IMAGE_UNCOMPRESSED_BYTES:
        raise ImageError('image expands beyond the allowed total')
    for digest, raw in ((manifest_digest, manifest_raw), (config_digest, config_raw)):
        (Path(blobs_dir) / digest).write_bytes(raw)
    entry = {
        'platform': platform, 'manifest_digest': manifest_digest,
        'config_digest': config_digest, 'layers': entry_layers,
    }
    oci.plan_image(entry, manifest_raw, config_raw)
    return entry


def export_oci(source, platforms, output):
    """Write images.json and blobs/ under a new output directory; return entries."""
    if not platforms or len(set(platforms)) != len(platforms):
        raise ImageError('name each platform once')
    for platform in platforms:
        oci.architecture(platform)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ImageError('output already exists; choose a new directory')
    layout = open_layout(source)
    try:
        output.mkdir(parents=True)
        try:
            blobs = output / 'blobs'
            blobs.mkdir()
            entries = [export_platform(layout, platform, blobs) for platform in platforms]
            (output / 'images.json').write_text(
                json.dumps(entries, indent=2) + '\n', encoding='utf-8')
        except BaseException:
            shutil.rmtree(output)
            raise
    finally:
        layout.close()
    return entries


def buildx_export(context, archive, platform, dockerfile=None):
    """Thin wrapper around docker buildx; the only place Docker is invoked."""
    command = ['docker', 'buildx', 'build', '--platform', platform, '--provenance=false',
               '--sbom=false', '--output', 'type=oci,dest=' + str(archive)]
    if dockerfile:
        command += ['--file', str(dockerfile)]
    subprocess.run(command + [str(context)], check=True)
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, nargs='?',
                        help='OCI layout directory or .tar; omit with --context to build')
    parser.add_argument('--context', type=Path, help='build context; runs docker buildx to create the layout')
    parser.add_argument('--dockerfile', type=Path)
    parser.add_argument('--platform', action='append', required=True, choices=oci.PLATFORMS)
    parser.add_argument('--output', type=Path, required=True, help='new directory for images.json and blobs/')
    args = parser.parse_args()
    try:
        source = args.source
        if args.context is not None:
            if source is None or len(args.platform) != 1:
                parser.error('--context needs a destination archive path and exactly one --platform')
            source = buildx_export(args.context, source, args.platform[0], args.dockerfile)
        elif source is None:
            parser.error('give an OCI layout or --context')
        print(json.dumps(export_oci(source, args.platform, args.output), indent=2))
    except (OSError, ImageError, subprocess.CalledProcessError) as err:
        parser.exit(1, 'Image export failed: ' + str(err) + '\n')
