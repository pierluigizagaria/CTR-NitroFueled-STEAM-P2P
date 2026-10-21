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


def fixture_plan():
    pins, channels = {}, {}
    for index, channel in enumerate(publisher.CHANNELS):
        pins[channel] = {'repository': 'https://github.com/example/hosts.git', 'branch': 'p2p/' + channel,
                         'revision': str(index + 3) * 40, 'psn_tree': '7' * 40, 'host_mode': 'psn',
                         'launcher': 'launcher.exe', 'portable_root': 'portable',
                         'upstream': {'repository': 'https://github.com/example/upstream.git',
                                      'tag': 'v2.0', 'revision': '9' * 40}}
        channels[channel] = {'expected_old_revision': str(index + 1) * 40,
                             'candidate_revision': pins[channel]['revision'], 'psn_tree': '7' * 40,
                             'upstream': pins[channel]['upstream'], 'changed': True}
    return {'schema_version': 1, 'base_revision': 'a' * 40, 'candidate_revision': 'b' * 40,
            'channels': channels, 'new_lock': {'schema_version': 1, 'channels': pins},
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
            'steam_runtime': {'sha256': sha256(b'permitted runtime')}}
        self.sources, self.binaries = {}, {}
        for channel in publisher.CHANNELS:
            pin = self.plan['new_lock']['channels'][channel]
            prefix = f"ctrnf-p2p-{channel}-{self.plan['version']}-{self.plan['candidate_revision'][:12]}"
            source_payload = {'host/LICENSE': b'GPL', 'distribution-lock.json': json_bytes(self.plan['new_lock']),
                              'build-recipes/release-lock.json': json_bytes(self.release_lock)}
            source = {'component': 'ctrnf-p2p-host-source', 'channel': channel, 'host': pin,
                      'revision': pin['revision'], 'psn_tree': pin['psn_tree'], 'redistribution_ready': True,
                      'dependency_evidence_complete': True,
                      'build_recipe': {'revision': self.plan['candidate_revision'], 'source_dirty': False},
                      'files': {name: sha256(data) for name, data in source_payload.items()}}
            source_payload['source-manifest.json'] = json_bytes(source)
            source_path = self.root / (prefix + '-source.zip')
            archive(source_path, source_payload)
            native_files = {'launcher.exe': b'launcher', 'bin/sacredfire.exe': b'host',
                            'bin/bb-gpu-capabilities.exe': b'caps', 'psn-bridge-backend.dll': b'backend'}
            build = {'source_revision': pin['revision'], 'shared_psn_tree': pin['psn_tree'],
                     'clean_source': True, 'binaries': {name: sha256(data) for name, data in native_files.items()}}
            components = copy.deepcopy(self.release_lock['components'])
            components.update({'ctrnf-p2p': {'revision': self.plan['candidate_revision'], 'license': 'MIT'},
                               'steamworks-runtime': {'sha256': sha256(b'permitted runtime')}})
            files = native_files | {'steam_api64.dll': b'permitted runtime',
                                    'p2p-host-build.json': json_bytes(build)}
            mod = {'host': pin, 'components': components, 'version': self.plan['version'],
                   'build': {'source_dirty': False}, 'files': {'steam_api64.dll': sha256(b'permitted runtime')}}
            files['ctrnf-p2p-manifest.json'] = json_bytes(mod)
            manifest = {'component': 'ctrnf-p2p-distribution', 'channel': channel, 'host': pin,
                        'version': self.plan['version'], 'platform': 'windows-x64', 'host_build': build,
                        'components': components, 'build': {'source_dirty': False}, 'redistribution_ready': True,
                        'unresolved_runtime_dependencies': [],
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
        self.assertEqual(len(assets), 8)
        self.assertTrue(all('-source.zip' in asset.name for asset in assets[:4]))

    def test_rejects_self_consistent_package_for_a_different_host_plan(self):
        plan = copy.deepcopy(self.plan)
        plan['new_lock']['channels']['channel-a']['upstream']['tag'] = 'v3.0'
        with self.assertRaisesRegex(ValueError, 'Host identity'):
            publisher.validate_assets(self.root, plan, self.release_lock)

    def test_rejects_extra_payload_even_if_other_checksums_are_valid(self):
        path, files = self.binaries['channel-a']
        archive(path, files | {'unexpected.exe': b'not covered'})
        with self.assertRaisesRegex(ValueError, 'manifested payload'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)

    def test_rejects_an_unreviewed_component_even_with_valid_package_hashes(self):
        different_lock = copy.deepcopy(self.release_lock)
        different_lock['components']['orbisteamworks']['revision'] = '0' * 40
        with self.assertRaisesRegex(ValueError, 'Component differs'):
            publisher.validate_assets(self.root, self.plan, different_lock)

    def test_rejects_binary_receipt_not_bound_to_payload(self):
        path, files = self.binaries['channel-a']
        manifest = json.loads(files['p2p-distribution-manifest.json'])
        manifest['host_build']['binaries']['launcher.exe'] = '0' * 64
        files['p2p-distribution-manifest.json'] = json_bytes(manifest)
        archive(path, files)
        with self.assertRaisesRegex(ValueError, 'Host binary differs'):
            publisher.validate_assets(self.root, self.plan, self.release_lock)


class FakeRefs:
    def __init__(self, plan, events):
        self.plan, self.events = plan, events
        self.hosts = {channel: plan['channels'][channel]['expected_old_revision'] for channel in publisher.CHANNELS}
        self.bridge = plan['base_revision']
        self.bridge_race, self.rollback_race, self.lost_response = False, False, False

    def heads(self):
        return dict(self.hosts), self.bridge

    def promote_hosts(self, plan):
        self.events.append('promote-hosts')
        self.hosts = {channel: plan['channels'][channel]['candidate_revision'] for channel in publisher.CHANNELS}

    def verify_source_tags(self, plan):
        self.events.append('verify-tags')

    def promote_bridge(self, plan):
        self.events.append('promote-bridge')
        if self.bridge_race:
            self.bridge = 'f' * 40
            raise ValueError('lease rejected')
        self.bridge = plan['candidate_revision']
        if self.lost_response:
            raise ValueError('response lost')

    def rollback_hosts(self, plan):
        self.events.append('rollback-hosts')
        if self.rollback_race:
            raise ValueError('another host update')
        self.hosts = {channel: plan['channels'][channel]['expected_old_revision'] for channel in publisher.CHANNELS}


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

    def test_success_orders_pending_sources_refs_completion_and_retains_run(self):
        result = self.publish()
        self.assertEqual(self.events[:3], ['state:pending', 'upload:a-source.zip', 'upload:b-windows-x64.zip'])
        self.assertLess(self.events.index('promote-hosts'), self.events.index('promote-bridge'))
        self.assertLess(self.events.index('promote-bridge'), self.events.index('notes'))
        self.assertEqual(self.events[-1], 'state:completed')
        self.assertEqual(result['source_run_id'], '55')
        self.assertEqual(result['completion']['revision'], self.plan['candidate_revision'])

    def test_upstream_tag_change_with_identical_host_heads_still_promotes_bridge(self):
        for channel in publisher.CHANNELS:
            self.plan['channels'][channel]['candidate_revision'] = self.plan['channels'][channel]['expected_old_revision']
        result = self.publish()
        self.assertEqual(result['status'], 'completed')
        self.assertIn('promote-bridge', self.events)

    def test_explicit_retry_can_publish_current_pins_without_ref_updates(self):
        self.plan['changed'] = False
        self.plan['candidate_revision'] = self.plan['base_revision']
        for channel in publisher.CHANNELS:
            self.plan['channels'][channel]['candidate_revision'] = self.plan['channels'][channel]['expected_old_revision']
        self.assertEqual(self.publish()['status'], 'completed')
        self.assertNotIn('promote-hosts', self.events)
        self.assertNotIn('promote-bridge', self.events)

    def test_resume_after_completion_upload_keeps_receipt_identical_despite_notification(self):
        with patch.object(self.release, 'notes', side_effect=ValueError('notes failed')):
            with self.assertRaisesRegex(ValueError, 'notes failed'):
                self.publish()
        self.state['notification'] = {'issue': 5}
        self.state['incident'] = {'run': 99}
        completed = self.publish(resume=True)
        self.assertEqual(completed['status'], 'completed')
        self.assertNotIn('notification', completed)

    def test_resume_materializes_from_saved_base_after_main_was_already_promoted(self):
        self.state = {'status': 'pending', 'plan': self.plan}
        self.refs.promote_hosts(self.plan)
        self.refs.promote_bridge(self.plan)
        with patch.object(publisher.prepare, 'clean', return_value=self.plan['candidate_revision']), \
                patch.object(publisher.prepare, 'git') as git, \
                patch.object(publisher.prepare, 'apply_bridge') as bridge, \
                patch.object(publisher.prepare, 'prepare_host') as host:
            publisher.materialize_candidates(self.plan, self.root, self.root, self.refs, resume=True)
        git.assert_called_once_with(self.root, 'checkout', '--detach', self.plan['base_revision'])
        bridge.assert_called_once_with(self.plan, self.root)
        self.assertEqual(host.call_count, 2)
        self.assertTrue(all(call.kwargs == {'validate_remote': False} for call in host.call_args_list))

    def test_resume_never_checks_out_over_an_unrelated_main_commit(self):
        self.state = {'status': 'pending', 'plan': self.plan}
        with patch.object(publisher.prepare, 'clean', return_value='f' * 40), \
                patch.object(publisher.prepare, 'git') as git:
            with self.assertRaisesRegex(ValueError, 'outside the pending plan'):
                publisher.materialize_candidates(self.plan, self.root, self.root, self.refs, resume=True)
        git.assert_not_called()

    def test_upload_failure_stops_before_any_ref_and_can_resume_exact_original_bytes(self):
        self.release.failure = 'b-windows-x64.zip'
        with self.assertRaisesRegex(ValueError, 'interrupted'):
            self.publish()
        self.assertEqual(self.state['status'], 'pending')
        self.assertNotIn('promote-hosts', self.events)
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

    def test_bridge_race_rolls_back_only_host_refs_and_leaves_pending(self):
        self.refs.bridge_race = True
        with self.assertRaisesRegex(ValueError, 'restored with leases'):
            self.publish()
        self.assertEqual(self.refs.bridge, 'f' * 40)
        self.assertEqual(self.refs.hosts['channel-a'], self.plan['channels']['channel-a']['expected_old_revision'])
        self.assertEqual(self.state['status'], 'pending')
        self.assertNotIn('notes', self.events)

    def test_main_race_during_source_tag_verification_restores_hosts_before_bridge_push(self):
        def verify_with_race(plan):
            self.refs.bridge = 'f' * 40
        with patch.object(self.refs, 'verify_source_tags', side_effect=verify_with_race):
            with self.assertRaisesRegex(ValueError, 'Post-promotion checks failed; host branches were restored'):
                self.publish()
        self.assertEqual(self.refs.bridge, 'f' * 40)
        self.assertEqual(self.refs.hosts['channel-a'], self.plan['channels']['channel-a']['expected_old_revision'])
        self.assertEqual(self.state['status'], 'pending')
        self.assertNotIn('promote-bridge', self.events)
        self.assertNotIn('notes', self.events)

    def test_rollback_race_requires_manual_recovery_without_completion(self):
        self.refs.bridge_race = self.refs.rollback_race = True
        with self.assertRaisesRegex(ValueError, 'rollback was rejected'):
            self.publish()
        self.assertEqual(self.state['status'], 'pending')
        self.assertNotIn('notes', self.events)

    def test_lost_bridge_push_response_is_verified_from_remote_refs(self):
        self.refs.lost_response = True
        self.assertEqual(self.publish()['status'], 'completed')
        self.assertNotIn('rollback-hosts', self.events)

    def test_mixed_remote_refs_stop_before_state_or_asset_writes(self):
        self.refs.hosts['channel-a'] = self.plan['channels']['channel-a']['candidate_revision']
        with self.assertRaisesRegex(ValueError, 'mixed or changed'):
            self.publish()
        self.assertEqual(self.events, [])

    def test_existing_asset_collision_stops_before_state_and_publication(self):
        self.release.uploaded[self.assets[0].name] = {'name': self.assets[0].name, 'sha256': 'wrong'}
        with self.assertRaisesRegex(ValueError, 'Existing release asset differs'):
            self.publish()
        self.assertEqual(self.events, [])


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


class WriteAccessTests(unittest.TestCase):
    def test_probes_only_current_heads_with_dry_run_and_explicit_leases(self):
        plan = fixture_plan()
        refs = publisher.GitRefs('bridge', 'hosts', 'example/bridge', 'example/hosts')
        with patch.object(refs, 'git') as git:
            refs.verify_write_access(plan)
        self.assertEqual(git.call_count, 2)
        host_args, bridge_args = [call.args for call in git.call_args_list]
        self.assertEqual(host_args[:4], (refs.host_source, 'push', '--dry-run', '--atomic'))
        for channel in publisher.CHANNELS:
            sha, branch = plan['channels'][channel]['expected_old_revision'], 'refs/heads/p2p/' + channel
            self.assertIn('--force-with-lease=' + branch + ':' + sha, host_args)
            self.assertIn(sha + ':' + branch, host_args)
        self.assertEqual(bridge_args, (refs.repository, 'push', '--dry-run',
                                      '--force-with-lease=refs/heads/main:' + plan['base_revision'],
                                      refs.bridge_url, plan['base_revision'] + ':refs/heads/main'))
        self.assertFalse(any('refs/tags/' in str(arg) for arg in host_args + bridge_args))

    def test_denied_host_write_authorization_fails_verification(self):
        refs = publisher.GitRefs('bridge', 'hosts', 'example/bridge', 'example/hosts')
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
        commits = []
        for number in range(3):
            (self.local / 'fixture.txt').write_text(str(number))
            self.git('add', 'fixture.txt')
            self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                     'commit', '-qm', 'fixture ' + str(number))
            commits.append(self.git('rev-parse', 'HEAD'))
        self.plan = fixture_plan()
        for channel, candidate in zip(publisher.CHANNELS, commits[1:]):
            self.plan['channels'][channel]['expected_old_revision'] = commits[0]
            self.plan['channels'][channel]['candidate_revision'] = candidate
            self.git('push', self.remote, commits[0] + ':refs/heads/p2p/' + channel)
        self.refs = publisher.GitRefs(self.local, self.local, 'example/bridge', 'example/host')
        self.refs.host_url = str(self.remote)
        self.commits = commits

    def git(self, *args):
        return publisher.command('git', '-C', self.local, *args)

    def remote_heads(self):
        values = self.refs.refs(self.local, self.remote, 'refs/heads/p2p/*')
        return {channel: values['refs/heads/p2p/' + channel] for channel in publisher.CHANNELS}

    def test_real_atomic_push_preserves_source_tags_and_rolls_back_with_leases(self):
        self.refs.promote_hosts(self.plan)
        self.refs.verify_source_tags(self.plan)
        self.assertEqual(self.remote_heads(), {channel: self.plan['channels'][channel]['candidate_revision']
                                             for channel in publisher.CHANNELS})
        self.refs.rollback_hosts(self.plan)
        self.assertEqual(set(self.remote_heads().values()), {self.commits[0]})
        self.refs.verify_source_tags(self.plan)

    def test_real_write_access_probe_leaves_all_remote_refs_unchanged(self):
        self.refs.bridge_url = str(self.remote)
        self.plan['base_revision'] = self.commits[0]
        self.git('push', self.remote, self.commits[0] + ':refs/heads/main')
        before = self.refs.refs(self.local, self.remote)
        self.refs.verify_write_access(self.plan)
        self.assertEqual(self.refs.refs(self.local, self.remote), before)
        self.assertEqual(set(before), {'refs/heads/main', 'refs/heads/p2p/channel-a', 'refs/heads/p2p/channel-b'})

    def test_real_concurrent_change_rejects_entire_atomic_promotion(self):
        self.git('push', self.remote, self.commits[1] + ':refs/heads/p2p/channel-b')
        with self.assertRaises(ValueError):
            self.refs.promote_hosts(self.plan)
        self.assertEqual(self.remote_heads(), {'channel-a': self.commits[0], 'channel-b': self.commits[1]})
        self.assertEqual(self.refs.refs(self.local, self.remote, 'refs/tags/p2p/*'), {})

    def test_real_concurrent_change_rejects_entire_rollback(self):
        self.refs.promote_hosts(self.plan)
        self.git('push', self.remote, self.commits[2] + ':refs/heads/p2p/channel-a')
        with self.assertRaises(ValueError):
            self.refs.rollback_hosts(self.plan)
        self.assertEqual(self.remote_heads(), {'channel-a': self.commits[2], 'channel-b': self.commits[2]})


if __name__ == '__main__':
    unittest.main()
