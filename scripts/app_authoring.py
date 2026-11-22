"""Shared offline checks for application authoring tools, not admission authority."""
import json
import re
import unicodedata
from pathlib import Path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def read_json(path, limit=131072):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Missing, unsafe or oversized authoring file: ' + path.name)
    with path.open('rb') as source:
        raw=source.read(limit+1)
    if len(raw)>limit:
        raise ValueError('Oversized authoring file')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object)


def refuse_baked_origin(frontend):
    # The bridge client derives the parent origin from its own document URL; a build-time origin
    # file is stale configuration that would only mislead, so a leftover one is refused.
    if (frontend / 'src/bootstrap.json').exists() or (frontend / 'src/bootstrap.json').is_symlink():
        raise ValueError('Remove frontend/src/bootstrap.json: the parent origin is derived at run time, not baked in')


def app_folder(root, app_id):
    if not isinstance(app_id, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', app_id):
        raise ValueError('Invalid application identifier')
    app = root / 'apps' / app_id
    if (root / 'apps').is_symlink() or app.is_symlink() or not app.resolve().is_relative_to((root / 'apps').resolve()):
        raise ValueError('Unsafe application directory')
    return app


def display_name(value):
    schema=Path(__file__).resolve().parents[1]/'packages/app-sdk/schema/descriptor-v2.schema.json'
    maximum=json.loads(schema.read_text())['$defs']['AppDisplayText']['properties']['name']['maxLength']
    if (not isinstance(value,str) or not value.strip() or value.strip()!=value or len(value)>maximum or
            any(unicodedata.category(char) in {'Cc','Cf','Cs'} or char=='\ufffd' for char in value)):
        raise ValueError('Use a nonblank display name without surrounding whitespace or control characters')
    return value
