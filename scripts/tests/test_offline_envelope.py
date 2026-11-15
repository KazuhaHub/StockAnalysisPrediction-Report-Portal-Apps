import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location(
    'offline_envelope', ROOT / 'scripts/pack-offline-envelope.py')
offline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(offline)


class OfflineEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        corpus = json.loads(
            (ROOT / 'packages/app-sdk/tests/fixtures/descriptor-v2.json')
            .read_text())
        self.static = None
        self.managed = None
        for case in corpus['cases']:
            if not case['valid']:
                continue
            value = json.loads(base64.b64decode(case['input_base64']))
            if value.get('backend') is None and self.static is None:
                self.static = value
            if value.get('backend') is not None and self.managed is None:
                self.managed = value
        self.assertIsNotNone(self.static)
        self.assertIsNotNone(self.managed)
        self.frontend = self.frontend_zip()
        self.static['frontend']['sha256'] = hashlib.sha256(
            self.frontend).hexdigest()
        self.descriptor = self.write_json(
            'descriptor.json', self.static)
        self.signature = self.root / 'descriptor.sig'
        self.signature.write_bytes(b'{"fixture":"signature"}')
        self.frontend_path = self.root / 'ui.zip'
        self.frontend_path.write_bytes(self.frontend)

    def frontend_zip(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            info = zipfile.ZipInfo('index.html', date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = (0o100644) << 16
            archive.writestr(info, '<!doctype html><title>Offline</title>')
        return raw.getvalue()

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        return path

    def pack(self, name='sample.portalapp', validator=lambda _raw: None):
        return offline.build_envelope(
            self.descriptor, self.signature, self.frontend_path,
            self.root / name, validator=validator)

    def test_pack_is_deterministic_and_binds_declared_frontend(self):
        first = self.pack()
        second = self.pack('second.portalapp')
        self.assertEqual(first.read_bytes(), second.read_bytes())
        digest = hashlib.sha256(self.frontend).hexdigest()
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(archive.namelist(), [
                'descriptor.json', 'descriptor.sig',
                'blobs/' + digest + '/' + Path(
                    self.static['frontend']['artifact']).name,
            ])
            self.assertEqual(
                json.loads(archive.read('descriptor.json')), self.static)
            self.assertTrue(all(
                info.date_time == (1980, 1, 1, 0, 0, 0)
                for info in archive.infolist()))

    def test_changed_frontend_or_validator_failure_leaves_no_output(self):
        self.frontend_path.write_bytes(self.frontend + b'x')
        with self.assertRaises(ValueError):
            self.pack()
        self.assertFalse((self.root / 'sample.portalapp').exists())
        self.frontend_path.write_bytes(self.frontend)
        with self.assertRaises(ValueError):
            self.pack(validator=lambda _raw: (_ for _ in ()).throw(
                ValueError('descriptor refused')))
        self.assertFalse((self.root / 'sample.portalapp').exists())

    def test_managed_or_preexisting_package_is_refused(self):
        self.managed['frontend']['sha256'] = hashlib.sha256(
            self.frontend).hexdigest()
        managed = self.write_json('managed.json', self.managed)
        with self.assertRaisesRegex(ValueError, 'managed'):
            offline.build_envelope(
                managed, self.signature, self.frontend_path,
                self.root / 'managed.portalapp',
                validator=lambda _raw: None)
        self.assertFalse((self.root / 'managed.portalapp').exists())
        existing = self.root / 'existing.portalapp'
        existing.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.pack('existing.portalapp')
        self.assertEqual(existing.read_bytes(), b'keep')

    def test_symlinked_release_input_is_refused(self):
        linked = self.root / 'linked.json'
        linked.symlink_to(self.descriptor)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            offline.build_envelope(
                linked, self.signature, self.frontend_path,
                self.root / 'linked.portalapp',
                validator=lambda _raw: None)


if __name__ == '__main__':
    unittest.main()
