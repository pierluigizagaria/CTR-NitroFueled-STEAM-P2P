import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import dxc_toolchain as dxc
from collect_runtime_sources import dxc_inventory
from distribution_support import json_bytes, sha256


class DxcTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / 'tool'
        self.archive = self.root / 'fixture.zip'
        self.lock_path = self.root / 'lock.json'
        self.files = {name: ('fixture ' + name).encode() for name in dxc.BINARIES | dxc.LICENSES}
        self.lock = dxc.load_lock()
        self.lock['files'] = {name: sha256(data) for name, data in self.files.items()}
        self.notices = {name: ('notice ' + name).encode() for name in dxc.NOTICES}
        for name, data in self.notices.items():
            self.lock['notices'][name]['sha256'] = sha256(data)
        self.make_archive()

    def make_archive(self, extras=(), missing=()):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name, data in self.files.items():
                if name not in missing:
                    archive.writestr(name, data)
            for name, data in extras:
                archive.writestr(name, data)
        self.lock['archive']['sha256'] = sha256(self.archive.read_bytes())
        self.lock_path.write_bytes(json_bytes(self.lock))

    def download(self, spec, path):
        if spec['url'] == self.lock['archive']['url']:
            self.assertEqual(sha256(self.archive.read_bytes()), spec['sha256'])
            return self.archive
        name = spec['url'].rsplit('/', 1)[1]
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.notices[name])
        return path

    def materialize(self):
        with mock.patch.object(dxc, 'download', side_effect=self.download):
            return dxc.materialize(self.destination, self.root / 'cache', self.lock_path)

    def payload(self):
        return {'bin/dxc/' + Path(name).name: data for name, data in self.files.items()}

    def test_only_x64_compiler_and_notices_are_materialized_and_reusable(self):
        self.make_archive([('bin/x64/dxil.dll', b'excluded signer'), ('bin/arm64/dxc.exe', b'other CPU')])
        self.materialize()
        actual = {p.relative_to(self.destination).as_posix() for p in self.destination.rglob('*') if p.is_file()}
        self.assertEqual(actual, dxc.BINARIES | dxc.LICENSES | dxc.NOTICES)
        self.materialize()
        self.assertFalse((self.destination / 'bin/x64/dxil.dll').exists())

    def test_unsafe_duplicate_and_symlink_members_are_rejected(self):
        link = zipfile.ZipInfo('symlink')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for extra in (('../outside', b'bad'), ('bin/X64/DXC.EXE', b'alias'), (link, b'target')):
            with self.subTest(extra=str(extra[0])):
                self.make_archive([extra])
                with self.assertRaises(ValueError):
                    self.materialize()
                self.assertFalse(self.destination.exists())

    def test_missing_license_and_changed_member_are_rejected_before_writes(self):
        self.make_archive(missing=['LICENSE-LLVM.txt'])
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.materialize()
        self.make_archive()
        self.lock['files']['bin/x64/dxc.exe'] = '0' * 64
        self.lock_path.write_bytes(json_bytes(self.lock))
        with self.assertRaisesRegex(ValueError, 'member checksum'):
            self.materialize()
        self.assertFalse(self.destination.exists())

    def test_modified_cached_tool_and_extra_signer_are_refused(self):
        self.materialize()
        tool = self.destination / 'bin/x64/dxc.exe'
        tool.write_bytes(b'modified')
        with self.assertRaisesRegex(ValueError, 'Existing DXC tool differs'):
            self.materialize()
        self.assertEqual(tool.read_bytes(), b'modified')
        tool.write_bytes(self.files['bin/x64/dxc.exe'])
        (tool.parent / 'dxil.dll').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'unexpected files'):
            dxc.verify_materialized(self.destination, self.lock)

    def test_inventory_requires_exact_payload_and_retains_all_notices_and_provenance(self):
        self.materialize()
        retained = {}
        def notice(name, data):
            retained[name] = data
            return name
        result = dxc_inventory(self.payload(), self.destination, notice, self.lock_path)
        self.assertEqual(set(result), {'bin/dxc/dxc.exe', 'bin/dxc/dxcompiler.dll'})
        self.assertEqual(set(retained), {'dxc/' + name for name in dxc.LICENSES | dxc.NOTICES})
        for item in result.values():
            self.assertEqual(item['source_revision'], self.lock['revision'])
            self.assertEqual(item['release_archive'], self.lock['archive'])
            self.assertEqual(item['redistribution_basis'], 'permissive-license')
        for payload in (self.payload() | {'bin/dxc/dxil.dll': b'not permitted'},
                        self.payload() | {'bin/dxc/dxc.exe': b'changed'},
                        {k: v for k, v in self.payload().items() if not k.endswith('LICENSE-LLVM.txt')}):
            with self.assertRaises(ValueError):
                dxc_inventory(payload, self.destination, notice, self.lock_path)

    def test_inventory_rejects_changed_source_notice_and_missing_materialization(self):
        self.materialize()
        (self.destination / 'ThirdPartyNotices.txt').write_bytes(b'modified')
        with self.assertRaisesRegex(ValueError, 'materialized checksum'):
            dxc_inventory(self.payload(), self.destination, lambda n, d: n, self.lock_path)
        with self.assertRaises(ValueError):
            dxc_inventory(self.payload(), None, lambda n, d: n, self.lock_path)

    def test_host_without_dxc_needs_no_dependency_or_network(self):
        with mock.patch.object(dxc, 'load_lock', side_effect=AssertionError('unneeded dependency')):
            self.assertEqual(dxc_inventory({'bin/host.exe': b'host'}, None, None), {})

    def test_lock_cannot_select_signer_or_unpinned_notice(self):
        for change in ('signer', 'notice'):
            bad = json.loads(json.dumps(self.lock))
            if change == 'signer':
                bad['files']['bin/x64/dxil.dll'] = '0' * 64
            else:
                bad['notices']['LICENSE.TXT']['url'] = bad['notices']['LICENSE.TXT']['url'].replace(
                    bad['revision'], 'main')
            self.lock_path.write_bytes(json_bytes(bad))
            with self.assertRaises(ValueError):
                dxc.load_lock(self.lock_path)


if __name__ == '__main__':
    unittest.main()
