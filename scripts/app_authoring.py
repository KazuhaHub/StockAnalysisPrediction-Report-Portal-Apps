"""Shared offline checks for application authoring tools, not admission authority."""
import ipaddress
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit


def parent_origin(value):
    if not isinstance(value, str) or not value or not value.isascii():
        raise ValueError('A canonical trusted parent origin is required')
    try:
        url = urlsplit(value)
        port = url.port
        host = url.hostname
    except ValueError:
        raise ValueError('Invalid parent origin') from None
    if (url.scheme not in {'https', 'http'} or not host or url.username is not None or
            url.password is not None or url.path or url.query or url.fragment or
            value != url.scheme + '://' + url.netloc or url.netloc != url.netloc.lower() or
            '\\' in value or any(ord(char) <= 32 or ord(char) == 127 for char in value)):
        raise ValueError('Invalid parent origin')
    try:
        address = ipaddress.ip_address(host)
        valid_host = str(address) == host and '%' not in host
    except ValueError:
        valid_host = not re.fullmatch(r'(?:[0-9]+|0x[0-9a-f]+)', host.split('.')[-1]) and len(host)<=253 and all(len(label)<=63 for label in host.split('.')) and bool(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*', host))
    if (not valid_host or (port is not None and not 1 <= port <= 65535) or
            port == (443 if url.scheme == 'https' else 80) or
            (url.scheme == 'http' and host not in {'localhost', '127.0.0.1', '::1'})):
        raise ValueError('Use HTTPS or an explicit loopback HTTP parent origin')
    expected_host = '[' + host + ']' if ':' in host else host
    if url.netloc != expected_host + (':' + str(port) if port is not None else ''):
        raise ValueError('Parent origin must be canonical')
    return value


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


def bootstrap(frontend):
    value = read_json(frontend / 'src/bootstrap.json', 2048)
    if not isinstance(value, dict) or set(value) != {'parentOrigin'}:
        raise ValueError('Invalid immutable origin bootstrap')
    return parent_origin(value['parentOrigin'])


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
