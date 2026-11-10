"""Pack signed static release bytes into a deterministic .portalapp envelope."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


authoring = module('offline_authoring', 'app_authoring.py')
builder = module('offline_builder', 'build-app-v2.py')
oci = sys.modules.get('oci_image') or module('oci_image', 'oci_image.py')
sys.modules.setdefault('oci_image', oci)


def read_regular(path, limit):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('release input must be a regular file')
    info = path.stat()
    if info.st_size > limit:
        raise ValueError('release input exceeds its bound')
    with path.open('rb') as source:
        raw = source.read(limit + 1)
    if len(raw) != info.st_size or len(raw) > limit:
        raise ValueError('release input changed while reading')
    return raw


def build_envelope(descriptor_path, signature_path, frontend_path, output, validator=None,
                   image_blobs=None):
    descriptor = read_regular(descriptor_path, 131072)
    signature = read_regular(signature_path, 4096)
    frontend = read_regular(frontend_path, 16 << 20)
    (validator or builder.validate_descriptor)(descriptor)
    try:
        manifest = json.loads(
            descriptor.decode('utf-8'), object_pairs_hook=authoring.unique_object)
    except (UnicodeDecodeError, ValueError):
        raise ValueError('signed descriptor is not canonical UTF-8 JSON') from None
    if not isinstance(manifest, dict) or manifest.get('format') != 'portal.app/v2':
        raise ValueError('signed descriptor has the wrong format')
    backend = manifest.get('backend')
    images = None
    if backend is not None:
        if not isinstance(backend, dict) or not backend.get('images'):
            raise ValueError('managed offline envelopes require a verified image payload')
        if image_blobs is None:
            raise ValueError('a managed descriptor needs --image-blobs from export-image-oci.py')
        try:
            oci.validate_backend_images(backend)
            images = oci.collect_blobs(backend['images'], image_blobs)
        except oci.ImageError as err:
            raise ValueError('managed image payload refused: ' + str(err)) from None
    elif image_blobs is not None:
        raise ValueError('image blobs were given for a descriptor without a managed backend')
    declared = manifest.get('frontend')
    if not isinstance(declared, dict):
        raise ValueError('signed descriptor has no frontend declaration')
    digest = hashlib.sha256(frontend).hexdigest()
    if declared.get('sha256') != digest:
        raise ValueError('frontend digest does not match the signed descriptor')
    artifact = declared.get('artifact')
    if not isinstance(artifact, str) or not artifact:
        raise ValueError('frontend artifact name is invalid')
    name = Path(artifact).name
    if name in {'', '.', '..'} or name != artifact:
        raise ValueError('frontend artifact must have a plain file name')
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('output already exists; .portalapp files are never replaced')
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError('output parent must be an existing real directory')
    entries = [
        ('descriptor.json', descriptor),
        ('descriptor.sig', signature),
        ('blobs/' + digest + '/' + name, frontend),
    ]
    if images is not None:
        return write_managed_envelope(entries, images, output)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                dir=output.parent, prefix='.portalapp-', delete=False) as file:
            temporary = Path(file.name)
            with zipfile.ZipFile(
                    file, 'w', compression=zipfile.ZIP_DEFLATED,
                    compresslevel=9) as archive:
                for member, raw in entries:
                    info = zipfile.ZipInfo(
                        member, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, raw, compresslevel=9)
        if temporary.stat().st_size > 131072 + 4096 + (16 << 20) + (1 << 20):
            raise ValueError('offline envelope exceeds its total bound')
        os.chmod(temporary, 0o644)
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return output


def write_managed_envelope(entries, images, output):
    """Version 2: the version 1 members plus one stored flat blobs/<sha256> member per image blob."""
    if 3 + len(images) > oci.MAX_PACKAGE_ENTRIES:
        raise ValueError('offline envelope has too many entries')
    members = sorted(images)
    total = sum(len(raw) for _, raw in entries) + sum(images[d][1]['size'] for d in members)
    if total > oci.MAX_PACKAGE_BYTES:
        raise ValueError('offline envelope exceeds its total bound')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                dir=output.parent, prefix='.portalapp-', delete=False) as file:
            temporary = Path(file.name)
            with zipfile.ZipFile(file, 'w', compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=9) as archive:
                for member, raw in entries:
                    info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, raw, compresslevel=9)
                for digest in members:
                    path, record = images[digest]
                    info = zipfile.ZipInfo('blobs/' + digest, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    info.compress_type = zipfile.ZIP_STORED
                    info.file_size = record['size']
                    with path.open('rb') as source, archive.open(
                            info, 'w', force_zip64=record['size'] >= 1 << 30) as target:
                        for chunk in iter(lambda: source.read(oci.CHUNK), b''):
                            target.write(chunk)
        if temporary.stat().st_size > oci.MAX_PACKAGE_BYTES:
            raise ValueError('offline envelope exceeds its total bound')
        os.chmod(temporary, 0o644)
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--descriptor', type=Path, required=True)
    parser.add_argument('--signature', type=Path, required=True)
    parser.add_argument('--frontend', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image-blobs', type=Path,
                        help='blobs/ directory written by export-image-oci.py (managed descriptors)')
    args = parser.parse_args()
    try:
        print(build_envelope(
            args.descriptor, args.signature, args.frontend, args.output,
            image_blobs=args.image_blobs))
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as err:
        parser.exit(1, 'Offline envelope failed: ' + str(err) + '\n')
