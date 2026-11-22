"""Shared offline checks for application authoring tools, not admission authority."""
import base64
import binascii
import json
import re
import struct
import unicodedata
import zlib
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


# Custom icon limits; they mirror the Portal's descriptor contract (display.icon_png).
MAX_ICON_PNG_BYTES = 16 * 1024
MIN_ICON_PIXELS, MAX_ICON_PIXELS = 64, 256
_PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
_PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
# Valid (colour type, bit depth) pairs from the PNG specification.
_PNG_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
MAX_ICON_BASE64 = (MAX_ICON_PNG_BYTES + 2) // 3 * 4
_MAX_INFLATED = 4 << 20


def validate_icon_png(raw):
    """Check PNG bytes against the icon contract and return (width, height).

    Authoring preflight only: it walks every chunk (CRC included), requires a square
    64-256 px image within the size cap and inflates the pixel data to confirm it decodes
    to the expected length. The Portal still decodes and re-encodes the icon on admission.
    """
    if not isinstance(raw, (bytes, bytearray)) or not raw.startswith(_PNG_SIGNATURE):
        raise ValueError('The icon is not a PNG file')
    if len(raw) > MAX_ICON_PNG_BYTES:
        raise ValueError(f'The icon is {len(raw)} bytes; the limit is {MAX_ICON_PNG_BYTES}')
    pos, header, idat, ended, palette = len(_PNG_SIGNATURE), None, bytearray(), False, False
    while pos < len(raw) and not ended:
        if pos + 12 > len(raw):
            raise ValueError('The PNG is truncated')
        length, kind = struct.unpack('>I4s', raw[pos:pos + 8])
        end = pos + 8 + length
        if end + 4 > len(raw):
            raise ValueError('The PNG is truncated')
        body = raw[pos + 4:end]
        if struct.unpack('>I', raw[end:end + 4])[0] != zlib.crc32(body):
            raise ValueError('The PNG has a corrupt chunk')
        if header is None:
            if kind != b'IHDR' or length != 13:
                raise ValueError('The PNG must start with an IHDR chunk')
            header = struct.unpack('>IIBBBBB', raw[pos + 8:end])
        elif kind == b'PLTE':
            palette = True
        elif kind == b'IDAT':
            idat += raw[pos + 8:end]
        elif kind == b'IEND':
            ended = True
        pos = end + 4
    if header is None or not ended or not idat:
        raise ValueError('The PNG is incomplete')
    width, height, depth, color, _compression, _filter, interlace = header
    if width != height or not MIN_ICON_PIXELS <= width <= MAX_ICON_PIXELS:
        raise ValueError(f'The icon is {width}x{height}; it must be square, {MIN_ICON_PIXELS}-{MAX_ICON_PIXELS} px')
    if depth not in _PNG_DEPTHS.get(color, ()) or interlace not in (0, 1):
        raise ValueError('Unsupported PNG colour type, bit depth or interlace method')
    if color == 3 and not palette:
        raise ValueError('A palette PNG needs a PLTE chunk')
    inflater = zlib.decompressobj()
    try:
        pixels = inflater.decompress(bytes(idat), _MAX_INFLATED)
    except zlib.error:
        raise ValueError('The PNG pixel data does not decode') from None
    if not inflater.eof:
        raise ValueError('The PNG pixel data is incomplete or oversized')
    bits = _PNG_CHANNELS[color] * depth
    if interlace == 0:
        expected = height * (1 + (width * bits + 7) // 8)
    else:
        expected = 0
        for x0, y0, dx, dy in _ADAM7:
            if width > x0 and height > y0:
                expected += ((height - y0 + dy - 1) // dy) * (1 + (((width - x0 + dx - 1) // dx) * bits + 7) // 8)
    if len(pixels) != expected:
        raise ValueError('The PNG pixel data has the wrong length')
    return width, height


def decode_icon_base64(text):
    """Strict standard base64 like Go's StdEncoding.Strict(): canonical, padded, no whitespace, capped."""
    if not isinstance(text, str) or not text or len(text) > MAX_ICON_BASE64 or len(text) % 4:
        raise ValueError('icon_png must be non-empty padded standard base64 within the size cap')
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('icon_png is not valid standard base64') from None
    # Re-encoding rejects non-zero padding bits and other non-canonical forms.
    if base64.b64encode(raw).decode('ascii') != text:
        raise ValueError('icon_png is not canonical base64 (non-zero padding bits)')
    return raw


def display_block(declaration):
    """Return presentation.display (or None), raising a clean error for a wrong shape."""
    if not isinstance(declaration, dict) or not isinstance(declaration.get('presentation'), dict):
        raise ValueError('presentation must be an object')
    display = declaration['presentation'].get('display')
    if display is not None and not isinstance(display, dict):
        raise ValueError('presentation.display must be an object')
    return display
