import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).parents[2]

def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

class V2AuthoringTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shutil.copytree(ROOT / 'templates', self.root / 'templates')
        self.creator = module('v2_creator', 'create-app.py')
        self.creator.ROOT = self.root
        self.standard = module('v2_standard', 'plugin-standard.py')

    def create(self, **options):
        self.creator.create('example-app', 'Example app', template='v2', parent_origin='https://portal.example.invalid', **options)
        return self.root / 'apps/example-app'

    def test_explicit_v2_is_unlisted_zero_authority_and_uses_shared_shell(self):
        app = self.create()
        manifest = json.loads((app / 'app.v2.json').read_text())
        self.assertEqual(manifest['format'], 'portal.app/v2')
        self.assertEqual(manifest['capabilities'], {'required': [], 'optional': []})
        self.assertNotIn('backend', manifest)
        self.assertEqual(manifest['frontend']['sha256'], '0' * 64)
        self.assertEqual({r['path'] for r in manifest['presentation']['routes']}, {'/', '/editor'})
        self.assertFalse((app / 'app.json').exists())
        self.assertFalse((self.root / 'index.json').exists())
        self.assertTrue(self.standard.check(self.root))
        original = (app / 'frontend/src/App.tsx').read_text()
        for name in ['useAppPage', 'useAppPresentation', 'useAppDraft', 'useAppNavigation']:
            (app / 'frontend/src/App.tsx').write_text(original.replace(name, 'CustomHook'))
            with self.assertRaisesRegex(ValueError, name):
                self.standard.check(self.root)
        (app / 'frontend/src/App.tsx').write_text(original + '\n// PortalPage\n')
        with self.assertRaisesRegex(ValueError, 'PortalPage'):
            self.standard.check(self.root)

    def test_invalid_origins_names_and_template_refused_before_creating_files(self):
        for origin in ['', 'http://example.com', '//portal.example.invalid', 'https://portal.example.invalid/',
                       'https://user:secret@portal.example.invalid', 'https://portal.example.invalid?q=1',
                       'https://portal.example.invalid#x', 'https://PORTAL.example.invalid', 'https://portal.example.invalid:443', 'https://127.1', 'https://0x7f000001']:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                self.creator.create('example-app', 'Example', template='v2', parent_origin=origin)
            self.assertFalse((self.root / 'apps/example-app').exists())
        with self.assertRaises(ValueError):
            self.creator.create('example-app', 'Example', template='unknown')
        for index,name in enumerate(['', ' ', 'x'*81, '\ud800', 'x\n', '\u202e', ' x', 'x ', 'x\u200b', 'x\ufffd']):
            identity=f'invalid-name-{index}'
            with self.subTest(name=repr(name)):
                with self.assertRaises(ValueError):
                    self.creator.create(identity, name, template='v2', parent_origin='http://127.0.0.1:31935')
                self.assertFalse((self.root/'apps'/identity).exists())
        self.assertFalse((self.root / 'apps/example-app').exists())

    def test_names_containing_template_markers_remain_literal_text(self):
        name='PARENT_ORIGIN_JSON / PUBLISHER_JSON "quoted"'
        self.creator.create('example-app',name,template='v2',parent_origin='https://portal.example.invalid')
        app=self.root/'apps/example-app'
        manifest=json.loads((app/'app.v2.json').read_text())
        self.assertEqual(manifest['presentation']['display']['texts'][0]['name'],name)
        for locale in ['en-US','zh-CN','zh-TW']:
            self.assertEqual(json.loads((app/'frontend/locales'/f'{locale}.json').read_text())['title'],name)

    def test_dual_manifests_and_a_missing_v2_workspace_cannot_bypass_standard(self):
        app = self.create()
        (app / 'app.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'both'):
            self.standard.check(self.root)
        (app / 'app.json').unlink()
        (app / 'frontend/package.json').unlink()
        with self.assertRaisesRegex(ValueError, 'frontend/package.json'):
            self.standard.check(self.root)

    def test_v2_origin_validation_does_not_derive_trust_from_a_browser(self):
        app = self.create()
        source = app / 'frontend/src/bootstrap.json'
        self.assertEqual(json.loads(source.read_text()), {'parentOrigin':'https://portal.example.invalid'})
        source.write_text('{"parentOrigin":"https://user:secret@portal.example.invalid"}')
        with self.assertRaisesRegex(ValueError, 'origin'):
            self.standard.check(self.root)


class V2PackagingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shutil.copytree(ROOT / 'templates', self.root / 'templates')
        creator = module('v2_package_creator','create-app.py');creator.ROOT=self.root
        creator.create('sample','Sample',template='v2',parent_origin='http://127.0.0.1:31935')
        self.app=self.root/'apps/sample'
        self.dist=self.app/'frontend/dist';self.dist.mkdir()
        for name,content in {'index.html':'<!doctype html><script src="app.js"></script>','app.js':'console.log("sample");','style.css':'body{margin:0}'}.items():
            (self.dist/name).write_text(content)
        self.builder=module('v2_builder','build-app-v2.py')
        self.seen=[]

    def candidate(self,name='one'):
        return self.builder.package_frontend('sample',self.root/name,root=self.root,validator=self.seen.append)

    def test_digest_is_real_archive_is_reproducible_and_source_is_unchanged(self):
        import hashlib,zipfile
        source=(self.app/'app.v2.json').read_bytes()
        first=self.candidate();second=self.candidate('two')
        raw=(first/'frontend.zip').read_bytes()
        self.assertEqual(raw,(second/'frontend.zip').read_bytes())
        descriptor=json.loads((first/'descriptor.json').read_text())
        self.assertEqual(descriptor['frontend']['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual((self.app/'app.v2.json').read_bytes(),source)
        self.assertEqual(len(self.seen),4)
        with zipfile.ZipFile(first/'frontend.zip') as archive:
            self.assertEqual(archive.namelist(),['app.js','index.html','style.css'])
            self.assertTrue(all(info.date_time==(1980,1,1,0,0,0) for info in archive.infolist()))
        with self.assertRaises(ValueError):self.candidate()

    def test_bad_build_members_and_duplicate_source_json_fail_without_output(self):
        (self.dist/'remote.js').symlink_to(self.dist/'app.js')
        with self.assertRaises(ValueError):self.candidate()
        self.assertFalse((self.root/'one').exists())
        (self.dist/'remote.js').unlink()
        (self.app/'app.v2.json').write_text('{"id":"sample","id":"another"}')
        with self.assertRaises(ValueError):self.candidate()
        self.assertFalse((self.root/'one').exists())

    def test_validator_failure_or_invalid_origin_leaves_no_candidate(self):
        def reject(_raw):raise ValueError('descriptor refused')
        with self.assertRaises(ValueError):
            self.builder.package_frontend('sample',self.root/'one',root=self.root,validator=reject)
        self.assertFalse((self.root/'one').exists())
        (self.app/'frontend/src/bootstrap.json').write_text('{"parentOrigin":"http://remote.example.invalid"}')
        with self.assertRaises(ValueError):self.candidate()
        self.assertFalse((self.root/'one').exists())

if __name__ == '__main__':
    unittest.main()
