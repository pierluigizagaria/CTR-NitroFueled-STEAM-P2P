import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import aerolib_inputs as aerolib
from distribution_support import json_bytes, read_zip, sha256
from export_host_source import dependency_files


class AerolibTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = aerolib.load_lock()
        self.inputs = {'aerolib.inl': b'// SPDX-License-Identifier: GPL-2.0-or-later\nSTUB(abcdef, example)\n',
                       'LICENSE': b'GPL source license fixture\n'}
        self.cache = self.root / 'cache'
        for name, data in self.inputs.items():
            self.lock['files'][name]['sha256'] = sha256(data)
            path = self.cache / self.lock['revision'] / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.lock_path = self.root / 'lock.json'
        self.lock_path.write_bytes(json_bytes(self.lock))
        self.destination = self.root / 'dependency'
        self.host = self.root / 'host'

    def materialize(self, destination=None):
        return aerolib.materialize(destination or self.destination, self.cache, self.host, self.lock_path)

    def test_pin_materializes_exact_source_without_network_and_preserves_existing_host(self):
        with mock.patch('urllib.request.urlopen', side_effect=AssertionError('unexpected network')):
            self.materialize()
            self.materialize()
        self.assertEqual((self.host / 'out/aerolib.inl').read_bytes(), self.inputs['aerolib.inl'])
        self.assertEqual(aerolib.verified_files(self.destination, self.lock), self.inputs)
        (self.host / 'out/aerolib.inl').write_bytes(b'existing different table')
        with self.assertRaisesRegex(ValueError, 'Host aerolib input differs'):
            self.materialize()
        self.assertEqual((self.host / 'out/aerolib.inl').read_bytes(), b'existing different table')

    def test_moving_source_url_and_invalid_hash_are_refused(self):
        for change in ('moving', 'hash', 'license'):
            bad = json.loads(json.dumps(self.lock))
            if change == 'moving':
                bad['files']['aerolib.inl']['url'] = bad['files']['aerolib.inl']['url'].replace(
                    bad['revision'], 'main')
            elif change == 'hash':
                bad['files']['aerolib.inl']['sha256'] = 'invalid'
            else:
                del bad['files']['LICENSE']
            self.lock_path.write_bytes(json_bytes(bad))
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.materialize()
            self.assertFalse(self.destination.exists())

    def test_changed_cached_source_or_existing_dependency_is_refused(self):
        source = self.cache / self.lock['revision'] / 'aerolib.inl'
        source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
            self.materialize()
        self.assertFalse(self.destination.exists())
        source.write_bytes(self.inputs['aerolib.inl'])
        self.materialize()
        (self.destination / 'LICENSE').write_bytes(b'changed notice')
        with self.assertRaisesRegex(ValueError, 'Existing aerolib input differs'):
            self.materialize()

    def test_source_archive_contains_exact_table_license_and_pinned_provenance(self):
        self.materialize()
        source = aerolib.source_archive(self.destination, self.lock)
        expected = {'src/core/aerolib/aerolib.inl': self.inputs['aerolib.inl'],
                    'LICENSE': self.inputs['LICENSE'], 'PROVENANCE.json': json_bytes(self.lock)}
        self.assertEqual(read_zip(source), expected)
        other = self.materialize(self.root / 'second-dependency')
        self.assertEqual(source.read_bytes(), aerolib.source_archive(other, self.lock).read_bytes())
        with zipfile.ZipFile(source, 'w') as archive:
            for name, data in expected.items():
                archive.writestr(name, b'changed' if name == 'LICENSE' else data)
        with self.assertRaisesRegex(ValueError, 'source archive differs'):
            aerolib.source_archive(self.destination, self.lock)

    def test_inventory_and_source_export_bind_same_table_and_license(self):
        self.materialize()
        payload = {'out/aerolib.inl': self.inputs['aerolib.inl']}
        inventory = {'schema_version': 1, 'source_archives': {}, 'license_files': {}}
        def notice(name, data):
            path = self.root / 'notices' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            inventory['license_files'][name] = {'path': str(path), 'sha256': sha256(data)}
            return name
        inventory['files'] = aerolib.inventory(payload, self.destination, notice,
                                              inventory['source_archives'], self.lock_path)
        inventory_path = self.root / 'inventory.json'
        inventory_path.write_bytes(json_bytes(inventory))
        exported = {}
        runtime, ready = dependency_files(inventory_path, exported, self.root / 'source-cache')
        self.assertTrue(ready)
        self.assertTrue(runtime['out/aerolib.inl']['redistribution_ready'])
        self.assertEqual(runtime['out/aerolib.inl']['sha256'], sha256(payload['out/aerolib.inl']))
        self.assertEqual(runtime['out/aerolib.inl']['source_revision'], self.lock['revision'])
        source = aerolib.source_archive(self.destination, self.lock)
        self.assertEqual(exported['dependency-sources/' + source.name], source.read_bytes())
        self.assertEqual(exported['dependency-licenses/shadps4-aerolib/LICENSE'], self.inputs['LICENSE'])
        for changed, directory in (({'out/aerolib.inl': b'changed'}, self.destination), (payload, None)):
            with self.assertRaises(ValueError):
                aerolib.inventory(changed, directory, notice, {}, self.lock_path)
        (self.destination / 'LICENSE').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            aerolib.inventory(payload, self.destination, notice, {}, self.lock_path)

    def test_absent_table_needs_no_dependency(self):
        with mock.patch.object(aerolib, 'load_lock', side_effect=AssertionError('unneeded dependency')):
            self.assertEqual(aerolib.inventory({'bin/host.exe': b'host'}, None, None, {}), {})


if __name__ == '__main__':
    unittest.main()
