"""Shared rules for managed image delivery: OCI manifests, layers and descriptor image entries.

The checks mirror the host's admission rules so a package that passes here is
not refused later for a reason the publisher could have seen. The host stays
authoritative; nothing here establishes trust.
"""
import gzip
import hashlib
import json
from pathlib import Path
import re

MAX_IMAGE_LAYERS = 32
MAX_IMAGE_PLATFORMS = 2
MAX_BLOB_BYTES = 256 << 20
MAX_METADATA_BYTES = 1 << 20
MAX_LAYER_UNCOMPRESSED_BYTES = 1 << 30
MAX_IMAGE_UNCOMPRESSED_BYTES = 4 << 30
MAX_PACKAGE_ENTRIES = 160
MAX_PACKAGE_BYTES = 384 << 20
PLATFORMS = ('linux/amd64', 'linux/arm64')
CHUNK = 1 << 20

MANIFEST_TYPES = {
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.docker.distribution.manifest.v2+json',
}
INDEX_TYPES = {
    'application/vnd.oci.image.index.v1+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
}
CONFIG_TYPES = {
    'application/vnd.oci.image.config.v1+json',
    'application/vnd.docker.container.image.v1+json',
}
# Media type -> whether the blob is gzip-compressed. zstd, foreign and
# non-distributable layers are refused in this release.
LAYER_TYPES = {
    'application/vnd.oci.image.layer.v1.tar': False,
    'application/vnd.oci.image.layer.v1.tar+gzip': True,
    'application/vnd.docker.image.rootfs.diff.tar': False,
    'application/vnd.docker.image.rootfs.diff.tar.gzip': True,
}
HEX = re.compile(r'[a-f0-9]{64}')


class ImageError(ValueError):
    pass


def sha256_hex(raw):
    return hashlib.sha256(raw).hexdigest()


def digest_hex(value):
    """Accept only the sha256:<hex> form and return the hex."""
    if not isinstance(value, str) or not value.startswith('sha256:'):
        raise ImageError('digest must use the sha256 form')
    hex_part = value[len('sha256:'):]
    if not HEX.fullmatch(hex_part):
        raise ImageError('digest is malformed')
    return hex_part


def architecture(platform):
    if platform not in PLATFORMS:
        raise ImageError('unsupported platform: ' + str(platform))
    return platform.split('/', 1)[1]


def strict_json(raw, closed):
    """Parse one JSON object with a single interpretation: no duplicate keys,
    and for a closed document no keys that differ only by case."""
    def hook(pairs):
        seen = set()
        for key, _ in pairs:
            folded = key.lower() if closed else key
            if folded in seen:
                raise ImageError('duplicate key in image document')
            seen.add(folded)
        return dict(pairs)
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=hook)
    except (UnicodeDecodeError, ValueError) as err:
        if isinstance(err, ImageError):
            raise
        raise ImageError('image document is not valid JSON') from None
    if not isinstance(value, dict):
        raise ImageError('image document must be an object')
    return value


def _closed(value, allowed, what):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ImageError(what + ' has unknown or malformed fields')
    return value


def parse_manifest(raw):
    """Return (media_type, config_descriptor, layer_descriptors) for a single
    platform image manifest. An index or manifest list is refused."""
    if not raw or len(raw) > MAX_METADATA_BYTES:
        raise ImageError('manifest size is out of bounds')
    manifest = strict_json(raw, True)
    _closed(manifest, ('schemaVersion', 'mediaType', 'config', 'layers', 'annotations'), 'manifest')
    if manifest.get('schemaVersion') != 2 or manifest.get('mediaType') not in MANIFEST_TYPES:
        raise ImageError('manifest must be an OCI or Docker schema 2 image manifest')
    config = _closed(manifest.get('config'), ('mediaType', 'digest', 'size', 'annotations'), 'config descriptor')
    if config.get('mediaType') not in CONFIG_TYPES:
        raise ImageError('unsupported config media type')
    layers = manifest.get('layers')
    if not isinstance(layers, list) or not layers or len(layers) > MAX_IMAGE_LAYERS:
        raise ImageError('layer count is out of bounds')
    for layer in layers:
        _closed(layer, ('mediaType', 'digest', 'size', 'annotations'), 'layer descriptor')
        if layer.get('mediaType') not in LAYER_TYPES:
            raise ImageError('unsupported layer media type (zstd and foreign layers are refused)')
        size = layer.get('size')
        if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_BLOB_BYTES:
            raise ImageError('layer size is out of bounds')
        digest_hex(layer.get('digest'))
    size = config.get('size')
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise ImageError('config size is invalid')
    digest_hex(config.get('digest'))
    return manifest['mediaType'], config, layers


