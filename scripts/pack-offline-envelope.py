"""Pack signed static release bytes into a deterministic .portalapp envelope."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
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


def build_envelope(descriptor_path, signature_path, frontend_path, output, validator=None):
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
    if manifest.get('backend') is not None:
        raise ValueError('managed offline envelopes require a verified image payload')
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--descriptor', type=Path, required=True)
    parser.add_argument('--signature', type=Path, required=True)
    parser.add_argument('--frontend', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(build_envelope(
            args.descriptor, args.signature, args.frontend, args.output))
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as err:
        parser.exit(1, 'Offline envelope failed: ' + str(err) + '\n')
