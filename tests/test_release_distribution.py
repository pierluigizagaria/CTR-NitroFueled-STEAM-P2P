import argparse
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from distribution_support import json_bytes, player_file, read_zip, sha256, verify_manifest
from export_host_source import export_git
from draft_distributions import validate as validate_draft
from package_distribution import assemble


def archive(path, files):
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pin = {'repository': 'https://github.com/GetLostIn/CTR-NitroFueled-PC.git',
                    'display_name': 'GetLostIn/CTR-NitroFueled-PC', 'source_tree': 'e' * 40,
                    'recipe': {'path': 'integrations/GetLostIn/CTR-NitroFueled-PC/recipe.json', 'sha256': 'f' * 64},
                    'revision': 'a' * 40, 'psn_tree': 'b' * 40, 'host_mode': 'psn',
                    'launcher': 'CTR-NitroFueled-PC.exe', 'portable_root': 'portable',
                    'upstream': {'repository': 'https://github.com/GetLostIn/CTR-NitroFueled-PC.git',
                                 'tag': 'v0.4', 'revision': 'c' * 40}}
        self.lock = self.root / 'lock.json'
        self.lock.write_bytes(json_bytes({'schema_version': 2, 'channels': {'getlostin-ctr-nitrofueled-pc': self.pin}}))
        self.host_files = {'portable/CTR-NitroFueled-PC.exe': b'launcher',
                           'portable/bin/sacredfire.exe': b'host', 'portable/bin/bb-gpu-capabilities.exe': b'caps',
                           'portable/run.py': b'# source',
                           'portable/LICENSE': b'GPL', 'portable/THIRD-PARTY.txt': b'notices',
                           'portable/art/picture.png': b'optional artwork'}
        self.host = self.root / 'host.zip'
        archive(self.host, self.host_files)
        self.mod_files = {'ctrnf-p2p.exe': b'bridge', 'ctrnf-p2p.ini': b'[game]\nhost=native\n',
                          'licenses/ctrnf-p2p/LICENSE': b'MIT'}
        manifest = {'component': 'ctrnf-p2p-mod', 'version': 'v0.1.0-preview.1',
                    'platform': 'windows-x64', 'components': {'ctrnf-p2p': {'revision': 'd' * 40}},
                    'build': {'source_dirty': False},
                    'files': {k: sha256(v) for k, v in self.mod_files.items()}}
        self.mod_files['ctrnf-p2p-manifest.json'] = json_bytes(manifest)
        self.mod_files['ctrnf-p2p-SHA256SUMS.txt'] = b'input sums'
        self.mod = self.root / 'mod.zip'
        archive(self.mod, self.mod_files)
        self.source = self.root / 'source.zip'
        self.source_files = {'host/LICENSE': b'GPL'}
        self.source_manifest = {'component': 'ctrnf-p2p-host-source', 'channel': 'getlostin-ctr-nitrofueled-pc',
                                'revision': 'a' * 40, 'psn_tree': 'b' * 40,
                                'source_tree': self.pin['source_tree'], 'host': self.pin,
                                'redistribution_ready': True, 'runtime_dependencies': {},
                                'build_recipe': {'source_dirty': False},
                                'files': {'host/LICENSE': sha256(b'GPL')}}
        self.write_source()
        self.backend = self.root / 'backend'
        self.backend.mkdir()
        (self.backend / 'psn-bridge-backend.dll').write_bytes(b'backend')
        self.host_build = self.root / 'host-build.json'
        self.host_build.write_bytes(json_bytes({'schema_version': 1, 'source_revision': 'a' * 40,
            'shared_psn_tree': 'b' * 40, 'source_tree': self.pin['source_tree'],
            'integration_recipe': self.pin['recipe'], 'clean_source': True, 'binaries': {
                'CTR-NitroFueled-PC.exe': sha256(b'launcher'), 'bin/sacredfire.exe': sha256(b'host'),
                'bin/bb-gpu-capabilities.exe': sha256(b'caps'), 'psn-bridge-backend.dll': sha256(b'backend')}}))
        self.args = argparse.Namespace(lock=self.lock, channel='getlostin-ctr-nitrofueled-pc', host_package=self.host,
                                       mod_package=self.mod, source_package=self.source,
                                       backend_dir=self.backend, version='v0.1.0-preview.1',
                                       host_build_manifest=self.host_build,
                                       output=self.root / 'complete.zip', require_redistribution_ready=True)

    def test_rejects_binary_not_bound_to_reviewed_build(self):
        archive(self.host, self.host_files | {'portable/bin/sacredfire.exe': b'stock host'})
        with self.assertRaisesRegex(ValueError, 'build artifact checksum'):
            assemble(self.args)

    def write_source(self):
        archive(self.source, self.source_files | {'source-manifest.json': json_bytes(self.source_manifest)})

    def test_complete_assembly_rehashes_settings_keeps_sources_and_is_deterministic(self):
        result = assemble(self.args)
        self.assertTrue(result['redistribution_ready'])
        files = read_zip(self.args.output)
        self.assertIn(b'host = psn', files['ctrnf-p2p.ini'])
        self.assertNotIn('art/picture.png', files)
        self.assertEqual(result['omitted_optional_artwork'], {'art/picture.png': sha256(b'optional artwork')})
        self.assertEqual(result['sources']['sha256'], sha256(self.source.read_bytes()))
        verify_manifest(files, 'ctrnf-p2p-manifest.json')
        first = self.args.output.read_bytes()
        self.args.output = self.root / 'second.zip'
        assemble(self.args)
        self.assertEqual(first, self.args.output.read_bytes())

    def test_rejects_unmanifested_or_tampered_mod(self):
        archive(self.mod, self.mod_files | {'unexpected.exe': b'extra'})
        with self.assertRaisesRegex(ValueError, 'unmanifested'):
            assemble(self.args)
        archive(self.mod, self.mod_files | {'ctrnf-p2p.exe': b'modified'})
        with self.assertRaisesRegex(ValueError, 'checksum'):
            assemble(self.args)

    def test_documentation_art_is_omitted_from_portable_packages_without_losing_text(self):
        image = 'docs/native-handbook/images/example.png'
        text = 'docs/native-handbook/START-HERE.txt'
        archive(self.host, self.host_files | {'portable/' + image: b'optional screenshot',
                                             'portable/' + text: b'handbook instructions'})
        result = assemble(self.args)
        files = read_zip(self.args.output)
        self.assertNotIn(image, files)
        self.assertEqual(files[text], b'handbook instructions')
        self.assertEqual(result['omitted_optional_artwork'][image], sha256(b'optional screenshot'))

    def test_rejects_wrong_corresponding_source(self):
        self.source_manifest['revision'] = 'e' * 40
        self.write_source()
        with self.assertRaisesRegex(ValueError, 'Source companion'):
            assemble(self.args)

    def test_source_tree_and_recipe_are_bound_to_build_evidence(self):
        original = json.loads(self.host_build.read_bytes())
        for field, value in (('source_tree', '0' * 40),
                             ('integration_recipe', self.pin['recipe'] | {'sha256': '0' * 64})):
            with self.subTest(field=field):
                self.host_build.write_bytes(json_bytes(original | {field: value}))
                with self.assertRaisesRegex(ValueError, 'Host build evidence'):
                    assemble(self.args)
        self.host_build.write_bytes(json_bytes(original))
        self.source_manifest['source_tree'] = '0' * 40
        self.write_source()
        with self.assertRaisesRegex(ValueError, 'Source companion'):
            assemble(self.args)

    def test_source_companion_must_name_the_exact_recipe(self):
        self.source_manifest['host'] = deepcopy(self.pin)
        self.source_manifest['host']['recipe']['sha256'] = '0' * 64
        self.write_source()
        with self.assertRaisesRegex(ValueError, 'Source companion'):
            assemble(self.args)

    def test_preserved_host_marker_is_replaced_with_upstream_identity(self):
        archive(self.host, self.host_files | {'portable/p2p-distribution.json':
                                             json_bytes({'channel': 'channel-a'})})
        assemble(self.args)
        files = read_zip(self.args.output)
        marker = json.loads(files['p2p-distribution.json'])
        self.assertEqual(marker['distribution'], 'GetLostIn/CTR-NitroFueled-PC')
        self.assertEqual(marker['channel'], self.args.channel)
        self.assertIn(b'GetLostIn/CTR-NitroFueled-PC complete preview', files['CTR-P2P-README.md'])

    def test_wrong_historical_host_marker_is_rejected(self):
        archive(self.host, self.host_files | {'portable/p2p-distribution.json':
                                             json_bytes({'channel': 'channel-b'})})
        with self.assertRaisesRegex(ValueError, 'different channel'):
            assemble(self.args)

    def test_complete_draft_requires_both_upstreams_and_bound_sources(self):
        dist = self.root / 'draft'
        dist.mkdir()
        for slug, upstream in (('getlostin-ctr-nitrofueled-pc', 'GetLostIn/CTR-NitroFueled-PC'),
                               ('ryu7w7-octr-nitrofueled-pc', 'Ryu7w7/OCTR-NitroFueled-PC')):
            pin = deepcopy(self.pin)
            pin.update(display_name=upstream, repository='https://github.com/' + upstream + '.git')
            pin['upstream']['repository'] = pin['repository']
            pin['recipe']['path'] = 'integrations/' + upstream + '/recipe.json'
            self.lock.write_bytes(json_bytes({'schema_version': 2, 'channels': {slug: pin}}))
            self.args.channel = slug
            self.args.output = dist / (slug + '-windows-x64.zip')
            self.source = self.args.source_package = dist / (slug + '-source.zip')
            self.source_manifest.update(channel=slug, host=pin,
                                        build_recipe={'revision': 'd' * 40, 'source_dirty': False})
            self.write_source()
            self.source.with_suffix('.zip.sha256').write_text(sha256(self.source.read_bytes()) + '  ' + self.source.name)
            receipt = json.loads(self.host_build.read_bytes())
            receipt['integration_recipe'] = pin['recipe']
            self.host_build.write_bytes(json_bytes(receipt))
            assemble(self.args)
        self.assertEqual(len(validate_draft(dist, self.args.version, 'd' * 40)), 8)
        # A rewritten source archive cannot replace the companion bound to the binary.
        self.source_manifest['source_tree'] = '0' * 40
        self.write_source()
        with self.assertRaisesRegex(ValueError, 'source companion checksum'):
            validate_draft(dist, self.args.version, 'd' * 40)

    def test_dependency_coverage_and_hash_are_required_for_redistribution(self):
        (self.backend / 'libexample.dll').write_bytes(b'dependency')
        with self.assertRaisesRegex(ValueError, 'source/notice evidence'):
            assemble(self.args)
        self.args.require_redistribution_ready = False
        result = assemble(self.args)
        self.assertFalse(result['redistribution_ready'])
        self.assertEqual(result['unresolved_runtime_dependencies'], ['libexample.dll'])

    def test_rejects_payload_collisions_and_private_state(self):
        archive(self.host, self.host_files | {'portable/ctrnf-p2p.exe': b'other bridge'})
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            assemble(self.args)
        archive(self.host, self.host_files | {'portable/user/save.bin': b'save'})
        with self.assertRaisesRegex(ValueError, 'Private'):
            assemble(self.args)

    def test_rejects_windows_aliases_traversal_and_links(self):
        for bad in ('../file', 'bin/CON.txt', 'file:ads', 'file.', 'FILE ', 'C:/file', 'x\\y'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                player_file(bad)
        path = self.root / 'bad.zip'
        archive(path, {'same.txt': b'a', 'SAME.txt': b'b'})
        with self.assertRaisesRegex(ValueError, 'case-alias'):
            read_zip(path)
        with zipfile.ZipFile(path, 'w') as z:
            item = zipfile.ZipInfo('symlink')
            item.create_system = 3
            item.external_attr = 0o120777 << 16
            z.writestr(item, '../outside')
        with self.assertRaisesRegex(ValueError, 'Non-regular'):
            read_zip(path)

    def test_export_reads_committed_parent_and_submodule_not_dirty_checkout(self):
        def git(repo, *args):
            return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
        repo = self.root / 'repo'
        repo.mkdir()
        git(repo, 'init', '-q')
        child = repo / 'vendor'
        child.mkdir()
        git(child, 'init', '-q')
        (child / 'library.c').write_text('original source')
        git(child, 'add', 'library.c')
        git(child, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-qm', 'library')
        commit = git(child, 'rev-parse', 'HEAD')
        (repo / '.gitmodules').write_text('[submodule "vendor"]\npath=vendor\nurl=https://example.invalid/library.git\n')
        (repo / 'build.sh').write_text('apply tracked.patch')
        (repo / 'tracked.patch').write_text('fixture patch recipe')
        git(repo, 'add', '.gitmodules', 'build.sh', 'tracked.patch')
        git(repo, 'update-index', '--add', '--cacheinfo', f'160000,{commit},vendor')
        git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-qm', 'host')
        (child / 'library.c').write_text('dirty generated source')
        (repo / 'private.key').write_text('not tracked')
        files, modes, modules = {}, {}, []
        export_git(repo, git(repo, 'rev-parse', 'HEAD'), 'host/', files, modes, modules)
        self.assertEqual(files['host/vendor/library.c'], b'original source')
        self.assertIn('host/tracked.patch', files)
        self.assertNotIn('host/private.key', files)
        self.assertEqual(modules[0]['revision'], commit)


if __name__ == '__main__':
    unittest.main()
