import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import automation_publish as publisher
from distribution_support import json_bytes, sha256


def archive(path, files):
    with zipfile.ZipFile(path, 'w') as stream:
        for name, data in files.items():
            stream.writestr(name, data)
    path.with_suffix('.zip.sha256').write_text(sha256(path.read_bytes()) + '  ' + path.name + '\n')


def fixture_recipe(repository):
    return {'schema_version': 1, 'upstream_repository': repository,
            'commits': [{'patch': 'adapter.patch', 'sha256': sha256(b'fixture adapter patch')}]}


def fixture_plan():
    pins, channels = {}, {}
    for index, channel in enumerate(publisher.CHANNELS):
        display_name = ('GetLostIn/CTR-NitroFueled-PC', 'Ryu7w7/OCTR-NitroFueled-PC')[index]
        pins[channel] = {'repository': 'https://github.com/' + display_name + '.git', 'display_name': display_name,
                         'source_tree': '8' * 40, 'recipe': {'path': 'integrations/' + display_name + '/recipe.json',
                             'sha256': sha256(json_bytes(fixture_recipe('https://github.com/' + display_name + '.git')))},
                         'revision': str(index + 3) * 40, 'psn_tree': '7' * 40, 'host_mode': 'psn',
                         'launcher': 'launcher.exe', 'portable_root': 'portable',
                         'upstream': {'repository': 'https://github.com/' + display_name + '.git',
                                      'tag': 'v2.0', 'revision': '9' * 40}}
        channels[channel] = {'expected_old_revision': str(index + 1) * 40,
                             'candidate_revision': pins[channel]['revision'], 'source_tree': '8' * 40, 'psn_tree': '7' * 40,
                             'upstream': pins[channel]['upstream'], 'changed': True}
    return {'schema_version': 2, 'base_revision': 'a' * 40, 'candidate_revision': 'b' * 40,
            'channels': channels, 'new_lock': {'schema_version': 2, 'channels': pins},
            'version': 'v0.1.0-preview.1', 'changed': True, 'verify': False,
            'fingerprint': 'f' * 64, 'commit_timestamp': '2026-10-21T00:00:00Z'}


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = fixture_plan()
        self.release_lock = {'components': {
            'orbisteamworks': {'revision': 'c' * 40, 'version': 'v0.0.1', 'license': 'MIT'},
            'demonware-server': {'revision': 'd' * 40, 'version': 'v0.1.0', 'license': 'Shield'},
            'signature-patch': {'revision': 'e' * 40, 'version': 'v0.1.0', 'license': 'MIT'}},
            'host': {'repository': 'example/legacy-host', 'revision': '6' * 40},
            'steam_runtime': {'sha256': sha256(b'permitted runtime'), 'sdk_version': '1.65'}}
        components = copy.deepcopy(self.release_lock['components'])
        components.update({'ctrnf-p2p': {'revision': self.plan['candidate_revision'], 'license': 'MIT'},
                           'steamworks-runtime': {'sha256': sha256(b'permitted runtime'), 'sdk_version': '1.65'}})
        self.standalone_files = {'ctrnf-p2p.exe': b'bridge', 'steam_api64.dll': b'permitted runtime',
                                 'ctrnf-p2p.ini': b'[game]\nhost=native\n',
                                 'ctrnf-p2p-release-lock.json': json_bytes(self.release_lock),
                                 'ctrnf-p2p-build-info.json': json_bytes({'source_dirty': False})}
        self.standalone_manifest = {'component': 'ctrnf-p2p-mod', 'platform': 'windows-x64',
                                    'host': self.release_lock['host'], 'components': components,
                                    'version': self.plan['version'], 'build': {'source_dirty': False},
                                    'files': {name: sha256(data) for name, data in self.standalone_files.items()}}
        self.standalone_files['ctrnf-p2p-manifest.json'] = json_bytes(self.standalone_manifest)
        self.standalone_files['ctrnf-p2p-SHA256SUMS.txt'] = b'checksums'
        mod_name = f"ctrnf-p2p-mod-{self.plan['version']}-windows-x64-{self.plan['candidate_revision'][:12]}.zip"
        self.standalone_path = self.root / mod_name
        archive(self.standalone_path, self.standalone_files)
        mod_digest = sha256(self.standalone_path.read_bytes())
        self.sources, self.binaries = {}, {}
        for channel in publisher.CHANNELS:
            pin = self.plan['new_lock']['channels'][channel]
            prefix = f"ctrnf-p2p-{channel}-{self.plan['version']}-{self.plan['candidate_revision'][:12]}"
            source_payload = {'host/LICENSE': b'GPL', 'distribution-lock.json': json_bytes(self.plan['new_lock']),
                              'build-recipes/release-lock.json': json_bytes(self.release_lock)}
            source_payload[pin['recipe']['path']] = json_bytes(fixture_recipe(pin['upstream']['repository']))
            source_payload[str(Path(pin['recipe']['path']).parent.as_posix()) + '/adapter.patch'] = b'fixture adapter patch'
            source = {'component': 'ctrnf-p2p-host-source', 'channel': channel, 'host': pin,
                      'revision': pin['revision'], 'source_tree': pin['source_tree'], 'psn_tree': pin['psn_tree'], 'redistribution_ready': True,
                      'dependency_evidence_complete': True,
                      'build_recipe': {'revision': self.plan['candidate_revision'], 'source_dirty': False},
                      'files': {name: sha256(data) for name, data in source_payload.items()}}
            source_payload['source-manifest.json'] = json_bytes(source)
            source_path = self.root / (prefix + '-source.zip')
            archive(source_path, source_payload)
            native_files = {'launcher.exe': b'launcher', 'bin/sacredfire.exe': b'host',
                            'bin/bb-gpu-capabilities.exe': b'caps', 'psn-bridge-backend.dll': b'backend'}
            build = {'source_revision': pin['revision'], 'source_tree': pin['source_tree'],
                     'integration_recipe': pin['recipe'], 'shared_psn_tree': pin['psn_tree'],
                     'clean_source': True, 'binaries': {name: sha256(data) for name, data in native_files.items()}}
            files = native_files | self.standalone_files | {'p2p-host-build.json': json_bytes(build)}
            mod = copy.deepcopy(self.standalone_manifest)
            mod.update(host=pin, assembly={'input_mod_sha256': mod_digest})
            files['ctrnf-p2p-manifest.json'] = json_bytes(mod)
            manifest = {'component': 'ctrnf-p2p-distribution', 'channel': channel, 'host': pin,
                        'version': self.plan['version'], 'platform': 'windows-x64', 'host_build': build,
                        'components': components, 'build': {'source_dirty': False}, 'redistribution_ready': True,
                        'unresolved_runtime_dependencies': [],
                        'input_archives': {'mod': mod_digest},
                        'sources': {'archive': source_path.name, 'sha256': sha256(source_path.read_bytes()),
                                    'manifest_sha256': sha256(source_payload['source-manifest.json'])},
                        'files': {name: sha256(data) for name, data in files.items()}}
            files['p2p-distribution-manifest.json'] = json_bytes(manifest)
            files['p2p-SHA256SUMS.txt'] = b'checksums'
            binary_path = self.root / (prefix + '-windows-x64.zip')
            archive(binary_path, files)
            self.sources[channel] = (source_path, source_payload)
            self.binaries[channel] = (binary_path, files)

    def test_validates_two_complete_channels_sources_first(self):
        assets = publisher.validate_assets(self.root, self.plan, self.release_lock)
        self.assertEqual(len(assets), 10)
        self.assertTrue(all('-source.zip' in asset.name for asset in assets[:4]))
        self.assertIn(self.standalone_path, assets)
        self.assertIn(self.standalone_path.with_suffix('.zip.sha256'), assets)

    def test_rejects_self_consistent_package_for_a_different_host_plan(self):
        plan = copy.deepcopy(self.plan)
        plan['new_lock']['channels']['getlostin-ctr-nitrofueled-pc']['upstream']['tag'] = 'v3.0'
        with self.assertRaisesRegex(ValueError, 'Host identity'):
            publisher.validate_assets(self.root, plan, self.release_lock)

    def test_rejects_extra_payload_even_if_other_checksums_are_valid(self):
        path, files = self.binaries['getlostin-ctr-nitrofueled-pc']
        archive(path, files | {'unexpected.exe': b'not covered'})
        with self.assertRaisesRegex(ValueError, 'manifested payload'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)

    def test_rejects_an_unreviewed_component_even_with_valid_package_hashes(self):
        self.standalone_manifest['components']['orbisteamworks']['revision'] = '0' * 40
        self.standalone_files['ctrnf-p2p-manifest.json'] = json_bytes(self.standalone_manifest)
        archive(self.standalone_path, self.standalone_files)
        with self.assertRaisesRegex(ValueError, 'Component differs'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)

    def test_rejects_binary_receipt_not_bound_to_payload(self):
        path, files = self.binaries['getlostin-ctr-nitrofueled-pc']
        manifest = json.loads(files['p2p-distribution-manifest.json'])
        manifest['host_build']['binaries']['launcher.exe'] = '0' * 64
        files['p2p-distribution-manifest.json'] = json_bytes(manifest)
        archive(path, files)
        with self.assertRaisesRegex(ValueError, 'Host binary differs'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)

    def rewrite_binary(self, channel):
        path, files = self.binaries[channel]
        manifest = json.loads(files['p2p-distribution-manifest.json'])
        manifest['files'] = {name: sha256(data) for name, data in files.items()
                             if name not in {'p2p-distribution-manifest.json', 'p2p-SHA256SUMS.txt'}}
        files['p2p-distribution-manifest.json'] = json_bytes(manifest)
        archive(path, files)

    def test_missing_standalone_mod_stops_the_complete_release(self):
        self.standalone_path.unlink()
        with self.assertRaisesRegex(ValueError, 'standalone mod archive is required'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)

    def test_rejects_build_receipt_for_another_recipe(self):
        path, files = self.binaries[publisher.CHANNELS[0]]
        manifest = json.loads(files['p2p-distribution-manifest.json'])
        manifest['host_build']['integration_recipe']['sha256'] = '0' * 64
        files['p2p-distribution-manifest.json'] = json_bytes(manifest)
        archive(path, files)
        with self.assertRaisesRegex(ValueError, 'Host build receipt differs'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)

    def test_self_consistent_archive_cannot_substitute_embedded_recipe_or_patch(self):
        channel = publisher.CHANNELS[0]
        pin = self.plan['new_lock']['channels'][channel]
        source_path, source_files = self.sources[channel]
        original = dict(source_files)
        for target, error in ((pin['recipe']['path'], 'Embedded integration recipe differs'),
                              (str(Path(pin['recipe']['path']).parent.as_posix()) + '/adapter.patch',
                               'Embedded integration patch differs')):
            with self.subTest(target=target):
                source_files.clear()
                source_files.update(original)
                source_files[target] += b' '
                manifest = json.loads(source_files['source-manifest.json'])
                manifest['files'][target] = sha256(source_files[target])
                source_files['source-manifest.json'] = json_bytes(manifest)
                archive(source_path, source_files)
                _, files = self.binaries[channel]
                binary_manifest = json.loads(files['p2p-distribution-manifest.json'])
                binary_manifest['sources'].update(sha256=sha256(source_path.read_bytes()),
                    manifest_sha256=sha256(source_files['source-manifest.json']))
                files['p2p-distribution-manifest.json'] = json_bytes(binary_manifest)
                self.rewrite_binary(channel)
                with self.assertRaisesRegex(ValueError, error):
                    publisher.validate_assets(self.root, self.plan, self.release_lock)

    def test_standalone_mod_tampering_and_external_checksum_are_rejected(self):
        archive(self.standalone_path, self.standalone_files | {'ctrnf-p2p.exe': b'tampered bridge'})
        with self.assertRaisesRegex(ValueError, 'Manifest checksum mismatch'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)
        archive(self.standalone_path, self.standalone_files)
        self.standalone_path.with_suffix('.zip.sha256').write_text('0' * 64 + '  ' + self.standalone_path.name)
        with self.assertRaisesRegex(ValueError, 'external archive checksum mismatch'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)

    def test_standalone_mod_must_keep_its_locked_legacy_host_identity(self):
        self.standalone_manifest['host'] = self.plan['new_lock']['channels']['getlostin-ctr-nitrofueled-pc']
        self.standalone_files['ctrnf-p2p-manifest.json'] = json_bytes(self.standalone_manifest)
        archive(self.standalone_path, self.standalone_files)
        with self.assertRaisesRegex(ValueError, 'Standalone mod identity'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)

    def test_standalone_mod_must_use_the_tested_clean_bridge_revision(self):
        self.standalone_manifest['components']['ctrnf-p2p']['revision'] = '0' * 40
        self.standalone_files['ctrnf-p2p-manifest.json'] = json_bytes(self.standalone_manifest)
        archive(self.standalone_path, self.standalone_files)
        with self.assertRaisesRegex(ValueError, 'Mod component identity'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)

    def test_dirty_or_unmanifested_standalone_mod_is_rejected(self):
        archive(self.standalone_path, self.standalone_files | {'extra.exe': b'unmanifested'})
        with self.assertRaisesRegex(ValueError, 'Standalone mod identity'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)
        self.standalone_manifest['build']['source_dirty'] = True
        self.standalone_files['ctrnf-p2p-manifest.json'] = json_bytes(self.standalone_manifest)
        archive(self.standalone_path, self.standalone_files)
        with self.assertRaisesRegex(ValueError, 'Standalone mod identity'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)

    def test_both_full_archive_and_embedded_mod_bind_the_exact_standalone_zip(self):
        for channel in publisher.CHANNELS:
            for target in ('outer', 'embedded'):
                with self.subTest(channel=channel, target=target):
                    _, files = self.binaries[channel]
                    original = dict(files)
                    if target == 'outer':
                        manifest = json.loads(files['p2p-distribution-manifest.json'])
                        manifest['input_archives']['mod'] = '0' * 64
                        files['p2p-distribution-manifest.json'] = json_bytes(manifest)
                    else:
                        mod = json.loads(files['ctrnf-p2p-manifest.json'])
                        mod['assembly']['input_mod_sha256'] = '0' * 64
                        files['ctrnf-p2p-manifest.json'] = json_bytes(mod)
                    self.rewrite_binary(channel)
                    with self.assertRaisesRegex(ValueError, 'exact standalone mod build'):
                        publisher.validate_assets(self.root, self.plan, self.release_lock)
                    files.clear()
                    files.update(original)
                    self.rewrite_binary(channel)

    def test_matching_hash_claims_cannot_substitute_a_different_compiled_mod(self):
        self.standalone_files['ctrnf-p2p.exe'] = b'different compilation of the same source'
        self.standalone_manifest['files']['ctrnf-p2p.exe'] = sha256(self.standalone_files['ctrnf-p2p.exe'])
        self.standalone_files['ctrnf-p2p-manifest.json'] = json_bytes(self.standalone_manifest)
        archive(self.standalone_path, self.standalone_files)
        digest = sha256(self.standalone_path.read_bytes())
        for channel in publisher.CHANNELS:
            _, files = self.binaries[channel]
            manifest = json.loads(files['p2p-distribution-manifest.json'])
            manifest['input_archives']['mod'] = digest
            files['p2p-distribution-manifest.json'] = json_bytes(manifest)
            mod = json.loads(files['ctrnf-p2p-manifest.json'])
            mod['assembly']['input_mod_sha256'] = digest
            files['ctrnf-p2p-manifest.json'] = json_bytes(mod)
            self.rewrite_binary(channel)
        with self.assertRaisesRegex(ValueError, 'Embedded mod payload differs'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)


