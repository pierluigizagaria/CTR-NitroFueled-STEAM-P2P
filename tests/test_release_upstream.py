import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from distribution_support import json_bytes, sha256
import host_integration as integration
import prepare_upstream_update as update


class UpstreamUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'upstream'
        self.repo = self.root / 'p2p'
        self.source.mkdir()
        self.repo.mkdir()
        for path in (self.source, self.repo):
            self.git('init', '-q', '-b', 'main', repo=path)
            self.git('config', 'user.name', 'Fixture Author', repo=path)
            self.git('config', 'user.email', 'fixture@example.invalid', repo=path)
            self.git('config', 'commit.gpgsign', 'false', repo=path)
            self.git('config', 'core.autocrlf', 'false', repo=path)
        self.write('.gitignore', '/out/\n')
        self.write('runtime.txt', 'base runtime\n')
        self.write('README.txt', 'upstream\n')
        self.binary = b'original optional artwork\0do not embed in source patches\xff'
        (self.source / 'artwork.bin').write_bytes(self.binary)
        self.base = self.commit('Upstream release one')
        self.git('tag', 'v1')
        self.git('switch', '-qc', 'integration')
        self.write('platform/psn/api.h', 'fixture public API\n')
        self.write('runtime.txt', 'integrated runtime\n')
        self.first_patch = self.commit('Add optional adapter')
        (self.source / 'artwork.bin').unlink()
        self.write('integration.txt', 'integration documentation\n')
        self.integrated = self.commit('Describe integration and omit artwork')
        self.psn_tree = self.git('rev-parse', 'HEAD:platform/psn')
        self.tree = self.git('rev-parse', 'HEAD^{tree}')
        self.channel = 'getlostin-ctr-nitrofueled-pc'
        self.url = 'https://github.com/Fixture/Host.git'
        self.recipe_dir = self.repo / 'integrations/Fixture/Host'
        integration.export_recipe(self.source, self.base, self.integrated, self.recipe_dir, self.url)
        self.recipe = self.recipe_dir / 'recipe.json'
        self.pin = dict(repository=self.url, display_name='Fixture/Host', revision=self.integrated,
                        source_tree=self.tree, psn_tree=self.psn_tree, host_mode='psn',
                        launcher='host.exe', portable_root='portable',
                        recipe=dict(path=self.recipe.relative_to(self.repo).as_posix(),
                                    sha256=sha256(self.recipe.read_bytes())),
                        upstream=dict(repository=self.url, tag='v1', revision=self.base))
        self.lock = self.repo / 'distribution-lock.json'
        self.lock.write_bytes(json_bytes(dict(schema_version=2, channels={self.channel: self.pin})))
        self.destination = self.repo / 'out/integrations/candidate'
        self.git('switch', '-q', 'main')
        self.write('README.txt', 'unsaved source checkout edit\n')
        self.args = argparse.Namespace(repository=self.repo, lock=self.lock, channel=self.channel,
                                       destination=self.destination, source_cache=self.source,
                                       upstream_tag='v1', upstream_revision=self.base)

    def git(self, *args, repo=None):
        return subprocess.check_output(['git', '-C', str(repo or self.source), *map(str, args)],
                                       text=True, stderr=subprocess.PIPE).strip()

    def write(self, name, data):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding='utf-8')

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def next_release(self, conflict=False):
        self.git('restore', 'README.txt')
        self.git('switch', '-qc', 'upstream-next', self.base)
        self.write('upstream.txt', 'new upstream behavior\n')
        if conflict:
            self.write('runtime.txt', 'upstream rewrite\n')
        self.upstream = self.commit('Upstream release two')
        self.git('tag', '-a', 'v2', '-m', 'Annotated upstream tag')
        self.git('switch', '-q', 'main')
        self.write('README.txt', 'unsaved source checkout edit\n')
        self.args.upstream_tag, self.args.upstream_revision = 'v2', self.upstream
        return dict(repository=self.url, tag='v2', revision=self.upstream)

    def preserved(self):
        return (self.git('rev-parse', 'HEAD'), self.git('branch', '--show-current'),
                self.git('status', '--porcelain'), self.git('rev-parse', 'integration'),
                (self.source / 'README.txt').read_bytes(), self.lock.read_bytes())

    def test_exact_original_commits_and_trees_are_reproduced_without_host_branch_access(self):
        before = self.preserved()
        result = update.prepare(self.args)
        self.assertEqual(result['status'], 'prepared')
        self.assertEqual(result['candidate_revision'], self.integrated)
        self.assertEqual(result['source_tree'], self.tree)
        self.assertEqual(result['psn_tree'], self.psn_tree)
        self.assertEqual(before, self.preserved())
        self.assertEqual(self.git('remote', 'get-url', 'origin', repo=self.destination), self.url)
        self.assertFalse((self.destination / 'artwork.bin').exists())
        self.assertFalse(result['lock_modified'])
        self.assertTrue(result['next_commands'])

    def test_recipe_contains_no_removed_binary_content(self):
        recipe = json.loads(self.recipe.read_bytes())
        self.assertEqual(recipe['commits'][1]['deletions'][0]['path'], 'artwork.bin')
        for path in self.recipe_dir.iterdir():
            self.assertNotIn(self.binary, path.read_bytes())
            self.assertNotIn(b'GIT binary patch', path.read_bytes())

    def test_updated_upstream_replay_is_deterministic_and_preserves_author_metadata(self):
        target = self.next_release()
        before = self.preserved()
        first = update.prepare(self.args)
        self.assertEqual(first['status'], 'prepared')
        self.assertEqual(before, self.preserved())
        self.assertEqual((self.destination / 'upstream.txt').read_text(), 'new upstream behavior\n')
        second = integration.materialize(self.repo, self.pin, self.repo / 'out/second',
                                         self.source, target, verify_pin=False)
        self.assertEqual(first['candidate_revision'], second['candidate_revision'])
        self.assertEqual(first['source_tree'], second['source_tree'])
        self.assertEqual(first['psn_tree'], self.psn_tree)
        raw = self.git('cat-file', 'commit', first['candidate_revision'], repo=self.destination)
        self.assertIn('author Fixture Author <fixture@example.invalid>', raw)

    def test_conflict_retains_candidate_and_does_not_modify_original_sources_or_lock(self):
        self.next_release(conflict=True)
        before = self.preserved()
        result = update.prepare(self.args)
        self.assertEqual(result['status'], 'conflict')
        self.assertTrue(self.destination.is_dir())
        self.assertEqual(result['candidate_worktree'], str(self.destination))
        self.assertIn('patch does not apply', result['diagnostic'])
        self.assertEqual(result['next_commands'], [])
        self.assertEqual(before, self.preserved())

    def test_modified_patch_is_rejected_before_destination_is_created(self):
        patch = next(self.recipe_dir.glob('*.patch'))
        patch.write_bytes(patch.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'patch checksum mismatch'):
            integration.materialize(self.repo, self.pin, self.destination, self.source)
        self.assertFalse(self.destination.exists())

    def test_recipe_path_cannot_escape_the_repository(self):
        pin = deepcopy(self.pin)
        pin['recipe']['path'] = '../recipe.json'
        with self.assertRaises(ValueError):
            integration.materialize(self.repo, pin, self.destination, self.source)
        self.assertFalse(self.destination.exists())

    def test_wrong_upstream_tag_revision_is_rejected(self):
        self.next_release()
        self.args.upstream_revision = self.base
        result = update.prepare(self.args)
        self.assertEqual(result['status'], 'conflict')
        self.assertIn('fetched official upstream tag', result['diagnostic'])

    def test_upstream_rollback_after_an_accepted_release_is_rejected(self):
        target = self.next_release()
        pin = deepcopy(self.pin)
        pin['upstream'] = target
        with self.assertRaisesRegex(ValueError, 'currently locked release'):
            integration.materialize(self.repo, pin, self.destination, self.source,
                                    self.pin['upstream'], verify_pin=False)

    def test_changed_deletion_target_is_rejected(self):
        self.git('restore', 'README.txt')
        (self.source / 'artwork.bin').write_bytes(b'changed optional artwork\0')
        upstream = self.commit('Change artwork')
        self.git('tag', 'v2')
        target = dict(repository=self.url, tag='v2', revision=upstream)
        with self.assertRaisesRegex(ValueError, 'deletion target changed'):
            integration.materialize(self.repo, self.pin, self.destination, self.source, target, False)

    def test_existing_completed_checkout_reuses_only_unchanged_tree(self):
        result = integration.materialize(self.repo, self.pin, self.destination, self.source)
        repeated = integration.materialize(self.repo, self.pin, self.destination, self.source)
        self.assertEqual(repeated['status'], 'unchanged')
        self.assertEqual(repeated['candidate_revision'], result['candidate_revision'])
        (self.destination / 'runtime.txt').write_text('user edit\n')
        with self.assertRaisesRegex(ValueError, 'not clean'):
            integration.materialize(self.repo, self.pin, self.destination, self.source)

    def test_clean_commit_cannot_replace_a_completed_candidate(self):
        target = self.next_release()
        integration.materialize(self.repo, self.pin, self.destination, self.source, target, False)
        self.git('config', 'user.name', 'Other', repo=self.destination)
        self.git('config', 'user.email', 'other@example.invalid', repo=self.destination)
        self.git('commit', '--allow-empty', '-qm', 'Unrelated commit', repo=self.destination)
        with self.assertRaisesRegex(ValueError, 'completed integration receipt'):
            integration.materialize(self.repo, self.pin, self.destination, self.source, target, False)

    def test_latest_peels_annotated_tag_without_git_or_local_mutation(self):
        self.next_release()
        before = self.preserved()
        with mock.patch.object(update, 'github_json', side_effect=[
                dict(tag_name='v2', draft=False, prerelease=False),
                dict(object=dict(type='tag', sha='a' * 40)),
                dict(object=dict(type='commit', sha=self.upstream))]) as request, \
                mock.patch.object(update, 'git', side_effect=AssertionError('read-only check ran Git')):
            result = update.latest(self.lock, self.channel)
        self.assertEqual(result['status'], 'changed')
        self.assertEqual(result['upstream_revision'], self.upstream)
        self.assertTrue(result['read_only'])
        self.assertEqual(request.call_args_list[0].args,
                         ('https://api.github.com/repos/Fixture/Host/releases/latest',))
        self.assertEqual(before, self.preserved())

    def test_latest_reports_unchanged_release(self):
        with mock.patch.object(update, 'github_json', side_effect=[
                dict(tag_name='v1'), dict(object=dict(type='commit', sha=self.base))]):
            self.assertEqual(update.latest(self.lock, self.channel)['status'], 'unchanged')


if __name__ == '__main__':
    unittest.main()
