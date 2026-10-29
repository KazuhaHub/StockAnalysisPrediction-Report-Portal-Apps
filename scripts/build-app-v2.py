"""Build an unsigned local v2 frontend candidate; never publish, sign or enroll."""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
import re

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('app_authoring', Path(__file__).with_name('app_authoring.py'))
authoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(authoring)
# Conservative authoring bounds, not a replacement for current host admission.
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 200, 4 << 20, 10 << 20


def validate_descriptor(raw):
    with tempfile.TemporaryDirectory(prefix='portal-v2-preflight-') as folder:
        path = Path(folder) / 'descriptor.json'
        path.write_bytes(raw)
        subprocess.run(['node', str(ROOT / 'scripts/validate-descriptor-v2.mjs'), str(path)], cwd=ROOT, check=True)


def package_frontend(app_id, output, root=ROOT, validator=validate_descriptor):
    app = authoring.app_folder(root, app_id)
    if (app / 'app.json').exists():
        raise ValueError('The v2 builder cannot accept a legacy or dual-format application')
    frontend = app / 'frontend'
    authoring.bootstrap(frontend)
    manifest_path = app / 'app.v2.json'
    declaration = authoring.read_json(manifest_path)
    validator(manifest_path.read_bytes())
    if declaration.get('id') != app_id or declaration.get('format') != 'portal.app/v2':
        raise ValueError('Application identity or descriptor format mismatch')
    if declaration.get('frontend', {}).get('artifact') != 'frontend.zip':
        raise ValueError('This authoring builder requires the frontend.zip artifact name')
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Candidate output already exists; choose a new output directory')
    dist = frontend / 'dist'
    if frontend.is_symlink() or dist.is_symlink() or not dist.is_dir():
        raise ValueError('Compiled frontend is missing or unsafe')
    files = []
    total = 0
    for path in sorted(dist.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlinked build members are refused')
        if path.is_dir():
            continue
        name = path.relative_to(dist).as_posix()
        if (not path.is_file() or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._/-]{0,255}', name) or
                any(part in {'.', '..'} for part in name.split('/'))):
            raise ValueError('Unsafe build member name')
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or len(files) >= MAX_FILES:
            raise ValueError('Compiled frontend exceeds authoring bounds')
        with path.open('rb') as source:
            raw=source.read(MAX_FILE_BYTES+1)
        if len(raw) != size:
            raise ValueError('Compiled frontend changed while packaging')
        files.append((name, raw))
    if declaration['presentation']['entry'] not in {name for name, _ in files}:
        raise ValueError('Declared entry document is absent from the compiled frontend')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw, compresslevel=9)
    archive_raw = buffer.getvalue()
    if len(archive_raw) > MAX_TOTAL_BYTES:
        raise ValueError('Frontend archive exceeds authoring bounds')
    declaration['frontend']['sha256'] = hashlib.sha256(archive_raw).hexdigest()
    descriptor_raw = (json.dumps(declaration, ensure_ascii=False, indent=2) + '\n').encode()
    validator(descriptor_raw)
    output.mkdir(parents=True, exist_ok=False)
    try:
        (output / 'frontend.zip').write_bytes(archive_raw)
        (output / 'descriptor.json').write_bytes(descriptor_raw)
    except BaseException:
        shutil.rmtree(output)
        raise
    return output


def build(app_id, output=None, root=ROOT):
    app = authoring.app_folder(root, app_id)
    if (app/'app.json').exists():
        raise ValueError('The v2 builder cannot accept legacy or dual-format declarations')
    if (app/'frontend').is_symlink():
        raise ValueError('Unsafe frontend build directory')
    authoring.bootstrap(app / 'frontend')
    # Refuse bad declarations before invoking the application build script.
    authoring.read_json(app / 'app.v2.json')
    validate_descriptor((app / 'app.v2.json').read_bytes())
    if (app / 'frontend').is_symlink() or (app / 'frontend/dist').is_symlink():
        raise ValueError('Unsafe frontend build directory')
    destination = Path(output) if output is not None else app / '.development' / 'candidate'
    if destination.exists() or destination.is_symlink():
        raise ValueError('Candidate output already exists; choose a new --output directory')
    subprocess.run(['npm', 'run', 'build'], cwd=app / 'frontend', check=True)
    shutil.copyfile(app / 'frontend/src/index.html', app / 'frontend/dist/index.html')
    return package_frontend(app_id, destination, root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app_id')
    parser.add_argument('--output', type=Path, help='New local output directory; existing outputs are never replaced')
    args = parser.parse_args()
    print('Unsigned development candidate: ' + str(build(args.app_id, args.output)))
