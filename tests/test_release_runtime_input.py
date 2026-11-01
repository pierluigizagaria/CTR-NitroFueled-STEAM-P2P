import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import release_inputs
from release_support import digest


class RuntimeInputTests(unittest.TestCase):
    def setUp(self):
        self.steam = {'archive': {'url': 'https://github.com/owner/bridge/releases/download/v0.1.0-preview.1/ctrnf-p2p-mod-v0.1.0-preview.1-windows-x64.zip',
                                  'sha256': '0' * 64}, 'member': 'steam_api64.dll', 'sha256': digest(b'permitted runtime')}
        self.spec = {'url': 'https://github.com/owner/bridge/releases/download/v0.1.0-preview.1/GetLostIn-CTR-NitroFueled-PC-v0.4-STEAM-P2P-windows-x64.zip',
                     'sha256': 'a' * 64}

    def response(self, **fields):
        state = {'schema_version': 1, 'status': 'completed'} | fields
        raw = json.dumps(state).encode()
        return json.dumps({'encoding': 'base64', 'size': len(raw), 'content': base64.b64encode(raw).decode()})

    def test_first_migration_uses_original_hash_pinned_bootstrap(self):
        with patch.object(release_inputs, 'output', return_value=self.response()):
            self.assertEqual(release_inputs.runtime_archive_spec(self.steam), self.steam['archive'])

    def test_completed_and_failed_runs_keep_same_verified_runtime_source(self):
        for status in ('completed', 'blocked', 'pending'):
            with self.subTest(status=status), patch.object(release_inputs, 'output', return_value=self.response(
                    status=status, runtime_source=self.spec, publication_format='two-complete-archives-v1')):
                self.assertEqual(release_inputs.runtime_archive_spec(self.steam), self.spec)

    def test_missing_or_foreign_saved_archive_never_uses_deleted_bootstrap(self):
        invalid = [None, self.spec | {'url': self.spec['url'].replace('owner/bridge', 'other/repo')},
                   self.spec | {'sha256': 'invalid'}, self.spec | {'url': self.spec['url'] + '?token=x'}]
        for spec in invalid:
            with self.subTest(spec=spec), patch.object(release_inputs, 'output', return_value=self.response(
                    runtime_source=spec, publication_format='two-complete-archives-v1')):
                with self.assertRaises(ValueError):
                    release_inputs.runtime_archive_spec(self.steam)

    def test_network_failure_is_not_hidden_by_bootstrap_fallback(self):
        with patch.object(release_inputs, 'output', side_effect=OSError('network unavailable')):
            with self.assertRaises(OSError):
                release_inputs.runtime_archive_spec(self.steam)

    def test_archive_hash_and_original_dll_hash_are_both_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'full.zip'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('steam_api64.dll', b'permitted runtime')
            spec = self.spec | {'sha256': digest(source.read_bytes())}
            cached = root / ('steam-runtime-' + spec['sha256'] + '.zip')
            cached.write_bytes(source.read_bytes())
            with patch.object(release_inputs, 'runtime_archive_spec', return_value=spec):
                release_inputs.prepare_runtime(self.steam, root)
                self.assertEqual((root / 'steam_api64.dll').read_bytes(), b'permitted runtime')
                with self.assertRaisesRegex(ValueError, 'Steam runtime checksum'):
                    release_inputs.prepare_runtime(self.steam | {'sha256': 'f' * 64}, root)
                cached.write_bytes(b'corrupted archive')
                with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
                    release_inputs.prepare_runtime(self.steam, root)


if __name__ == '__main__':
    unittest.main()