def parse_config(raw, platform):
    if not raw or len(raw) > MAX_METADATA_BYTES:
        raise ImageError('config size is out of bounds')
    config = strict_json(raw, False)
    rootfs = config.get('rootfs')
    volumes = (config.get('config') or {}).get('Volumes') if isinstance(config.get('config'), dict) else None
    if (config.get('os') != 'linux' or config.get('architecture') != architecture(platform) or
            not isinstance(rootfs, dict) or rootfs.get('type') != 'layers' or
            not isinstance(rootfs.get('diff_ids'), list) or volumes):
        raise ImageError('image config does not describe a volume-free linux image for ' + platform)
    return [digest_hex(value) for value in rootfs['diff_ids']]


def blob_record(digest, kind, media_type, size, diff_id=None, uncompressed_bytes=None):
    record = {'digest': digest, 'kind': kind, 'media_type': media_type, 'size': size}
    if kind == 'layer':
        record['diff_id'] = diff_id
        record['uncompressed_bytes'] = uncompressed_bytes
    return record


def plan_image(entry, manifest_raw, config_raw):
    """Bind one descriptor image entry to its manifest and config bytes.

    Returns the ordered blob records: manifest, config, then the layers."""
    if sha256_hex(manifest_raw) != entry['manifest_digest'] or sha256_hex(config_raw) != entry['config_digest']:
        raise ImageError('manifest or config bytes do not match the descriptor digests')
    media_type, config_desc, layers = parse_manifest(manifest_raw)
    if digest_hex(config_desc['digest']) != entry['config_digest'] or config_desc['size'] != len(config_raw):
        raise ImageError('manifest config reference does not match the config blob')
    diff_ids = parse_config(config_raw, entry['platform'])
    declared = entry['layers']
    if len(layers) != len(declared) or len(diff_ids) != len(declared):
        raise ImageError('layer count differs between manifest, config and descriptor')
    blobs = [
        blob_record(entry['manifest_digest'], 'manifest', media_type, len(manifest_raw)),
        blob_record(entry['config_digest'], 'config', config_desc['mediaType'], len(config_raw)),
    ]
    for layer, diff_id, claim in zip(layers, diff_ids, declared):
        if diff_id != claim['diff_id']:
            raise ImageError('layer diff_id order differs between config and descriptor')
        blobs.append(blob_record(
            digest_hex(layer['digest']), 'layer', layer['mediaType'], layer['size'],
            claim['diff_id'], claim['uncompressed_bytes']))
    return blobs


