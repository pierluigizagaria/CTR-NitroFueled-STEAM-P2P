"""Host identity must follow its upstream, independently of the P2P preview tag."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import ci_distribution


class HostVersionTests(unittest.TestCase):
    def run_build(self, channel, upstream, *, build_identity=True,
                  built_version=None, packaged_version=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        host = root / 'host'
        (host / 'packaging/windows').mkdir(parents=True)
        (host / 'packaging/windows/make_portable.py').write_text('# packaging fixture\n')
        if build_identity:
            (host / 'tools').mkdir()
            (host / 'tools/build_version.py').write_text('# embedded identity fixture\n')
        (root / 'release-lock.json').write_text(json.dumps({'json': {'header': {}}}))
        pin = {'revision': 'a' * 40, 'source_tree': 'b' * 40, 'psn_tree': 'c' * 40,
               'upstream': {'tag': upstream}, 'recipe': {'path': 'recipe.json'},
               'launcher': 'CTR-NitroFueled-PC.exe', 'portable_root': 'portable'}
        commands = []

        def output(*args):
            if 'status' in args:
                return ''
            return {'HEAD': pin['revision'], 'HEAD^{tree}': pin['source_tree'],
                    'HEAD:platform/psn': pin['psn_tree']}[args[-1]] if '--short=12' not in args else 'd' * 12

        def run(*args, **kwargs):
            args = [str(arg) for arg in args]
            commands.append((args, kwargs))
            if args[1:2] == ['build.sh']:
                (host / 'out').mkdir()
                actual = built_version or (kwargs['env']['BB_VERSION'] if build_identity else 'v0.4-7-gabcdef')
                (host / 'out/VERSION').write_text(actual + '-windows\n')
            if '--build' in args:
                backend = host / 'out/p2p-psn/backends'
                backend.mkdir(parents=True)
                (backend / 'psn-bridge-backend.dll').write_bytes(b'backend')
            if len(args) > 1 and args[1].endswith('make_portable.py'):
                portable = Path(args[args.index('--dist') + 1])
                portable.mkdir(parents=True)
                actual = packaged_version or args[args.index('--version') + 1]
                with zipfile.ZipFile(portable / 'CTR-NitroFueled-PC-portable-windows.zip', 'w') as archive:
                    for name in ('CTR-NitroFueled-PC.exe', 'bin/sacredfire.exe', 'bin/bb-gpu-capabilities.exe'):
                        archive.writestr('portable/' + name, name.encode())
                    archive.writestr('portable/bin/VERSION', actual + '-windows\n')

        argv = ['ci_distribution.py', '--channel', channel, '--host-source', str(host),
                '--msys-root', str(root / 'msys'), '--mod-package', str(root / 'mod.zip'),
                '--version', 'v0.1.0-preview.1', '--require-redistribution-ready']
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(ci_distribution, 'ROOT', root))
            stack.enter_context(mock.patch.object(ci_distribution, 'locked_channel', return_value=({}, pin)))
            stack.enter_context(mock.patch.object(ci_distribution, 'output', side_effect=output))
            stack.enter_context(mock.patch.object(ci_distribution, 'run', side_effect=run))
            stack.enter_context(mock.patch('host_integration.load_recipe'))
            stack.enter_context(mock.patch('release_support.download', return_value=root / 'include/nlohmann/json.hpp'))
            stack.enter_context(mock.patch.object(sys, 'argv', argv))
            stack.enter_context(mock.patch.dict('os.environ', {'BB_VERSION': 'v9.9.9'}))
            ci_distribution.main()
        receipt = json.loads((root / 'out/distribution' / channel / 'host-build-manifest.json').read_text())
        return commands, receipt

    def test_both_host_packages_use_upstream_tag_and_keep_preview_distribution(self):
        for channel, tag, identity in [('getlostin-ctr-nitrofueled-pc', 'v0.4', False),
                                       ('ryu7w7-octr-nitrofueled-pc', 'v0.8.3', True)]:
            with self.subTest(channel=channel):
                commands, receipt = self.run_build(channel, tag, build_identity=identity)
                build = next(item for item in commands if item[0][1:2] == ['build.sh'])
                self.assertEqual(build[1]['env']['BB_VERSION'], tag)
                portable = next(args for args, _ in commands if args[1].endswith('make_portable.py'))
                self.assertEqual(portable[portable.index('--version') + 1], tag)
                assembly = next(args for args, _ in commands if args[1].endswith('package_distribution.py'))
                self.assertEqual(assembly[assembly.index('--version') + 1], 'v0.1.0-preview.1')
                self.assertIn(channel + '-v0.1.0-preview.1-', assembly[assembly.index('--output') + 1])
                self.assertEqual(receipt['upstream_version'], tag)
                self.assertIn('BB_VERSION=' + tag, receipt['commands'][0])
                self.assertIn('--version ' + tag, receipt['commands'][-1])

    def test_embedded_host_identity_must_match_the_locked_upstream(self):
        with self.assertRaisesRegex(ValueError, 'Host build version differs'):
            self.run_build('ryu7w7-octr-nitrofueled-pc', 'v0.8.3', built_version='dev-deadbeef')

    def test_packaged_identity_cannot_revert_to_preview_or_another_upstream(self):
        for wrong in ('v0.1.0-preview.1', 'v0.7.5'):
            with self.subTest(version=wrong), self.assertRaisesRegex(ValueError, 'Host package version differs'):
                self.run_build('ryu7w7-octr-nitrofueled-pc', 'v0.8.3', packaged_version=wrong)

    def test_older_host_packaging_also_rejects_the_preview_version(self):
        with self.assertRaisesRegex(ValueError, 'Host package version differs'):
            self.run_build('getlostin-ctr-nitrofueled-pc', 'v0.4', build_identity=False,
                           packaged_version='v0.1.0-preview.1')


if __name__ == '__main__':
    unittest.main()
