"""The manual draft must carry the same exact standalone mod as automatic releases."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import draft_distributions
import test_release_automation_publish as fixtures
from distribution_support import json_bytes


class CompleteDraftTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AssetTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.plan = self.fixture.plan
        self.repository = self.root / 'repository'
        self.repository.mkdir()
        (self.repository / 'distribution-lock.json').write_bytes(json_bytes(self.plan['new_lock']))
        (self.repository / 'release-lock.json').write_bytes(json_bytes(self.fixture.release_lock))

    def validate(self):
        return draft_distributions.validate_draft(self.root, self.plan['version'],
            self.plan['candidate_revision'], self.repository)

    def test_draft_contains_both_complete_builds_sources_and_exact_standalone_mod(self):
        assets = self.validate()
        self.assertEqual(len(assets), 10)
        self.assertIn(self.fixture.standalone_path, assets)
        self.assertIn(self.fixture.standalone_path.with_suffix('.zip.sha256'), assets)
        with patch.object(sys, 'argv', ['draft_distributions.py', '--version', self.plan['version'],
                '--revision', self.plan['candidate_revision'], '--dist', str(self.root)]), \
                patch.object(draft_distributions, 'validate_draft', return_value=assets), \
                patch.object(draft_distributions, 'output', side_effect=['[[]]', '[]']), \
                patch.object(draft_distributions, 'run') as run:
            draft_distributions.main()
        run.assert_called_once()
        self.assertTrue(all(asset in run.call_args.args for asset in assets))
        self.assertIn('--draft', run.call_args.args)
        self.assertNotIn('--clobber', run.call_args.args)
        self.assertIn('separate ctrnf-p2p-mod archive', (self.root / 'complete-release-notes.md').read_text())

    def test_missing_standalone_mod_cannot_create_a_draft(self):
        self.fixture.standalone_path.unlink()
        with self.assertRaisesRegex(ValueError, 'standalone mod archive is required'):
            self.validate()

    def test_mod_must_match_the_trusted_bridge_revision(self):
        manifest = self.fixture.standalone_manifest
        manifest['components']['ctrnf-p2p']['revision'] = '0' * 40
        self.fixture.standalone_files['ctrnf-p2p-manifest.json'] = json_bytes(manifest)
        fixtures.archive(self.fixture.standalone_path, self.fixture.standalone_files)
        with self.assertRaisesRegex(ValueError, 'Mod component identity'):
            self.validate()

    def test_complete_distribution_must_use_the_downloaded_standalone_bytes(self):
        channel = fixtures.publisher.CHANNELS[0]
        path, files = self.fixture.binaries[channel]
        manifest = json.loads(files['p2p-distribution-manifest.json'])
        manifest['input_archives']['mod'] = '0' * 64
        files['p2p-distribution-manifest.json'] = json_bytes(manifest)
        fixtures.archive(path, files)
        with self.assertRaisesRegex(ValueError, 'exact standalone mod build'):
            self.validate()


if __name__ == '__main__':
    unittest.main()