class FakeRefs:
    def __init__(self, plan, events):
        self.plan, self.events = plan, events
        self.bridge = plan['base_revision']
        self.bridge_race, self.lost_response = False, False

    def heads(self):
        return self.bridge

    def promote_bridge(self, plan):
        self.events.append('promote-bridge')
        if self.bridge_race:
            self.bridge = 'f' * 40
            raise ValueError('lease rejected')
        self.bridge = plan['candidate_revision']
        if self.lost_response:
            raise ValueError('response lost')


class FakeRelease:
    def __init__(self, events):
        self.events, self.uploaded = events, {}
        self.failure = None

    def read(self):
        return {'id': 123, 'assets': list(self.uploaded.values())}

    def verify(self, asset, expected):
        if asset != expected:
            raise ValueError('Existing release asset differs')

    def ensure_asset(self, path, expected):
        self.events.append('upload:' + path.name)
        if self.failure == path.name:
            raise ValueError('upload interrupted')
        if path.name in self.uploaded:
            self.verify(self.uploaded[path.name], expected)
        self.uploaded[path.name] = expected

    def notes(self, plan, receipt_name):
        self.events.append('notes')


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan, self.events = fixture_plan(), []
        self.assets = []
        for name in ('b-windows-x64.zip', 'a-source.zip'):
            path = self.root / name
            path.write_bytes(name.encode())
            self.assets.append(path)
        self.refs, self.release = FakeRefs(self.plan, self.events), FakeRelease(self.events)
        self.state, self.state_revision = None, None
        self.read_patch = patch.object(publisher.automation_state, 'read_state', self.read_state)
        self.write_patch = patch.object(publisher.automation_state, 'write_state', self.write_state)
        self.env_patch = patch.dict(os.environ, {'GITHUB_RUN_ID': '55', 'GH_REPO': 'example/bridge'})
        for item in (self.read_patch, self.write_patch, self.env_patch):
            item.start()
            self.addCleanup(item.stop)

    def read_state(self):
        return copy.deepcopy(self.state), self.state_revision

    def write_state(self, document, expected):
        self.assertEqual(expected, self.state_revision)
        self.events.append('state:' + document['status'])
        self.state = copy.deepcopy(document)
        self.state_revision = str(int(self.state_revision or '0') + 1)
        return self.state_revision

    def publish(self, **kwargs):
        return publisher.publish(self.plan, self.assets, self.refs, self.release, **kwargs)

    def test_success_orders_pending_sources_main_completion_and_retains_run(self):
        result = self.publish()
        self.assertEqual(self.events[:3], ['state:pending', 'upload:a-source.zip', 'upload:b-windows-x64.zip'])
        self.assertLess(self.events.index('promote-bridge'), self.events.index('notes'))
        self.assertEqual(self.events[-1], 'state:completed')
        self.assertEqual(result['source_run_id'], '55')
        self.assertEqual(result['completion']['revision'], self.plan['candidate_revision'])
        self.assertFalse(any('host' in event or 'tag' in event for event in self.events))

    def test_publish_pinned_uploads_without_any_main_promotion(self):
        self.plan.update(changed=False, candidate_revision=self.plan['base_revision'])
        self.assertEqual(self.publish()['status'], 'completed')
        self.assertNotIn('promote-bridge', self.events)
        self.assertIn('notes', self.events)

    def test_resume_reconstructs_from_p2p_candidate_and_replays_both_recipes(self):
        self.state = {'status': 'pending', 'plan': self.plan}
        self.refs.bridge = self.plan['candidate_revision']
        with patch.object(publisher.prepare, 'clean', return_value=self.plan['candidate_revision']), \
                patch.object(publisher.prepare, 'git') as git, \
                patch.object(publisher.prepare, 'apply_bridge') as bridge, \
                patch.object(publisher.prepare, 'prepare_host') as host:
            publisher.materialize_candidates(self.plan, self.root, self.refs, resume=True)
        git.assert_called_once_with(self.root, 'checkout', '--detach', self.plan['base_revision'])
        bridge.assert_called_once_with(self.plan, self.root)
        self.assertEqual(host.call_count, 2)
        self.assertTrue(all(call.args[2] == self.root for call in host.call_args_list))

    def test_resume_never_checks_out_over_an_unrelated_main_commit(self):
        self.state = {'status': 'pending', 'plan': self.plan}
        with patch.object(publisher.prepare, 'clean', return_value='f' * 40), \
                patch.object(publisher.prepare, 'git') as git:
            with self.assertRaisesRegex(ValueError, 'outside the pending plan'):
                publisher.materialize_candidates(self.plan, self.root, self.refs, resume=True)
        git.assert_not_called()

    def test_upload_failure_stops_before_any_ref_and_can_resume_exact_original_bytes(self):
        self.release.failure = 'b-windows-x64.zip'
        with self.assertRaisesRegex(ValueError, 'interrupted'):
            self.publish()
        self.assertEqual(self.state['status'], 'pending')
        self.assertNotIn('promote-bridge', self.events)
        self.release.failure = None
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '99'}):
            result = self.publish(resume=True)
        self.assertEqual(result['source_run_id'], '55')

    def test_resume_rejects_newly_built_bytes_before_any_upload(self):
        self.release.failure = 'a-source.zip'
        with self.assertRaises(ValueError):
            self.publish()
        self.events.clear()
        self.assets[0].write_bytes(b'rebuilt differently')
        with self.assertRaisesRegex(ValueError, 'original pending plan'):
            self.publish(resume=True)
        self.assertEqual(self.events, [])

    def test_main_lease_race_preserves_the_other_writer_and_pending_transaction(self):
        self.refs.bridge_race = True
        with self.assertRaisesRegex(ValueError, 'main promotion failed'):
            self.publish()
        self.assertEqual(self.refs.bridge, 'f' * 40)
        self.assertEqual(self.state['status'], 'pending')
        self.assertNotIn('notes', self.events)

    def test_lost_main_push_response_is_verified_from_remote_main(self):
        self.refs.lost_response = True
        self.assertEqual(self.publish()['status'], 'completed')

    def test_unrelated_main_stops_before_state_or_asset_writes(self):
        self.refs.bridge = 'f' * 40
        with self.assertRaisesRegex(ValueError, 'changed outside this plan'):
            self.publish()
        self.assertEqual(self.events, [])

    def test_existing_asset_collision_stops_before_state_and_publication(self):
        self.release.uploaded[self.assets[0].name] = {'name': self.assets[0].name, 'sha256': 'wrong'}
        with self.assertRaisesRegex(ValueError, 'Existing release asset differs'):
            self.publish()
        self.assertEqual(self.events, [])

    def test_post_promotion_failure_resumes_without_repromoting_main(self):
        with patch.object(self.release, 'notes', side_effect=ValueError('notes failed')):
            with self.assertRaisesRegex(ValueError, 'notes failed'):
                self.publish()
        self.assertEqual(self.state['status'], 'pending')
        self.assertEqual(self.refs.bridge, self.plan['candidate_revision'])
        count = self.events.count('promote-bridge')
        self.assertEqual(self.publish(resume=True)['status'], 'completed')
        self.assertEqual(self.events.count('promote-bridge'), count)


