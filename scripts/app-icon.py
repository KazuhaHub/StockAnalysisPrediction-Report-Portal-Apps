"""Embed a PNG as an application's custom icon (display.icon_png in app.v2.json).

Usage: python3 scripts/app-icon.py ICON.png apps/APP_ID

The PNG must be square, 64-256 px and at most 16 KiB. The tool validates it, then
writes it as strict standard base64 under presentation.display.icon_png. The shared
`display.icon` name stays as the fallback. Deploy order: the Portal and the app-runner
must both be upgraded before a package that uses this field is published.
"""
import argparse
import base64
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("app_authoring", Path(__file__).with_name("app_authoring.py"))
authoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(authoring)


def apply(png_path, app_dir):
    png_path, app_dir = Path(png_path), Path(app_dir)
    if png_path.is_symlink() or not png_path.is_file():
        raise ValueError('The icon file is missing or unsafe')
    with png_path.open('rb') as source:
        raw = source.read(authoring.MAX_ICON_PNG_BYTES + 1)
    authoring.validate_icon_png(raw)
    if (app_dir / 'app.json').exists():
        raise ValueError('Custom icons require a v2 application, not a legacy one')
    manifest = app_dir / 'app.v2.json'
    declaration = authoring.read_json(manifest)
    display = declaration.get('presentation', {}).get('display') if isinstance(declaration, dict) else None
    if not isinstance(display, dict):
        raise ValueError('Add presentation.display (icon and texts) before embedding a custom icon')
    display['icon_png'] = base64.b64encode(raw).decode('ascii')
    text = json.dumps(declaration, ensure_ascii=False, indent=2) + '\n'
    handle, temporary = tempfile.mkstemp(dir=app_dir, prefix='.app.v2.', suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as target:
            target.write(text)
        os.replace(temporary, manifest)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('png', type=Path)
    parser.add_argument('app_dir', type=Path)
    args = parser.parse_args()
    try:
        path = apply(args.png, args.app_dir)
    except (ValueError, OSError) as error:
        sys.exit(f'app-icon: {error}')
    print(f'Embedded icon in {path}')
