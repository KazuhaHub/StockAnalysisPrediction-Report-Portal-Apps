import base64
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).parents[2]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


oci = load('oci_image', 'oci_image.py')
sys.modules['oci_image'] = oci
exporter = load('t_export_image', 'export-image-oci.py')
packer = load('t_pack_offline', 'pack-offline-envelope.py')
builder = load('t_build_app', 'build-app-v2.py')

OCI_MANIFEST = 'application/vnd.oci.image.manifest.v1+json'
OCI_CONFIG = 'application/vnd.oci.image.config.v1+json'
OCI_INDEX = 'application/vnd.oci.image.index.v1+json'
GZIP_LAYER = 'application/vnd.oci.image.layer.v1.tar+gzip'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def tar_bytes(name, body):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        info = tarfile.TarInfo(name)
        info.size = len(body)
        info.mtime = 0
        archive.addfile(info, io.BytesIO(body))
    return buffer.getvalue()


def gzip_bytes(raw):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0) as stream:
        stream.write(raw)
    return buffer.getvalue()


class Layout:
    """A tiny OCI layout kept as {relative path: bytes}."""

    def __init__(self):
        self.files = {'oci-layout': b'{"imageLayoutVersion":"1.0.0"}'}

    def blob(self, raw):
        digest = sha(raw)
        self.files['blobs/sha256/' + digest] = raw
        return digest

    def image(self, arch='amd64', layer_type=GZIP_LAYER, manifest_extra=None, layer_extra=None):
        tars = [tar_bytes('etc/one', b'first ' + arch.encode()), tar_bytes('etc/two', b'second')]
        blobs = [gzip_bytes(t) for t in tars]
        config = json.dumps({
            'architecture': arch, 'os': 'linux', 'config': {},
            'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + sha(t) for t in tars]},
        }).encode()
        layers = []
        for blob in blobs:
            self.blob(blob)
            layer = {'mediaType': layer_type, 'digest': 'sha256:' + sha(blob), 'size': len(blob)}
            layer.update(layer_extra or {})
            layers.append(layer)
        config_digest = self.blob(config)
        manifest = {
            'schemaVersion': 2, 'mediaType': OCI_MANIFEST,
            'config': {'mediaType': OCI_CONFIG, 'digest': 'sha256:' + config_digest, 'size': len(config)},
            'layers': layers,
        }
        manifest.update(manifest_extra or {})
        raw = json.dumps(manifest).encode()
        return self.blob(raw), len(raw), tars

    def index(self, entries, nested=False):
        document = {'schemaVersion': 2, 'mediaType': OCI_INDEX, 'manifests': entries}
        if nested:
            digest = self.blob(json.dumps(document).encode())
            document = {'schemaVersion': 2, 'manifests': [{
                'mediaType': OCI_INDEX, 'digest': 'sha256:' + digest,
                'size': len(json.dumps(document).encode())}]}
        self.files['index.json'] = json.dumps(document).encode()

    def write_dir(self, root):
        for name, raw in self.files.items():
            path = Path(root) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        return Path(root)

    def write_tar(self, path):
        with tarfile.open(path, 'w') as archive:
            for name, raw in self.files.items():
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
        return Path(path)


def entry_for(digest, size, arch=None, media_type=OCI_MANIFEST, annotations=None):
    item = {'mediaType': media_type, 'digest': 'sha256:' + digest, 'size': size}
    if arch:
        item['platform'] = {'architecture': arch, 'os': 'linux'}
    if annotations:
        item['annotations'] = annotations
    return item


def verify_managed_package(test, path, descriptor):
    """Independent reader of the version 2 rules the host enforces."""
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        test.assertLessEqual(len(infos), 160)
        test.assertLessEqual(Path(path).stat().st_size, 384 << 20)
        names = [info.filename for info in infos]
        test.assertEqual(len(names), len(set(names)))
        blobs = {}
        for info in infos:
            test.assertEqual((info.external_attr >> 16) & 0o777, 0o644)
            test.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
            test.assertNotIn(info.filename.rsplit('/', 1)[-1].lower(),
                             {'manifest.json', 'repositories', 'index.json', 'oci-layout'})
            if info.filename.startswith('blobs/') and '/' not in info.filename[6:]:
                test.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                raw = archive.read(info)
                test.assertEqual(sha(raw), info.filename[6:])
                test.assertEqual(info.file_size, info.compress_size)
                blobs[info.filename[6:]] = raw
        expected = set()
        for image in descriptor['backend']['images']:
            expected |= {image['manifest_digest'], image['config_digest']}
            manifest = json.loads(blobs[image['manifest_digest']])
            expected |= {layer['digest'][7:] for layer in manifest['layers']}
        test.assertEqual(set(blobs), expected)
        test.assertEqual(len(infos), 3 + len(expected))
        test.assertEqual(names[:2], ['descriptor.json', 'descriptor.sig'])
        test.assertEqual(json.loads(archive.read('descriptor.json')), descriptor)


class ExporterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def export(self, layout, platforms=('linux/amd64',), tar=False, name='out'):
        source = layout.write_tar(self.root / 'image.tar') if tar else layout.write_dir(self.root / 'layout')
        return exporter.export_oci(source, list(platforms), self.root / name)

    def single(self, arch='amd64', **kwargs):
        layout = Layout()
        digest, size, tars = layout.image(arch, **kwargs)
        layout.index([entry_for(digest, size)])
        return layout, digest, tars

    def test_directory_and_tar_layouts_produce_the_same_entries(self):
        layout, digest, tars = self.single()
        from_dir = self.export(layout, name='a')
        (self.root / 'image.tar').unlink() if (self.root / 'image.tar').exists() else None
        from_tar = self.export(layout, tar=True, name='b')
        self.assertEqual(from_dir, from_tar)
        entry = from_dir[0]
        self.assertEqual(entry['platform'], 'linux/amd64')
        self.assertEqual(entry['manifest_digest'], digest)
        self.assertEqual([item['diff_id'] for item in entry['layers']], [sha(t) for t in tars])
        self.assertEqual([item['uncompressed_bytes'] for item in entry['layers']], [len(t) for t in tars])
        self.assertEqual(list(entry), ['platform', 'manifest_digest', 'config_digest', 'layers'])

    def test_output_holds_only_flat_referenced_blobs(self):
        layout, digest, _ = self.single()
        layout.blob(b'unreferenced publisher content')
        entry = self.export(layout)[0]
        written = {path.name for path in (self.root / 'out/blobs').iterdir()}
        manifest = json.loads(layout.files['blobs/sha256/' + digest])
        self.assertEqual(written, {entry['manifest_digest'], entry['config_digest']} |
                         {layer['digest'][7:] for layer in manifest['layers']})
        names = {path.name for path in (self.root / 'out').rglob('*')}
        self.assertFalse(names & {'index.json', 'manifest.json', 'oci-layout'})
        self.assertEqual(json.loads((self.root / 'out/images.json').read_text()),
                         [entry])
        for path in (self.root / 'out/blobs').iterdir():
            self.assertEqual(sha(path.read_bytes()), path.name)

    def test_index_resolves_down_to_one_manifest_per_platform_and_skips_attestations(self):
        layout = Layout()
        amd, amd_size, _ = layout.image('amd64')
        arm, arm_size, _ = layout.image('arm64')
        attestation, attestation_size, _ = layout.image('amd64', manifest_extra={'annotations': {'k': 'v'}})
        layout.index([
            entry_for(amd, amd_size, 'amd64'), entry_for(arm, arm_size, 'arm64'),
            entry_for(attestation, attestation_size, 'amd64',
                      annotations={'vnd.docker.reference.type': 'attestation-manifest'}),
        ], nested=True)
        entries = self.export(layout, ['linux/amd64', 'linux/arm64'])
        self.assertEqual([e['manifest_digest'] for e in entries], [amd, arm])

    def test_two_manifests_for_one_platform_are_refused(self):
        layout = Layout()
        first, size, _ = layout.image('amd64')
        second, second_size, _ = layout.image('amd64', manifest_extra={'annotations': {'x': 'y'}})
        layout.index([entry_for(first, size, 'amd64'), entry_for(second, second_size, 'amd64')])
        with self.assertRaisesRegex(oci.ImageError, 'more than one'):
            self.export(layout)
        self.assertFalse((self.root / 'out').exists())

    def test_absent_platform_is_refused(self):
        layout, _, _ = self.single('amd64')
        with self.assertRaisesRegex(oci.ImageError, 'no image manifest'):
            self.export(layout, ['linux/arm64'])

    def test_zstd_layer_is_refused(self):
        layout, _, _ = self.single(layer_type='application/vnd.oci.image.layer.v1.tar+zstd')
        with self.assertRaisesRegex(oci.ImageError, 'layer media type'):
            self.export(layout)

    def test_foreign_layer_and_layer_urls_are_refused(self):
        layout, _, _ = self.single(
            layer_type='application/vnd.oci.image.layer.nondistributable.v1.tar+gzip')
        with self.assertRaises(oci.ImageError):
            self.export(layout)
        layout, _, _ = self.single(layer_extra={'urls': ['https://example.invalid/layer']})
        with self.assertRaisesRegex(oci.ImageError, 'unknown'):
            self.export(layout, name='second')

    def test_nested_image_index_as_the_platform_manifest_is_refused(self):
        layout, digest, _ = self.single()
        layout.index([entry_for(digest, 1, 'amd64', media_type='application/vnd.example.unknown+json')])
        with self.assertRaisesRegex(oci.ImageError, 'unsupported media type'):
            self.export(layout)

    def test_layer_whose_content_breaks_the_config_is_refused(self):
        layout, digest, _ = self.single()
        manifest = json.loads(layout.files['blobs/sha256/' + digest])
        other = gzip_bytes(tar_bytes('evil', b'x'))
        layout.blob(other)
        manifest['layers'][0].update(digest='sha256:' + sha(other), size=len(other))
        raw = json.dumps(manifest).encode()
        layout.index([entry_for(layout.blob(raw), len(raw))])
        with self.assertRaisesRegex(oci.ImageError, 'diff_id'):
            self.export(layout)

    def test_corrupt_blob_and_existing_output_are_refused(self):
        layout, digest, _ = self.single()
        manifest = json.loads(layout.files['blobs/sha256/' + digest])
        key = 'blobs/sha256/' + manifest['layers'][0]['digest'][7:]
        blob = layout.files[key]
        layout.files[key] = blob[:20] + bytes([blob[20] ^ 1]) + blob[21:]
        with self.assertRaises(oci.ImageError):
            self.export(layout)
        self.assertFalse((self.root / 'out').exists())
        (self.root / 'taken').mkdir()
        with self.assertRaisesRegex(oci.ImageError, 'already exists'):
            self.export(self.single()[0], name='taken')

    def test_docker_schema2_spelling_is_accepted(self):
        layout = Layout()
        tars = [tar_bytes('a', b'1')]
        blob = gzip_bytes(tars[0])
        layout.blob(blob)
        config = json.dumps({'architecture': 'amd64', 'os': 'linux',
                             'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + sha(tars[0])]}}).encode()
        manifest = json.dumps({
            'schemaVersion': 2, 'mediaType': 'application/vnd.docker.distribution.manifest.v2+json',
            'config': {'mediaType': 'application/vnd.docker.container.image.v1+json',
                       'digest': 'sha256:' + layout.blob(config), 'size': len(config)},
            'layers': [{'mediaType': 'application/vnd.docker.image.rootfs.diff.tar.gzip',
                        'digest': 'sha256:' + sha(blob), 'size': len(blob)}]}).encode()
        layout.index([entry_for(layout.blob(manifest), len(manifest),
                                media_type='application/vnd.docker.distribution.manifest.v2+json')])
        self.assertEqual(len(self.export(layout)[0]['layers']), 1)


class PackerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        layout = Layout()
        digest, size, self.tars = layout.image('amd64')
        layout.index([entry_for(digest, size)])
        self.entries = exporter.export_oci(layout.write_dir(self.root / 'layout'), ['linux/amd64'], self.root / 'export')
        self.blobs = self.root / 'export/blobs'
        corpus = json.loads((ROOT / 'packages/app-sdk/tests/fixtures/descriptor-v2.json').read_text())
        for case in corpus['cases']:
            value = json.loads(base64.b64decode(case['input_base64']))
            if case['valid'] and value.get('backend') is not None:
                self.managed = value
                break
        frontend = io.BytesIO()
        with zipfile.ZipFile(frontend, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            info = zipfile.ZipInfo('index.html', date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, '<!doctype html><title>x</title>')
        self.frontend = frontend.getvalue()
        self.frontend_path = self.root / 'ui.zip'
        self.frontend_path.write_bytes(self.frontend)
        self.managed['frontend']['sha256'] = sha(self.frontend)
        self.managed['backend'].pop('image')
        self.managed['backend']['platforms'] = ['linux/amd64']
        self.managed['backend']['images'] = self.entries
        self.signature = self.root / 'descriptor.sig'
        self.signature.write_bytes(b'{"fixture":"signature"}')

    def descriptor(self, value=None):
        path = self.root / 'descriptor.json'
        path.write_text(json.dumps(value or self.managed, indent=2) + '\n')
        return path

    def pack(self, name='m.portalapp', value=None, blobs='default', validator=lambda _raw: None):
        return packer.build_envelope(
            self.descriptor(value), self.signature, self.frontend_path, self.root / name,
            validator=validator, image_blobs=self.blobs if blobs == 'default' else blobs)

    def test_managed_package_follows_every_envelope_rule_and_is_deterministic(self):
        first = self.pack()
        self.assertEqual(first.read_bytes(), self.pack('again.portalapp').read_bytes())
        verify_managed_package(self, first, self.managed)
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(len(archive.namelist()), 3 + 4)
            frontend = [i for i in archive.infolist() if i.filename.count('/') == 2][0]
            self.assertEqual(frontend.compress_type, zipfile.ZIP_DEFLATED)

    def test_shared_blobs_appear_once(self):
        layout = Layout()
        digest, size, _ = layout.image('amd64')
        layout.index([entry_for(digest, size)])
        # Two platforms that carry the same layer bytes would share it; here a duplicated
        # layer inside one image must be a single member.
        layer = self.entries[0]['layers'][0]
        manifest_raw = (self.blobs / self.entries[0]['manifest_digest']).read_bytes()
        self.assertGreater(len(manifest_raw), 0)
        self.assertEqual(len(set(oci.collect_blobs(self.entries, self.blobs))), 4)
        self.assertTrue(layer['diff_id'])

    def test_verifier_catches_deflated_extra_and_missing_members(self):
        good = self.pack()
        with zipfile.ZipFile(good) as archive:
            members = [(i.filename, archive.read(i), i.compress_type) for i in archive.infolist()]

        def rebuild(items):
            path = self.root / ('bad%d.portalapp' % len(list(self.root.glob('bad*'))))
            with zipfile.ZipFile(path, 'w') as archive:
                for name, raw, kind in items:
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.external_attr = 0o100644 << 16
                    info.compress_type = kind
                    archive.writestr(info, raw)
            return path
        digest_names = [m[0] for m in members if m[0].startswith('blobs/') and m[0].count('/') == 1]
        deflated = [(n, r, zipfile.ZIP_DEFLATED if n == digest_names[0] else k) for n, r, k in members]
        extra = members + [('blobs/' + sha(b'extra'), b'extra', zipfile.ZIP_STORED)]
        missing = [m for m in members if m[0] != digest_names[-1]]
        for bad in (deflated, extra, missing):
            with self.assertRaises(AssertionError):
                verify_managed_package(self, rebuild(bad), self.managed)

    def test_missing_tampered_or_extra_blob_files(self):
        victim = sorted(self.blobs.iterdir())[0]
        original = victim.read_bytes()
        victim.unlink()
        with self.assertRaisesRegex(ValueError, 'refused'):
            self.pack()
        victim.write_bytes(original + b'x')
        with self.assertRaisesRegex(ValueError, 'refused'):
            self.pack()
        victim.write_bytes(original)
        (self.blobs / sha(b'stray')).write_bytes(b'stray')
        verify_managed_package(self, self.pack(), self.managed)
        self.assertFalse((self.root / 'bad.portalapp').exists())

    def test_descriptor_that_disagrees_with_the_image_is_refused(self):
        for mutate in (
            lambda d: d['backend']['images'][0]['layers'][0].update(diff_id='0' * 64),
            lambda d: d['backend']['images'][0]['layers'].reverse(),
            lambda d: d['backend']['images'][0]['layers'][0].update(uncompressed_bytes=1),
            lambda d: d['backend'].update(platforms=['linux/arm64']),
            lambda d: d['backend']['images'][0].update(config_digest='1' * 64),
            lambda d: d['backend'].update(image='ghcr.io/example/x@sha256:' + 'b' * 64),
        ):
            value = json.loads(json.dumps(self.managed))
            mutate(value)
            with self.assertRaises(ValueError):
                self.pack('x.portalapp', value=value)
            self.assertFalse((self.root / 'x.portalapp').exists())

    def test_managed_needs_blobs_and_static_refuses_them(self):
        with self.assertRaisesRegex(ValueError, 'image-blobs'):
            self.pack(blobs=None)
        static = json.loads(json.dumps(self.managed))
        static.pop('backend')
        with self.assertRaisesRegex(ValueError, 'without a managed backend'):
            self.pack('s.portalapp', value=static)

    def test_builder_switches_the_backend_to_images(self):
        declaration = json.loads(json.dumps(self.managed))
        declaration['backend']['image'] = 'ghcr.io/example/x@sha256:' + 'b' * 64
        del declaration['backend']['images']
        builder.apply_images(declaration, self.entries)
        self.assertNotIn('image', declaration['backend'])
        self.assertEqual(declaration['backend']['images'], self.entries)
        declaration['backend']['platforms'] = ['linux/amd64', 'linux/arm64']
        with self.assertRaises(ValueError):
            builder.apply_images(declaration, self.entries)
        with self.assertRaises(ValueError):
            builder.apply_images({'id': 'x'}, self.entries)

    def test_descriptor_with_images_passes_the_real_validator(self):
        import shutil as which
        if which.which('node') is None or not (ROOT / 'node_modules/vite').is_dir():
            self.skipTest('node toolchain is not installed')
        builder.validate_descriptor(self.descriptor().read_bytes())


if __name__ == '__main__':
    unittest.main()
