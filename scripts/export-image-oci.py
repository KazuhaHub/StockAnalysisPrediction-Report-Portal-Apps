"""Export an OCI image layout into descriptor image entries and flat blob files.

Input is an OCI layout directory or a .tar (for example the output of
`docker save <image-id> -o image.tar` on Docker 25 or later, which writes an OCI layout).
Output is a new directory holding `images.json` (the `backend.images` entries)
and `blobs/<sha256>` for every manifest, config and layer. The publisher's
index.json, manifest.json and oci-layout are never forwarded.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
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
            if not info.isreg():
                # docker save may add links beside the layout; only regular files are ever read.
                continue
            if name in self.members:
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


def copy_blob(layout, digest, destination, expected_size, limit=oci.MAX_BLOB_BYTES):
    """Copy one blob while hashing it, so a blob is never trusted by name."""
    if expected_size > limit or layout.blob_size(digest) != expected_size:
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


GZIP_OF = {
    'application/vnd.oci.image.layer.v1.tar': 'application/vnd.oci.image.layer.v1.tar+gzip',
    'application/vnd.docker.image.rootfs.diff.tar': 'application/vnd.docker.image.rootfs.diff.tar.gzip',
}
# Room left in the package for the descriptor, signature and frontend.
PACKAGE_HEADROOM = 24 << 20


def gzip_layer(source_path, target_path):
    """Compress a layer deterministically: level 9, no name, fixed mtime."""
    with source_path.open('rb') as source, target_path.open('wb') as raw:
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', compresslevel=9, mtime=0) as out:
            for chunk in iter(lambda: source.read(oci.CHUNK), b''):
                out.write(chunk)


def export_platform(layout, platform, blobs_dir):
    found = find_manifest(layout, index_entries(layout), platform)
    if not found:
        raise ImageError('no image manifest for ' + platform)
    if len(found) > 1:
        raise ImageError('more than one image manifest for ' + platform)
    manifest_digest = next(iter(found))
    manifest_raw = read_blob_bytes(layout, manifest_digest)
    # Layers are read with the uncompressed-layer bound here; the host's blob bound is applied after any
    # compression, below.
    _, config_desc, layers = oci.parse_manifest(manifest_raw, max_layer=oci.MAX_LAYER_UNCOMPRESSED_BYTES)
    config_digest = oci.digest_hex(config_desc['digest'])
    config_raw = read_blob_bytes(layout, config_digest)
    if len(config_raw) != config_desc['size']:
        raise ImageError('config size differs from the manifest')
    diff_ids = oci.parse_config(config_raw, platform)
    if len(diff_ids) != len(layers):
        raise ImageError('layer count differs between manifest and config')
    # Copy each layer under its original digest first, measuring it against the config diff_id.
    originals, measured = [], []
    for layer, expected_diff in zip(layers, diff_ids):
        digest = oci.digest_hex(layer['digest'])
        if layout.blob_size(digest) != layer['size']:
            raise ImageError('blob size differs from its descriptor')
        copy_blob(layout, digest, blobs_dir, layer['size'], limit=oci.MAX_LAYER_UNCOMPRESSED_BYTES)
        with (Path(blobs_dir) / digest).open('rb') as stream:
            diff_id, size = oci.measure_layer(stream, layer['mediaType'])
        if diff_id != expected_diff:
            raise ImageError('layer content does not match the config diff_id')
        originals.append(digest)
        measured.append((diff_id, size))
    sizes = [layer['size'] for layer in layers]
    needs_gzip = (any(size > oci.MAX_BLOB_BYTES for size in sizes) or
                  sum(sizes) + len(manifest_raw) + len(config_raw) > oci.MAX_PACKAGE_BYTES - PACKAGE_HEADROOM)
    if needs_gzip:
        manifest = oci.strict_json(manifest_raw, True)
        converted = {}
        for layer in manifest['layers']:
            if layer['mediaType'] not in GZIP_OF:
                continue
            original = oci.digest_hex(layer['digest'])
            if original not in converted:
                temporary = Path(blobs_dir) / ('.gzip-' + original)
                gzip_layer(Path(blobs_dir) / original, temporary)
                digest, size = oci.hash_file(temporary)
                temporary.replace(Path(blobs_dir) / digest)
                converted[original] = (digest, size)
            digest, size = converted[original]
            layer.update({'mediaType': GZIP_OF[layer['mediaType']], 'digest': 'sha256:' + digest, 'size': size})
        kept = {oci.digest_hex(layer['digest']) for layer in manifest['layers']}
        for original in converted:
            if original not in kept:
                (Path(blobs_dir) / original).unlink()
        manifest_raw = json.dumps(manifest, separators=(',', ':')).encode()
        manifest_digest = oci.sha256_hex(manifest_raw)
        _, _, layers = oci.parse_manifest(manifest_raw)
    entry_layers, total = [], 0
    for layer, (diff_id, size) in zip(layers, measured):
        if layer['size'] > oci.MAX_BLOB_BYTES:
            raise ImageError('a layer is larger than the blob bound even after compression')
        total += size
        entry_layers.append({'diff_id': diff_id, 'uncompressed_bytes': size})
    if total > oci.MAX_IMAGE_UNCOMPRESSED_BYTES:
        raise ImageError('image expands beyond the allowed total')
    on_disk = sum((Path(blobs_dir) / oci.digest_hex(layer['digest'])).stat().st_size for layer in layers)
    if on_disk + len(manifest_raw) + len(config_raw) > oci.MAX_PACKAGE_BYTES - PACKAGE_HEADROOM:
        raise ImageError('the image does not fit in a package even after compression')
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='OCI layout directory or .tar (the output of docker save on Docker 25 or later)')
    parser.add_argument('--platform', action='append', required=True, choices=oci.PLATFORMS)
    parser.add_argument('--output', type=Path, required=True, help='new directory for images.json and blobs/')
    args = parser.parse_args()
    try:
        print(json.dumps(export_oci(args.source, args.platform, args.output), indent=2))
    except (OSError, ImageError, ImageError) as err:
        parser.exit(1, 'Image export failed: ' + str(err) + '\n')
