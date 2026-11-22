import base64
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import zlib

ROOT = Path(__file__).parents[2]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def chunk(kind, data):
    body = kind + data
    return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body))


def make_png(width=64, height=64, color_type=6, extra=b''):
    """A real RGBA (or RGB when color_type is 2) PNG filled with one colour."""
    channels = 4 if color_type == 6 else 3
    row = b'\x00' + bytes([20, 120, 220, 255][:channels]) * width
    ihdr = struct.pack('>IIBBBBB', width, height, 8, color_type, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) +
            chunk(b'IDAT', zlib.compress(row * height)) + extra + chunk(b'IEND', b''))


def raw_png(width, height, depth, color, data, interlace=0, palette=False):
    ihdr = struct.pack('>IIBBBBB', width, height, depth, color, 0, 0, interlace)
    mid = chunk(b'PLTE', b'\x00\x00\x00' * 2) if palette else b''
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + mid +
            chunk(b'IDAT', zlib.compress(data)) + chunk(b'IEND', b''))


def adam7_length(size, bits_per_pixel):
    total = 0
    for xs, ys, dx, dy in ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)):
        if size > xs and size > ys:
            width, rows = (size - xs + dx - 1) // dx, (size - ys + dy - 1) // dy
            total += rows * (1 + (width * bits_per_pixel + 7) // 8)
    return total


class IconValidationTests(unittest.TestCase):
    def setUp(self):
        self.authoring = module('icon_authoring', 'app_authoring.py')

    def check(self, raw):
        return self.authoring.validate_icon_png(raw)

    def test_accepts_square_icons_in_range(self):
        for size in (64, 128, 256):
            self.assertEqual(self.check(make_png(size, size)), (size, size))
        self.assertEqual(self.check(make_png(64, 64, color_type=2)), (64, 64))

    def test_refuses_wrong_signature_and_formats(self):
        for raw in (b'GIF89a' + b'\x00' * 40, b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'', b'\x89PNG'):
            with self.assertRaises(ValueError):
                self.check(raw)

    def test_refuses_bad_dimensions(self):
        for size in ((300, 300), (63, 63), (64, 65), (257, 257)):
            with self.assertRaises(ValueError, msg=str(size)):
                self.check(make_png(*size))

    def test_refuses_oversize(self):
        raw = make_png(64, 64)
        padded = raw[:-12] + chunk(b'tEXt', b'k\x00' + b'x' * (16 * 1024)) + raw[-12:]
        with self.assertRaises(ValueError):
            self.check(padded)

    def test_refuses_corrupt_header_crc_or_undecodable_pixels(self):
        raw = bytearray(make_png(64, 64))
        raw[29] ^= 0xFF  # IHDR CRC
        with self.assertRaises(ValueError):
            self.check(bytes(raw))
        ihdr = struct.pack('>IIBBBBB', 64, 64, 8, 6, 0, 0, 0)
        bad = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) +
               chunk(b'IDAT', b'not a zlib stream') + chunk(b'IEND', b''))
        with self.assertRaises(ValueError):
            self.check(bad)

    def test_refuses_pixel_data_of_the_wrong_length(self):
        ihdr = struct.pack('>IIBBBBB', 64, 64, 8, 6, 0, 0, 0)
        short = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) +
                 chunk(b'IDAT', zlib.compress(b'\x00' * 100)) + chunk(b'IEND', b''))
        with self.assertRaises(ValueError):
            self.check(short)


    def test_refuses_invalid_colour_type_and_depth_pairs(self):
        rows = b'\x00' * 64 * (1 + 64 * 3 // 2)
        with self.assertRaises(ValueError):
            self.check(raw_png(64, 64, 4, 2, rows))
        with self.assertRaises(ValueError):
            self.check(raw_png(64, 64, 16, 3, b'\x00' * 64 * 129, palette=True))
        self.assertEqual(self.check(raw_png(64, 64, 8, 0, (b'\x00' + b'\x80' * 64) * 64)), (64, 64))

    def test_palette_images_need_a_palette(self):
        data = (b'\x00' + b'\x00' * 64) * 64
        with self.assertRaises(ValueError):
            self.check(raw_png(64, 64, 8, 3, data))
        self.assertEqual(self.check(raw_png(64, 64, 8, 3, data, palette=True)), (64, 64))

    def test_interlaced_images_are_checked_against_the_adam7_length(self):
        for size in (64, 65 + 0, 100):
            if size < 64:
                continue
            need = adam7_length(size, 32)
            self.assertEqual(self.check(raw_png(size, size, 8, 6, b'\x00' * need, interlace=1)), (size, size))
            with self.assertRaises(ValueError):
                self.check(raw_png(size, size, 8, 6, b'\x00' * (need - 1), interlace=1))
            with self.assertRaises(ValueError):
                self.check(raw_png(size, size, 8, 6, b'\x00' * (need + 1), interlace=1))


class StrictBase64Tests(unittest.TestCase):
    def setUp(self):
        self.authoring = module('b64_authoring', 'app_authoring.py')

    def test_round_trips_canonical_text_only(self):
        self.assertEqual(self.authoring.decode_icon_base64('QQ=='), b'A')
        for bad in ('QR==', 'QQ=', 'QQ', 'QQ==\n', 'QQ==  ', '', 'Q-==', 'data:image/png;base64,QQ==', 'A' * 21852, None, 5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.authoring.decode_icon_base64(bad)


class IconCommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shutil.copytree(ROOT / 'templates', self.root / 'templates')
        creator = module('icon_creator', 'create-app.py')
        creator.ROOT = self.root
        creator.create('example-app', 'Example app', template='v2')
        self.app = self.root / 'apps/example-app'
        self.manifest = self.app / 'app.v2.json'
        self.tool = module('app_icon', 'app-icon.py')
        self.png = self.root / 'icon.png'

    def declaration(self):
        return json.loads(self.manifest.read_text())

    def test_writes_strict_base64_into_display_and_keeps_the_rest(self):
        before = self.declaration()
        self.png.write_bytes(make_png(128, 128))
        self.tool.apply(self.png, self.app)
        after = self.declaration()
        encoded = after['presentation']['display'].pop('icon_png')
        self.assertEqual(base64.b64decode(encoded, validate=True), self.png.read_bytes())
        self.assertEqual(after, before)
        self.assertTrue(self.manifest.read_text().endswith('\n'))

    def test_replaces_an_existing_icon_and_is_idempotent(self):
        self.png.write_bytes(make_png(64, 64))
        self.tool.apply(self.png, self.app)
        first = self.manifest.read_bytes()
        self.tool.apply(self.png, self.app)
        self.assertEqual(self.manifest.read_bytes(), first)
        self.png.write_bytes(make_png(256, 256))
        self.tool.apply(self.png, self.app)
        self.assertNotEqual(self.manifest.read_bytes(), first)

    def test_a_refused_icon_leaves_the_descriptor_untouched(self):
        original = self.manifest.read_bytes()
        self.png.write_bytes(make_png(300, 300))
        with self.assertRaises(ValueError):
            self.tool.apply(self.png, self.app)
        self.assertEqual(self.manifest.read_bytes(), original)

    def test_refuses_a_missing_png_a_legacy_app_and_a_descriptor_without_display(self):
        with self.assertRaises(ValueError):
            self.tool.apply(self.root / 'missing.png', self.app)
        self.png.write_bytes(make_png())
        data = self.declaration()
        del data['presentation']['display']
        self.manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.tool.apply(self.png, self.app)
        self.manifest.unlink()
        with self.assertRaises(ValueError):
            self.tool.apply(self.png, self.app)

    def test_original_file_mode_is_preserved(self):
        self.manifest.chmod(0o640)
        self.png.write_bytes(make_png())
        self.tool.apply(self.png, self.app)
        self.assertEqual(self.manifest.stat().st_mode & 0o777, 0o640)

    def test_non_object_presentation_or_display_is_a_clean_error(self):
        self.png.write_bytes(make_png())
        standard = module('shape_standard', 'plugin-standard.py')
        pristine = self.manifest.read_text()
        for key, value in (('presentation', None), ('presentation', []), ('display', []), ('display', 'x')):
            self.manifest.write_text(pristine)
            data = self.declaration()
            if key == 'presentation':
                data['presentation'] = value
            else:
                data['presentation']['display'] = value
            self.manifest.write_text(json.dumps(data))
            with self.assertRaises(ValueError, msg=repr((key, value))):
                self.tool.apply(self.png, self.app)
            with self.assertRaises(ValueError, msg=repr((key, value))):
                standard.check(self.root)

    def test_plugin_standard_refuses_non_strict_base64(self):
        standard = module('b64_standard', 'plugin-standard.py')
        data = self.declaration()
        encoded = base64.b64encode(make_png(64, 64)).decode()  # 209 bytes: one pad char
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
        pad = len(encoded) - len(encoded.rstrip('='))
        at = len(encoded) - pad - 1
        dirty = encoded[:at] + alphabet[(alphabet.index(encoded[at]) + 1) % 64] + encoded[at + 1:]
        data['presentation']['display']['icon_png'] = dirty
        self.manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            standard.check(self.root)

    def test_plugin_standard_accepts_new_fields_and_refuses_a_bad_icon(self):
        standard = module('icon_standard', 'plugin-standard.py')
        self.png.write_bytes(make_png(64, 64))
        self.tool.apply(self.png, self.app)
        data = self.declaration()
        data['publisher_name'] = 'Kazuha Hub'
        self.manifest.write_text(json.dumps(data))
        self.assertTrue(standard.check(self.root))
        data['presentation']['display']['icon_png'] = base64.b64encode(make_png(300, 300)).decode()
        self.manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            standard.check(self.root)


if __name__ == '__main__':
    unittest.main()
