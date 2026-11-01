"""Exercise actual asset-ID rotation and recovery against an in-memory GitHub API."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import automation_publish as publisher


class RotationTests(unittest.TestCase):
    def setUp(self):
        self.first = {'name': 'GetLostIn-CTR-NitroFueled-PC-v0.4-STEAM-P2P-windows-x64.zip',
                      'size': 11, 'sha256': 'a' * 64}
        self.second = {'name': 'Ryu7w7-OCTR-NitroFueled-PC-v0.7.5-STEAM-P2P-windows-x64.zip',
                       'size': 12, 'sha256': 'b' * 64}
        self.records = [self.first, self.second]
        self.items = {}
        self.events = []
        self.fail_before = self.fail_after = None
        self.add(1, dict(self.first, sha256='c' * 64))
        self.add(2, self.second)
        self.add(3, dict(self.first, name=publisher.stage_name(self.first)))
        self.add(4, {'name': 'ctrnf-p2p-complete-v0.1.0-preview.1-0123456789ab.json',
                     'size': 10, 'sha256': 'd' * 64})
        self.add(5, {'name': 'maintainer-notes.txt', 'size': 3, 'sha256': 'e' * 64})
        self.previous = [publisher.remote_identity(item) for item in self.items.values()
                         if publisher.owned_asset(item['name'])]
        self.release = publisher.GitHubRelease('example/bridge', 'v0.1.0-preview.1')
        self.read_patch = patch.object(self.release, 'read', lambda: {'id': 99, 'assets': copy.deepcopy(list(self.items.values()))})
        self.api_patch = patch.object(publisher, 'api', self.api)
        for context in (self.read_patch, self.api_patch):
            context.start()
            self.addCleanup(context.stop)

    def add(self, identifier, record):
        self.items[identifier] = {'id': identifier, 'name': record['name'], 'size': record['size'],
                                  'digest': 'sha256:' + record['sha256'], 'state': 'uploaded'}

    def api(self, path, *, method='GET', body=None):
        identifier = int(path.rsplit('/', 1)[-1])
        event = (method, identifier)
        self.events.append(event)
        if self.fail_before == event:
            raise ValueError('request interrupted')
        if method == 'PATCH':
            if any(item['name'] == body['name'] and item['id'] != identifier for item in self.items.values()):
                raise ValueError('duplicate name')
            self.items[identifier]['name'] = body['name']
        elif method == 'DELETE':
            del self.items[identifier]
        else:
            raise AssertionError(method)
        if self.fail_after == event:
            raise ValueError('response lost')
        return copy.deepcopy(self.items.get(identifier))

    def test_same_version_update_keeps_old_bytes_until_pair_is_verified(self):
        self.release.promote_asset(self.first, self.previous)
        self.assertEqual(self.items[1]['name'], publisher.previous_name(self.previous[0]))
        self.assertEqual(self.items[3]['name'], self.first['name'])
        self.assertFalse(any(method == 'DELETE' for method, _ in self.events))
        self.release.prune(self.previous, self.records)
        self.assertEqual(set(self.items), {2, 3, 5})

    def test_interruption_between_backup_and_promotion_can_resume(self):
        self.fail_before = ('PATCH', 3)
        with self.assertRaisesRegex(ValueError, 'interrupted'):
            self.release.promote_asset(self.first, self.previous)
        self.assertEqual(set(self.items), {1, 2, 3, 4, 5})
        self.fail_before = None
        self.release.promote_asset(self.first, self.previous)
        self.release.prune(self.previous, self.records)
        self.assertEqual(set(self.items), {2, 3, 5})

    def test_lost_rename_and_delete_responses_are_verified_by_id(self):
        self.fail_after = ('PATCH', 3)
        self.release.promote_asset(self.first, self.previous)
        self.fail_after = ('DELETE', 1)
        self.release.prune(self.previous, self.records)
        self.assertEqual(set(self.items), {2, 3, 5})

    def test_cleanup_failure_keeps_final_pair_and_resumes_remaining_ids(self):
        self.release.promote_asset(self.first, self.previous)
        self.fail_before = ('DELETE', 4)
        with self.assertRaisesRegex(ValueError, 'interrupted'):
            self.release.prune(self.previous, self.records)
        self.assertEqual(set(self.items), {2, 3, 4, 5})
        self.fail_before = None
        self.release.prune(self.previous, self.records)
        self.assertEqual(set(self.items), {2, 3, 5})

    def test_missing_or_changed_staging_never_renames_old_download(self):
        self.items[3]['digest'] = 'sha256:' + '0' * 64
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.release.promote_asset(self.first, self.previous)
        self.assertEqual(self.events, [])

    def test_unknown_replacement_of_public_asset_is_not_overwritten(self):
        self.items[1]['id'] = 500
        with self.assertRaisesRegex(ValueError, 'outside the saved replacement'):
            self.release.promote_asset(self.first, self.previous)
        self.assertEqual(self.events, [])

    def test_pruning_requires_both_final_archives_and_preserves_unrecognized_assets(self):
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.release.prune(self.previous, self.records)
        self.assertEqual(self.events, [])
        self.release.promote_asset(self.first, self.previous)
        self.items[4]['name'] = 'changed-by-someone-else.json'
        with self.assertRaisesRegex(ValueError, 'outside the saved cleanup'):
            self.release.prune(self.previous, self.records)
        self.assertIn(4, self.items)
        self.assertIn(5, self.items)

    def test_old_format_whitelist_does_not_include_unrelated_downloads(self):
        self.assertTrue(publisher.owned_asset('ctrnf-p2p-mod-v0.1.0-preview.1-windows-x64.zip'))
        self.assertTrue(publisher.owned_asset('ctrnf-p2p-channel-a-v0.1.0-preview.1-0123456789ab-source.zip.sha256'))
        for name in ('ctrnf-p2p-important-notes.txt', 'random.zip', 'steam_api64.dll'):
            self.assertFalse(publisher.owned_asset(name))


if __name__ == '__main__':
    unittest.main()