def validate_backend_images(backend):
    """Check the shape of backend.images against the descriptor rules."""
    images = backend.get('images')
    if backend.get('image') is not None or not isinstance(images, list) or not images:
        raise ImageError('backend must carry images and no image reference')
    platforms = backend.get('platforms')
    names = [item.get('platform') if isinstance(item, dict) else None for item in images]
    if (not isinstance(platforms, list) or len(images) > MAX_IMAGE_PLATFORMS or
            len(set(platforms)) != len(platforms) or sorted(map(str, names)) != sorted(map(str, platforms))):
        raise ImageError('image platforms must equal backend.platforms exactly')
    for item in images:
        if not isinstance(item, dict) or set(item) != {'platform', 'manifest_digest', 'config_digest', 'layers'}:
            raise ImageError('image entry has unknown or missing fields')
        architecture(item['platform'])
        for key in ('manifest_digest', 'config_digest'):
            if not isinstance(item[key], str) or not HEX.fullmatch(item[key]):
                raise ImageError(key + ' must be 64 lowercase hex characters')
        layers = item['layers']
        if not isinstance(layers, list) or not layers or len(layers) > MAX_IMAGE_LAYERS:
            raise ImageError('layer count is out of bounds')
        total = 0
        for layer in layers:
            if not isinstance(layer, dict) or set(layer) != {'diff_id', 'uncompressed_bytes'}:
                raise ImageError('layer entry has unknown or missing fields')
            size = layer['uncompressed_bytes']
            if (not isinstance(layer['diff_id'], str) or not HEX.fullmatch(layer['diff_id']) or
                    not isinstance(size, int) or isinstance(size, bool) or
                    not 1 <= size <= MAX_LAYER_UNCOMPRESSED_BYTES):
                raise ImageError('layer entry is out of bounds')
            total += size
        if total > MAX_IMAGE_UNCOMPRESSED_BYTES:
            raise ImageError('image expands beyond the allowed total')


def measure_layer(stream, media_type, limit=MAX_LAYER_UNCOMPRESSED_BYTES):
    """Return (diff_id, uncompressed_bytes) for a layer stream, decompressing
    while hashing and stopping a bomb at the limit."""
    compressed = LAYER_TYPES.get(media_type)
    if compressed is None:
        raise ImageError('unsupported layer media type')
    reader = gzip.GzipFile(fileobj=stream) if compressed else stream
    digest = hashlib.sha256()
    total = 0
    try:
        while True:
            chunk = reader.read(CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ImageError('layer expands beyond its bound')
            digest.update(chunk)
    except (OSError, EOFError) as err:
        raise ImageError('layer cannot be decompressed: ' + str(err)) from None
    if total < 1:
        raise ImageError('layer is empty')
    return digest.hexdigest(), total


def hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(CHUNK), b''):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def collect_blobs(images, blob_dir):
    """Verify every image of a descriptor against a directory of blob files
    named by their sha256 hex. Returns {digest: (path, record)} holding exactly
    the referenced set; shared blobs appear once."""
    validate_backend_images({'images': images, 'platforms': [item['platform'] for item in images]})
    blob_dir = Path(blob_dir)
    if blob_dir.is_symlink() or not blob_dir.is_dir():
        raise ImageError('image blob directory must be a real directory')

    def regular(digest):
        path = blob_dir / digest
        if path.is_symlink() or not path.is_file():
            raise ImageError('missing image blob ' + digest)
        return path

    known = {}
    for entry in images:
        manifest_path, config_path = regular(entry['manifest_digest']), regular(entry['config_digest'])
        for path in (manifest_path, config_path):
            if path.stat().st_size > MAX_METADATA_BYTES:
                raise ImageError('metadata blob exceeds its bound')
        records = plan_image(entry, manifest_path.read_bytes(), config_path.read_bytes())
        for record in records:
            path = regular(record['digest'])
            if record['digest'] in known:
                if known[record['digest']][1] != record:
                    raise ImageError('one blob is used in two different roles')
                continue
            digest, size = hash_file(path)
            if digest != record['digest'] or size != record['size'] or size > MAX_BLOB_BYTES:
                raise ImageError('blob bytes do not match their digest or declared size')
            if record['kind'] == 'layer':
                with path.open('rb') as source:
                    diff_id, uncompressed = measure_layer(source, record['media_type'])
                if diff_id != record['diff_id'] or uncompressed != record['uncompressed_bytes']:
                    raise ImageError('layer content does not match its diff_id or size')
            known[record['digest']] = (path, record)
    return known
