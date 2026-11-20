import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location('run_backend_local', ROOT / 'scripts/run-backend-local.py')
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)

BACKEND = {'platform': 'linux/amd64', 'memory_mib': 128, 'cpu_millis': 250, 'pids': 64, 'proxy': False}
DIRECTORY = Path('/work/apps/demo/.development/local')


def pairs(args):
    """Every `--flag value` pair, so a test can look a flag up without caring about order."""
    found = {}
    for flag, value in zip(args, args[1:]):
        found.setdefault(flag, []).append(value)
    return found


class RunArgsTests(unittest.TestCase):
    def run_args(self, **options):
        return local.run_args('demo', 'demo:dev', BACKEND | options.pop('backend', {}), DIRECTORY, **options)

    def test_the_runners_sandbox_is_reproduced(self):
        args = self.run_args()
        found = pairs(args)
        self.assertEqual(found['--user'], ['65532:65532'])
        self.assertEqual(found['--network'], ['none'])
        self.assertIn('--read-only', args)
        self.assertEqual(found['--cap-drop'], ['ALL'])
        self.assertEqual(found['--security-opt'], ['no-new-privileges:true'])
        self.assertEqual(found['--tmpfs'], ['/tmp:rw,nosuid,nodev,noexec,size=16777216,mode=1777'])
        self.assertEqual(found['--memory'], ['128m'])
        self.assertEqual(found['--memory-swap'], ['128m'])
        self.assertEqual(found['--cpus'], ['0.25'])
        self.assertEqual(found['--pids-limit'], ['64'])
        self.assertEqual(found['--cpu-shares'], ['256'])
        self.assertEqual(found['--shm-size'], ['16m'])
        self.assertEqual(found['--ulimit'], ['nofile=1024:1024'])
        self.assertEqual(found['--restart'], ['no'])
        self.assertEqual(found['--stop-timeout'], ['10'])
        self.assertIn('--init', args)
        self.assertEqual(args[-1], 'demo:dev')

    def test_nothing_is_published_and_only_three_paths_are_mounted(self):
        args = self.run_args()
        for flag in ('-p', '--publish', '-P', '--privileged', '--network=host', '--volume', '-v'):
            self.assertNotIn(flag, args)
        mounts = pairs(args)['--mount']
        self.assertEqual(len(mounts), 3)
        self.assertEqual([m.split('target=')[1].split(',')[0] for m in mounts],
                         ['/data', '/run/portal-app/http', '/run/portal-app/broker'])
        data, http, broker = mounts
        self.assertNotIn('readonly', data.split(','))
        self.assertNotIn('readonly', http.split(','))
        self.assertIn('readonly', broker.split(','))  # the runner mounts the broker directory read-only
        self.assertTrue(all('bind-propagation=rprivate' in m for m in mounts))

    def test_environment_names_the_two_sockets_and_the_proxy_only_when_declared(self):
        env = pairs(self.run_args())['--env']
        self.assertEqual(env, ['PORTAL_APP_HTTP_SOCKET=/run/portal-app/http/app.sock',
                               'PORTAL_APP_BROKER_SOCKET=/run/portal-app/broker/broker.sock'])
        env = pairs(self.run_args(backend={'proxy': True}))['--env']
        self.assertIn('HTTPS_PROXY=http://127.0.0.1:3128', env)
        self.assertIn('https_proxy=http://127.0.0.1:3128', env)
        self.assertIn('NO_PROXY=127.0.0.1,localhost', env)
        self.assertIn('PORTAL_APP_PROXY_LISTEN=127.0.0.1:3128', env)
        # Doc 184: plain HTTP stays refused, so HTTP_PROXY and ALL_PROXY are never set.
        self.assertFalse([e for e in env if e.split('=')[0].upper() in {'HTTP_PROXY', 'ALL_PROXY'}])

    def test_data_can_be_mounted_read_only_and_a_broker_socket_added(self):
        mounts = pairs(self.run_args(data_readonly=True))['--mount']
        self.assertIn('readonly', mounts[0].split(','))
        mounts = pairs(self.run_args(broker_socket=Path('/tmp/fake/broker.sock')))['--mount']
        self.assertEqual(len(mounts), 4)
        self.assertIn('source=/tmp/fake/broker.sock,target=/run/portal-app/broker/broker.sock', mounts[3])

    def test_the_container_name_is_per_checkout_and_app(self):
        first = local.container_name('demo', Path('/work/a/.development/local'))
        self.assertRegex(first, r'^portal-local-demo-[0-9a-f]{6}$')
        self.assertNotEqual(first, local.container_name('demo', Path('/work/b/.development/local')))
        self.assertEqual(pairs(self.run_args())['--name'], [local.container_name('demo', DIRECTORY)])

    def test_detached_or_attached_and_a_resource_limit_follows_the_descriptor(self):
        self.assertIn('--detach', self.run_args())
        attached = self.run_args(detach=False)
        self.assertNotIn('--detach', attached)
        self.assertIn('--rm', attached)
        found = pairs(self.run_args(backend={'memory_mib': 2048, 'cpu_millis': 1000, 'pids': 128}))
        self.assertEqual((found['--memory'], found['--cpus'], found['--pids-limit']), (['2048m'], ['1'], ['128']))

    def test_a_path_that_would_split_a_mount_option_is_refused(self):
        with self.assertRaises(local.LocalRunError):
            local.run_args('demo', 'demo:dev', BACKEND, Path('/work/a,b'))


