import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import prepare_upstream_update as update


class UpstreamUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / 'host'
        self.repo.mkdir()
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Fixture Author')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.autocrlf', 'false')
        self.git('config', 'protocol.file.allow', 'always')
        # Exercise the real fetch command against local Git objects, without network access.
        self.git('config', 'url.' + self.repo.as_uri() + '.insteadOf',
                 'https://github.com/fixture/official.git')
        self.write('.gitignore', '/out/\n')
        self.write('runtime.txt', 'base runtime\n')
        self.write('README.txt', 'upstream\n')
        self.base = self.commit('Upstream release one')
        self.git('tag', 'v1')
        self.lock = self.root / 'distribution-lock.json'

    def git(self, *args, repo=None):
        return subprocess.check_output(['git', '-C', str(repo or self.repo), *map(str, args)],
                                       text=True, stderr=subprocess.PIPE).strip()

    def write(self, name, data):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding='utf-8')

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def history(self, conflict=False, adopted=False):
        self.git('switch', '-qc', 'upstream-next')
        self.write('upstream.txt', 'new upstream behavior\n')
        if conflict:
            self.write('runtime.txt', 'upstream rewrite\n')
        if adopted:
            self.write('platform/psn/api.h', 'fixture public API\n')
        self.upstream = self.commit('Upstream release two')
        self.git('tag', '-a', 'v2', '-m', 'Annotated upstream tag')
        self.git('switch', '-qc', 'p2p/channel-a', self.base)
        self.write('platform/psn/api.h', 'fixture public API\n')
        if conflict:
            self.write('runtime.txt', 'integration rewrite\n')
        self.first_patch = self.commit('Add optional adapter')
        self.write('integration.txt', 'integration documentation\n')
        self.integration = self.commit('Describe integration')
        self.psn_tree = self.git('rev-parse', 'HEAD:platform/psn')
        self.pin = dict(repository='https://github.com/fixture/integration.git',
            branch='p2p/channel-a', revision=self.integration, psn_tree=self.psn_tree,
            host_mode='psn', launcher='host.exe', portable_root='portable',
            upstream=dict(repository='https://github.com/fixture/official.git',
                          tag='v1', revision=self.base))
        self.lock.write_text(json.dumps(dict(schema_version=1, channels={'channel-a': self.pin})))
        self.args = argparse.Namespace(lock=self.lock, channel='channel-a', host_source=self.repo,
                                       upstream_tag='v2', upstream_revision=self.upstream)
        self.git('switch', '-q', 'main')
        self.write('README.txt', 'unsaved local user edit\n')
        self.write('staged.txt', 'staged user edit\n')
        self.git('add', 'staged.txt')

    def preserved(self):
        return (self.git('rev-parse', 'HEAD'), self.git('branch', '--show-current'),
                self.git('status', '--porcelain'), self.git('rev-parse', 'p2p/channel-a'),
                (self.repo / 'README.txt').read_bytes(), self.lock.read_bytes())

    def test_replays_linear_series_without_changing_checkout_branch_or_lock(self):
        self.history()
        before = self.preserved()
        result = update.prepare(self.args)
        self.assertEqual(result['status'], 'prepared')
        self.assertEqual(before, self.preserved())
        candidate = Path(result['candidate_worktree'])
        self.assertEqual(candidate.parent, self.repo / 'out/worktrees')
        self.assertEqual((candidate / 'upstream.txt').read_text(), 'new upstream behavior\n')
        self.assertEqual((candidate / 'integration.txt').read_text(), 'integration documentation\n')
        self.assertFalse((candidate / 'staged.txt').exists())
        self.assertEqual(result['psn_tree'], self.psn_tree)
        self.assertEqual(self.git('rev-list', '--count', self.upstream + '..HEAD', repo=candidate), '2')
        self.assertTrue(result['candidate_branch'].startswith('p2p/candidate/channel-a-'))
        self.assertTrue(result['next_commands'])
        self.assertFalse(result['lock_modified'])

    def test_conflict_is_retained_with_sequencer_and_original_checkout_untouched(self):
        self.history(conflict=True)
        before = self.preserved()
        result = update.prepare(self.args)
        candidate = Path(result['candidate_worktree'])
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(result['conflicts'], ['runtime.txt'])
        self.assertEqual(before, self.preserved())
        self.assertIn('<<<<<<<', (candidate / 'runtime.txt').read_text())
        self.assertEqual(self.git('rev-parse', 'CHERRY_PICK_HEAD', repo=candidate), self.first_patch)
        self.assertEqual(result['next_commands'], [])
        self.assertIn('--continue', result['resume_command'])
        self.assertEqual(self.git('rev-parse', 'HEAD', repo=candidate), self.upstream)

    def test_changes_already_adopted_upstream_are_dropped(self):
        self.history(adopted=True)
        result = update.prepare(self.args)
        self.assertEqual(result['status'], 'prepared')
        candidate = Path(result['candidate_worktree'])
        self.assertEqual(self.git('rev-list', '--count', self.upstream + '..HEAD', repo=candidate), '1')
        self.assertEqual(result['psn_tree'], self.psn_tree)

    def test_mismatched_official_tag_creates_no_candidate(self):
        self.history()
        self.args.upstream_revision = self.base
        before = self.preserved()
        with self.assertRaisesRegex(ValueError, 'fetched official upstream tag'):
            update.prepare(self.args)
        self.assertEqual(before, self.preserved())
        self.assertFalse((self.repo / 'out/worktrees').exists())

    def test_input_worktree_still_places_candidate_under_owning_checkout(self):
        self.history()
        reader = self.repo / 'out/worktrees/reader'
        self.git('worktree', 'add', '--detach', reader, self.integration)
        self.args.host_source = reader
        before = self.preserved()
        result = update.prepare(self.args)
        self.assertEqual(result['status'], 'prepared')
        self.assertEqual(Path(result['candidate_worktree']).parent, reader.parent)
        self.assertEqual(self.git('rev-parse', 'HEAD', repo=reader), self.integration)
        self.assertEqual(before, self.preserved())

    def test_stale_channel_branch_is_rejected(self):
        self.history()
        self.git('update-ref', 'refs/heads/p2p/channel-a', self.base)
        with self.assertRaisesRegex(ValueError, 'channel branch differs'):
            update.prepare(self.args)
        self.assertFalse((self.repo / 'out/worktrees').exists())

    def test_non_linear_series_requires_review_before_creating_candidate(self):
        self.history()
        merged = self.git('commit-tree', self.git('rev-parse', self.integration + '^{tree}'),
                          '-p', self.integration, '-p', self.upstream, '-m', 'Fixture merge')
        self.git('update-ref', 'refs/heads/p2p/channel-a', merged)
        self.pin['revision'] = merged
        self.lock.write_text(json.dumps(dict(schema_version=1, channels={'channel-a': self.pin})))
        before = self.preserved()
        with self.assertRaisesRegex(ValueError, 'Non-linear integration history'):
            update.prepare(self.args)
        self.assertEqual(before, self.preserved())
        self.assertFalse((self.repo / 'out/worktrees').exists())

    def test_post_replay_failure_keeps_candidate_location_in_receipt(self):
        self.history()
        before = self.preserved()
        original_value = update.value

        def unavailable_tree(repo, *args):
            if Path(repo) != self.repo and args[-1].endswith(':platform/psn'):
                raise ValueError('Candidate module tree unavailable')
            return original_value(repo, *args)

        with mock.patch.object(update, 'value', side_effect=unavailable_tree):
            result = update.prepare(self.args)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(Path(result['candidate_worktree']).is_dir())
        self.assertIn('module tree unavailable', result['diagnostic'])
        self.assertEqual(result['next_commands'], [])
        self.assertEqual(before, self.preserved())

    def test_latest_peels_annotated_tag_without_git_or_local_mutation(self):
        self.history()
        before = self.preserved()
        tag_object = 'a' * 40
        with mock.patch.object(update, 'github_json', side_effect=[
                dict(tag_name='v2', draft=False, prerelease=False),
                dict(object=dict(type='tag', sha=tag_object)),
                dict(object=dict(type='commit', sha=self.upstream))]) as request, \
                mock.patch.object(update, 'git', side_effect=AssertionError('read-only check ran Git')):
            result = update.latest(self.lock, 'channel-a')
        self.assertEqual(result['status'], 'changed')
        self.assertEqual(result['upstream_revision'], self.upstream)
        self.assertTrue(result['read_only'])
        self.assertEqual(request.call_args_list[0].args,
                         ('https://api.github.com/repos/fixture/official/releases/latest',))
        self.assertEqual(before, self.preserved())

    def test_latest_reports_unchanged_release(self):
        self.history()
        with mock.patch.object(update, 'github_json', side_effect=[
                dict(tag_name='v1'), dict(object=dict(type='commit', sha=self.base))]):
            self.assertEqual(update.latest(self.lock, 'channel-a')['status'], 'unchanged')


if __name__ == '__main__':
    unittest.main()