class RemoteAssetTests(unittest.TestCase):
    def test_existing_hash_collision_never_invokes_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.zip'
            path.write_bytes(b'ours')
            release = publisher.GitHubRelease('example/bridge', 'v0.1.0')
            remote = {'name': path.name, 'size': 4, 'state': 'uploaded', 'digest': 'sha256:' + '0' * 64}
            with patch.object(release, 'read', return_value={'assets': [remote]}), patch.object(publisher, 'command') as command:
                with self.assertRaisesRegex(ValueError, 'never be overwritten'):
                    release.ensure_asset(path, publisher.asset_record(path))
                command.assert_not_called()

    def test_release_notes_preserve_all_text_outside_owned_block(self):
        release = publisher.GitHubRelease('example/bridge', 'v0.1.0')
        original = 'Original author notices.\n\n' + publisher.BLOCK_START + '\nold\n' + publisher.BLOCK_END + '\nHuman footer.'
        with patch.object(release, 'read', return_value={'id': 123, 'body': original}), patch.object(publisher, 'api') as api:
            release.notes(fixture_plan(), 'receipt.json')
        updated = api.call_args.kwargs['body']['body']
        self.assertTrue(updated.startswith('Original author notices.\n\n'))
        self.assertTrue(updated.endswith('\nHuman footer.'))
        self.assertEqual(updated.count(publisher.BLOCK_START), 1)
        self.assertIn('Standalone compiled mod for manual installation', updated)
        self.assertIn('requires a compatible host', updated)
        self.assertIn('ctrnf-p2p-mod-v0.1.0-preview.1-windows-x64-' + 'b' * 12 + '.zip', updated)