class PrepareTests(unittest.TestCase):
    def test_a_broker_socket_needs_its_mount_point_to_exist_beforehand(self):
        # runc cannot create a mount point inside the read-only broker directory.
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            local.prepare(directory)
            self.assertFalse((directory / 'broker/broker.sock').exists())
            local.prepare(directory, Path('/tmp/fake.sock'))
            self.assertTrue((directory / 'broker/broker.sock').is_file())
            local.prepare(directory)
            self.assertFalse((directory / 'broker/broker.sock').exists())
            self.assertEqual(oct((directory / 'data').stat().st_mode & 0o7777), '0o1777')
            self.assertEqual(oct((directory / 'broker').stat().st_mode & 0o7777), '0o755')


class HelperArgsTests(unittest.TestCase):
    def test_the_client_runs_in_the_same_sandbox_with_the_socket_directory(self):
        args = local.helper_args('demo:dev', BACKEND, DIRECTORY, Path('/work/bin/portal-dev-client'),
                                 local.call_tool_args('GET', '/v1/hello', role='admin', ous=['a', 'b']))
        found = pairs(args)
        self.assertEqual((found['--user'], found['--network']), (['65532:65532'], ['none']))
        self.assertIn('--read-only', args)
        self.assertEqual(found['--entrypoint'], ['/portal-dev-client'])
        mounts = found['--mount']
        self.assertEqual(len(mounts), 3)
        self.assertTrue(any('target=/portal-dev-client,' in m and m.endswith('readonly') for m in mounts))
        self.assertNotIn('target=/data', ' '.join(mounts))
        tail = args[args.index('demo:dev') + 1:]
        self.assertEqual(tail[:5], ['call', '--socket', '/run/portal-app/http/app.sock', '--registration',
                                    '/run/portal-app/broker/registration.json'])
        self.assertEqual(tail[-2:], ['GET', '/v1/hello'])
        self.assertEqual(tail.count('--ou'), 2)

    def test_only_purge_runs_as_root_and_it_sees_nothing_but_the_work_directory(self):
        args = local.helper_args('demo:dev', BACKEND, DIRECTORY, Path('/work/bin/c'), ['purge', '--dir', '/work'], root_user=True)
        self.assertEqual(pairs(args)['--user'], ['0:0'])
        self.assertIn('target=/work,', ' '.join(pairs(args)['--mount']))
        self.assertEqual(pairs(args)['--network'], ['none'])
        self.assertEqual(pairs(args)['--cap-add'], ['DAC_OVERRIDE', 'FOWNER'])
        self.assertEqual(pairs(args)['--cap-drop'], ['ALL'])
        plain = local.helper_args('demo:dev', BACKEND, DIRECTORY, Path('/work/bin/c'), ['ready'])
        self.assertNotIn('--cap-add', plain)

    def test_task_arguments_carry_the_payload_as_one_argument(self):
        tool = local.task_tool_args('{"job": "example"}', 'occ-1')
        self.assertEqual(tool[-1], '{"job": "example"}')
        self.assertEqual(tool[tool.index('--occurrence') + 1], 'occ-1')


class DescriptorTests(unittest.TestCase):
    def app(self, declaration):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / 'apps/demo').mkdir(parents=True)
        (root / 'apps/demo/app.v2.json').write_text(json.dumps(declaration))
        return root

    def test_limits_and_proxy_come_from_the_descriptor(self):
        root = self.app({'backend': {'platforms': ['linux/arm64'], 'resources': {'memory_mib': 256, 'cpu_millis': 500, 'pids': 32}},
                         'capabilities': {'required': [], 'optional': ['background.run', 'network.proxy']}})
        self.assertEqual(local.read_backend('demo', root), {
            'platform': 'linux/arm64', 'memory_mib': 256, 'cpu_millis': 500, 'pids': 32, 'proxy': True})

    def test_proxy_needs_the_optional_declaration_not_a_required_one(self):
        root = self.app({'backend': {'platforms': ['linux/amd64'], 'resources': {'memory_mib': 16, 'cpu_millis': 25, 'pids': 16}},
                         'capabilities': {'required': ['network.http'], 'optional': None}})
        self.assertFalse(local.read_backend('demo', root)['proxy'])

    def test_an_app_without_a_backend_or_with_a_bad_id_is_refused(self):
        with self.assertRaises(local.LocalRunError):
            local.read_backend('demo', self.app({'capabilities': {}}))
        with self.assertRaises(local.LocalRunError):
            local.read_backend('missing', self.app({}))
        for bad in ('', 'Demo', '../x', 'a b', '1abc', 'a' * 65):
            with self.subTest(bad), self.assertRaises(local.LocalRunError):
                local.app_id_checked(bad)

    def test_the_template_descriptor_is_readable_after_generation(self):
        # The generated backend app runs locally with its own limits and no proxy until it opts in.
        text = (ROOT / 'templates/react-app-v2-backend/app.v2.json').read_text()
        value = json.loads(text.replace('PUBLISHER_JSON', '"p"').replace('APP_NAME_JSON', '"n"'))
        root = self.app(value)
        self.assertEqual(local.read_backend('demo', root)['proxy'], False)


if __name__ == '__main__':
    unittest.main()
