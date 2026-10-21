from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import automation_prepare as automation


class AutomationPreparationTests(unittest.TestCase):
    timestamp = '2026-10-21T12:30:00Z'
    identity = {'name': 'Fixture Maintainer', 'email': 'maintainer@example.invalid'}
    controlled = 'https://github.com/fixture/integration.git'

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.seed = self.root / 'seed'
        self.initialize(self.seed)
        self.write(self.seed, '.gitignore', '/out/\n')
        self.write(self.seed, 'runtime.txt', 'upstream runtime\n')
        self.base = self.commit(self.seed, 'Upstream release one')
        self.git(self.seed, 'tag', 'v1')
        self.git(self.seed, 'switch', '-qc', 'p2p/channel-a')
        self.write(self.seed, 'platform/psn/api.h', 'public adapter API\n')
        self.write(self.seed, 'runtime.txt', 'optional adapter runtime\n')
        self.commit(self.seed, 'Add optional adapter')
        self.write(self.seed, 'integration.txt', 'Adapter documentation\n')
        self.integration = self.commit(self.seed, 'Describe integration')
        self.psn_tree = self.git(self.seed, 'rev-parse', 'HEAD:platform/psn')
        self.git(self.seed, 'branch', 'p2p/channel-b')
        self.git(self.seed, 'switch', '-qc', 'upstream-next', self.base)
        self.write(self.seed, 'upstream.txt', 'new upstream behavior\n')
        self.upstream = self.commit(self.seed, 'Upstream release two')
        self.git(self.seed, 'tag', '-a', 'v2', '-m', 'Release two')
        self.git(self.seed, 'switch', '-q', 'main')
        self.lock = {'schema_version': 1, 'channels': {}}
        for channel in automation.CHANNELS:
            self.lock['channels'][channel] = dict(repository=self.controlled,
                branch='p2p/' + channel, revision=self.integration, psn_tree=self.psn_tree,
                host_mode='psn' if channel == 'channel-a' else 'octr', launcher='host.exe',
                portable_root='portable', upstream=dict(
                    repository='https://github.com/fixture/official-' + channel[-1] + '.git',
                    tag='v1', revision=self.base))
        self.host = self.clone_host('host')
        self.bridge = self.root / 'bridge'
        self.initialize(self.bridge)
        self.write(self.bridge, '.gitignore', '/out/\n')
        self.write(self.bridge, 'unrelated.txt', 'Keep this source unchanged.\n')
        (self.bridge / 'distribution-lock.json').write_bytes(automation.json_bytes(self.lock))
        (self.bridge / 'automation.json').write_bytes(automation.json_bytes(dict(
            schema_version=1, release_tag='v0.1.0-preview.1', host_repository='fixture/integration',
            notification_assignee='fixture', commit_identity=self.identity)))
        self.bridge_base = self.commit(self.bridge, 'Pin initial distribution')

    def git(self, repo, *args):
        return subprocess.check_output(['git', '-C', str(repo), *map(str, args)],
                                       text=True, stderr=subprocess.PIPE).strip()

    def configure(self, repo):
        for name, value in (('user.name', 'Fixture Author'), ('user.email', 'author@example.invalid'),
                            ('commit.gpgsign', 'false'), ('core.autocrlf', 'false'),
                            ('protocol.file.allow', 'always')):
            self.git(repo, 'config', name, value)

    def initialize(self, repo):
        repo.mkdir()
        self.git(repo, 'init', '-q', '-b', 'main')
        self.configure(repo)

    def write(self, repo, name, value):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')

    def commit(self, repo, message):
        self.git(repo, 'add', '.')
        self.git(repo, 'commit', '-qm', message)
        return self.git(repo, 'rev-parse', 'HEAD')

    def clone_host(self, name):
        destination = self.root / name
        self.git(self.root, '-c', 'core.autocrlf=false', 'clone', '-q', '--no-hardlinks', self.seed, destination)
        self.configure(destination)
        self.git(destination, 'remote', 'set-url', 'origin', self.controlled)
        for channel in automation.CHANNELS:
            self.git(destination, 'config', '--add', 'url.' + self.seed.as_uri() + '.insteadOf',
                     'https://github.com/fixture/official-' + channel[-1] + '.git')
        return destination

    def clone_bridge(self, name='bridge-copy'):
        destination = self.root / name
        self.git(self.root, '-c', 'core.autocrlf=false', 'clone', '-q', '--no-hardlinks', self.bridge, destination)
        self.configure(destination)
        return destination

    def reports(self, changed=True):
        result = {}
        for channel in automation.CHANNELS:
            old = self.lock['channels'][channel]['upstream']
            updated = changed and channel == 'channel-a'
            result[channel] = dict(schema_version=1, channel=channel, read_only=True,
                status='changed' if updated else 'unchanged', locked_upstream=deepcopy(old),
                upstream_repository=old['repository'], upstream_tag='v2' if updated else 'v1',
                upstream_revision=self.upstream if updated else self.base)
        return result

    def plan(self, changed=True, **kwargs):
        return automation.plan(self.bridge, self.host, self.reports(changed), self.timestamp, **kwargs)

    def preserved(self, repo):
        return (self.git(repo, 'rev-parse', 'HEAD'), self.git(repo, 'branch', '--show-current'),
                self.git(repo, 'status', '--porcelain'), self.git(repo, 'write-tree'))

    def test_replay_and_bridge_commit_are_identical_in_independent_clones(self):
        original_bridge, original_host = self.preserved(self.bridge), self.preserved(self.host)
        original_lock = (self.bridge / 'distribution-lock.json').read_bytes()
        receipt = self.plan()
        self.assertEqual(self.preserved(self.bridge), original_bridge)
        self.assertEqual(self.preserved(self.host), original_host)
        self.assertEqual((self.bridge / 'distribution-lock.json').read_bytes(), original_lock)
        self.assertTrue(receipt['changed'])
        self.assertEqual(receipt['channels']['channel-b']['candidate_revision'], self.integration)
        other_host, other_bridge = self.clone_host('host-copy'), self.clone_bridge()
        host_result = automation.prepare_host(receipt, 'channel-a', other_host)
        candidate = Path(host_result['host_source'])
        self.assertEqual(candidate.parent, other_host / 'out/worktrees')
        self.assertEqual(host_result['candidate_revision'], receipt['channels']['channel-a']['candidate_revision'])
        self.assertEqual(host_result['psn_tree'], self.psn_tree)
        self.assertEqual(self.git(candidate, 'status', '--porcelain'), '')
        self.assertEqual(self.git(candidate, 'show', '-s', '--format=%an <%ae>'), 'Fixture Author <author@example.invalid>')
        self.assertEqual(self.git(candidate, 'show', '-s', '--format=%cn <%ce>'), 'Fixture Maintainer <maintainer@example.invalid>')
        self.assertEqual(self.git(candidate, 'show', '-s', '--format=%cI').replace('Z', '+00:00'),
                         '2026-10-21T12:30:00+00:00')
        bridge_result = automation.apply_bridge(receipt, other_bridge)
        self.assertTrue(bridge_result['clean_source'])
        self.assertEqual(self.git(other_bridge, 'branch', '--show-current'), '')
        self.assertEqual(self.git(other_bridge, 'rev-parse', 'HEAD'), receipt['candidate_revision'])
        self.assertEqual(self.git(other_bridge, 'status', '--porcelain'), '')
        self.assertEqual(self.git(other_bridge, 'diff-tree', '--no-commit-id', '--name-only', '-r',
                                  self.bridge_base, 'HEAD'), 'distribution-lock.json')
        self.assertEqual(self.git(other_bridge, 'show', '-s', '--format=%aI%n%cI').replace('Z', '+00:00'),
                         '2026-10-21T12:30:00+00:00\n2026-10-21T12:30:00+00:00')
        self.assertEqual(json.loads((other_bridge / 'distribution-lock.json').read_bytes()), receipt['new_lock'])
        self.assertEqual(self.preserved(self.bridge), original_bridge)
        self.assertEqual(self.preserved(self.host), original_host)

    def test_unchanged_verification_creates_no_bridge_commit_and_reuses_clean_pinned_host(self):
        receipt = self.plan(False, verify=True)
        self.assertFalse(receipt['changed'])
        self.assertTrue(receipt['verify'])
        self.assertEqual(receipt['candidate_revision'], self.bridge_base)
        self.git(self.host, 'checkout', '--detach', self.integration)
        result = automation.prepare_host(receipt, 'channel-b', self.host)
        self.assertEqual(Path(result['host_source']), self.host)
        self.assertFalse((self.host / 'out/worktrees').exists())
        other = self.clone_bridge()
        automation.apply_bridge(receipt, other)
        self.assertEqual(self.git(other, 'rev-parse', 'HEAD'), self.bridge_base)
        self.assertEqual(self.git(other, 'rev-list', '--count', 'HEAD'), '1')

    def test_unchanged_channel_preserves_other_checkout_and_uses_detached_worktree(self):
        receipt = self.plan(False)
        before = self.preserved(self.host)
        result = automation.prepare_host(receipt, 'channel-b', self.host)
        self.assertEqual(self.preserved(self.host), before)
        candidate = Path(result['host_source'])
        self.assertEqual(candidate.parent, self.host / 'out/worktrees')
        self.assertEqual(self.git(candidate, 'rev-parse', 'HEAD'), self.integration)
        self.assertEqual(self.git(candidate, 'branch', '--show-current'), '')

    def test_fingerprint_coalesces_retries_but_commit_dates_are_explicit(self):
        first = self.plan()
        second = automation.plan(self.bridge, self.host, self.reports(), '2026-10-22T12:30:00Z')
        self.assertEqual(first['fingerprint'], second['fingerprint'])
        self.assertNotEqual(first['candidate_revision'], second['candidate_revision'])
        self.assertNotEqual(first['channels']['channel-a']['candidate_revision'],
                            second['channels']['channel-a']['candidate_revision'])

    def test_stale_remote_heads_and_wrong_origin_are_rejected_before_replay(self):
        self.git(self.host, 'update-ref', 'refs/remotes/origin/p2p/channel-a', self.base)
        with self.assertRaisesRegex(ValueError, 'Fetched host channel head differs'):
            self.plan()
        self.assertFalse((self.host / 'out/worktrees').exists())
        self.git(self.host, 'update-ref', 'refs/remotes/origin/p2p/channel-a', self.integration)
        self.git(self.host, 'remote', 'set-url', 'origin', 'https://github.com/another/host.git')
        with self.assertRaisesRegex(ValueError, 'origin is not'):
            self.plan()

    def test_stale_release_report_cannot_change_lock(self):
        reports = self.reports()
        reports['channel-a']['locked_upstream']['revision'] = 'a' * 40
        before = self.preserved(self.bridge)
        with self.assertRaisesRegex(ValueError, 'Release report is stale'):
            automation.plan(self.bridge, self.host, reports, self.timestamp)
        self.assertEqual(self.preserved(self.bridge), before)
        self.assertFalse((self.host / 'out/worktrees').exists())

    def test_dirty_and_advanced_bridge_bases_are_refused(self):
        receipt = self.plan()
        dirty = self.clone_bridge('dirty')
        self.write(dirty, 'unrelated.txt', 'uncommitted work\n')
        with self.assertRaisesRegex(ValueError, 'clean checkout'):
            automation.apply_bridge(receipt, dirty)
        self.assertEqual(self.git(dirty, 'rev-parse', 'HEAD'), self.bridge_base)
        advanced = self.clone_bridge('advanced')
        self.write(advanced, 'unrelated.txt', 'new committed work\n')
        new_base = self.commit(advanced, 'New base')
        with self.assertRaisesRegex(ValueError, 'not at the plan base'):
            automation.apply_bridge(receipt, advanced)
        self.assertEqual(self.git(advanced, 'rev-parse', 'HEAD'), new_base)

    def test_candidate_sha_and_lock_provenance_tampering_are_rejected(self):
        receipt = self.plan()
        other = self.clone_bridge()
        tampered = deepcopy(receipt)
        tampered['candidate_revision'] = 'a' * 40
        with self.assertRaisesRegex(ValueError, 'bridge candidate does not match'):
            automation.apply_bridge(tampered, other)
        self.assertEqual(self.git(other, 'rev-parse', 'HEAD'), self.bridge_base)
        tampered = deepcopy(receipt)
        tampered['new_lock']['channels']['channel-a']['host_mode'] = 'octr'
        with self.assertRaisesRegex(ValueError, 'Only channel/upstream revisions'):
            automation.apply_bridge(tampered, other)
        tampered = deepcopy(receipt)
        tampered['new_lock']['channels']['channel-a']['revision'] = 'a' * 40
        tampered['channels']['channel-a']['candidate_revision'] = 'a' * 40
        with self.assertRaisesRegex(ValueError, 'host candidate does not match'):
            automation.prepare_host(tampered, 'channel-a', self.clone_host('host-copy'))

    def test_resume_reconstructs_after_caller_validates_partially_published_refs(self):
        receipt = self.plan()
        candidate = receipt['channels']['channel-a']['candidate_revision']
        self.git(self.host, 'update-ref', 'refs/remotes/origin/p2p/channel-a', candidate)
        with self.assertRaisesRegex(ValueError, 'Fetched host channel head differs'):
            automation.prepare_host(receipt, 'channel-a', self.host)
        result = automation.prepare_host(receipt, 'channel-a', self.host, validate_remote=False)
        self.assertEqual(result['candidate_revision'], candidate)
        self.assertEqual(self.git(self.host, 'rev-parse', 'refs/remotes/origin/p2p/channel-a'), candidate)

    def test_upstream_psn_changes_are_retained_but_not_automatically_promoted(self):
        self.git(self.seed, 'switch', '-q', 'upstream-next')
        self.write(self.seed, 'platform/psn/upstream.h', 'new upstream interface\n')
        changed = self.commit(self.seed, 'Upstream adds a PSN module')
        self.git(self.seed, 'tag', 'v3')
        reports = self.reports()
        reports['channel-a'].update(upstream_tag='v3', upstream_revision=changed)
        before = self.preserved(self.bridge)
        with self.assertRaisesRegex(ValueError, 'changed the shared PSN tree') as caught:
            automation.plan(self.bridge, self.host, reports, self.timestamp)
        self.assertTrue(Path(caught.exception.candidate['candidate_worktree']).is_dir())
        self.assertEqual(self.preserved(self.bridge), before)

    def test_conflict_retains_candidate_and_leaves_bridge_clean(self):
        self.git(self.seed, 'switch', '-q', 'upstream-next')
        self.write(self.seed, 'runtime.txt', 'incompatible upstream runtime\n')
        changed = self.commit(self.seed, 'Conflicting upstream change')
        self.git(self.seed, 'tag', 'v3')
        reports = self.reports()
        reports['channel-a'].update(upstream_tag='v3', upstream_revision=changed)
        with self.assertRaisesRegex(ValueError, 'did not produce a clean candidate') as caught:
            automation.plan(self.bridge, self.host, reports, self.timestamp)
        retained = caught.exception.candidate
        self.assertEqual(retained['status'], 'conflict')
        self.assertIn('runtime.txt', retained['conflicts'])
        self.assertTrue(Path(retained['candidate_worktree']).is_dir())
        self.assertEqual(self.git(self.bridge, 'status', '--porcelain'), '')
        self.assertEqual(self.git(self.bridge, 'rev-parse', 'HEAD'), self.bridge_base)

    def test_output_cannot_overwrite_inputs_tracked_files_or_dirty_source_checkout(self):
        for name in ('distribution-lock.json', 'unrelated.txt', 'receipt.json'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'ignored untracked path'):
                automation.output_destination(self.bridge / name, [self.bridge], [])
        reports = self.root / 'reports.json'
        with self.assertRaisesRegex(ValueError, 'replace an input'):
            automation.output_destination(reports, [self.bridge], [reports])
        self.assertEqual(automation.output_destination(self.bridge / 'out/plan.json', [self.bridge], []),
                         self.bridge / 'out/plan.json')

    def test_cli_plan_and_materialization_produce_machine_readable_receipts(self):
        script = Path(automation.__file__).resolve()
        reports, planned = self.root / 'reports.json', self.root / 'plan.json'
        reports.write_bytes(automation.json_bytes(self.reports()))
        subprocess.run([sys.executable, '-B', str(script), 'plan', '--repository', str(self.bridge),
            '--host-source', str(self.host), '--reports', str(reports), '--timestamp', self.timestamp,
            '--output', str(planned)], check=True, capture_output=True, text=True)
        receipt = json.loads(planned.read_bytes())
        bridge = self.clone_bridge()
        host = self.clone_host('host-copy')
        bridge_output, host_output = self.root / 'bridge-result.json', self.root / 'host-result.json'
        for operation, arguments, output in (
                ('materialize-bridge', ['--repository', str(bridge)], bridge_output),
                ('materialize-host', ['--host-source', str(host), '--channel', 'channel-a'], host_output)):
            completed = subprocess.run([sys.executable, '-B', str(script), operation, *arguments,
                '--plan', str(planned), '--output', str(output)], check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(completed.stdout), json.loads(output.read_bytes()))
        self.assertEqual(json.loads(bridge_output.read_bytes())['candidate_revision'], receipt['candidate_revision'])
        self.assertEqual(json.loads(host_output.read_bytes())['candidate_revision'],
                         receipt['channels']['channel-a']['candidate_revision'])


if __name__ == '__main__':
    unittest.main()