class WriteAccessTests(unittest.TestCase):
    def test_only_p2p_main_is_probed_with_dry_run_and_explicit_lease(self):
        plan = fixture_plan()
        refs = publisher.GitRefs('bridge', 'example/bridge')
        with patch.object(refs, 'git') as git:
            refs.verify_write_access(plan)
        git.assert_called_once_with(refs.repository, 'push', '--dry-run',
            '--force-with-lease=refs/heads/main:' + plan['base_revision'],
            refs.bridge_url, plan['base_revision'] + ':refs/heads/main')
        self.assertFalse(hasattr(refs, 'promote_hosts'))
        self.assertFalse(hasattr(refs, 'host_url'))

    def test_denied_write_authorization_fails_verification(self):
        refs = publisher.GitRefs('bridge', 'example/bridge')
        with patch.object(refs, 'git', side_effect=ValueError('receive-pack denied')) as git:
            with self.assertRaisesRegex(ValueError, 'receive-pack denied'):
                refs.verify_write_access(fixture_plan())
        self.assertEqual(git.call_count, 1)


class GitLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.local, self.remote = self.root / 'local', self.root / 'remote.git'
        self.local.mkdir()
        self.git('init', '-q')
        publisher.command('git', 'init', '-q', '--bare', self.remote)
        self.commits = []
        for number in range(3):
            (self.local / 'fixture.txt').write_text(str(number))
            self.git('add', 'fixture.txt')
            self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                     'commit', '-qm', 'fixture ' + str(number))
            self.commits.append(self.git('rev-parse', 'HEAD'))
        self.plan = fixture_plan()
        self.plan.update(base_revision=self.commits[0], candidate_revision=self.commits[1])
        self.git('push', self.remote, self.commits[0] + ':refs/heads/main')
        # Historical branches and tags must survive the migration untouched.
        self.git('push', self.remote, self.commits[0] + ':refs/heads/p2p/channel-a',
                 self.commits[0] + ':refs/tags/v0.1.0-preview.1')
        self.refs = publisher.GitRefs(self.local, 'example/bridge')
        self.refs.bridge_url = str(self.remote)

    def git(self, *args):
        return publisher.command('git', '-C', self.local, *args)

    def test_real_promotion_changes_only_main_and_preserves_history(self):
        before = self.refs.refs(self.local, self.remote)
        self.refs.promote_bridge(self.plan)
        after = self.refs.refs(self.local, self.remote)
        self.assertEqual(after, before | {'refs/heads/main': self.commits[1]})
        self.assertEqual(self.refs.heads(), self.commits[1])

    def test_real_write_access_probe_leaves_all_refs_unchanged(self):
        before = self.refs.refs(self.local, self.remote)
        self.refs.verify_write_access(self.plan)
        self.assertEqual(self.refs.refs(self.local, self.remote), before)

    def test_real_concurrent_change_rejects_promotion_without_overwrite(self):
        self.git('push', self.remote, self.commits[2] + ':refs/heads/main')
        before = self.refs.refs(self.local, self.remote)
        with self.assertRaises(ValueError):
            self.refs.promote_bridge(self.plan)
        self.assertEqual(self.refs.refs(self.local, self.remote), before)


if __name__ == '__main__':
    unittest.main()
