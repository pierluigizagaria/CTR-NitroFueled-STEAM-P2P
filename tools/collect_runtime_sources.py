"""Inventory portable runtime DLLs and licenses from their exact MSYS2 owners.

Copyleft dependency sources are explicit reviewed inputs, never inferred from a
generic project homepage. --source-evidence supplies source_archives and package
records keyed by the exact 'package@version'. Unresolved entries stay unresolved.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from distribution_support import json_bytes, locked_channel, read_zip, sha256, windows_name
from msys2_metadata import installed as installed_metadata


def dxc_inventory(payload, directory, notice, lock_path=None):
    """Bind packaged DXC bytes and notices to the reviewed Microsoft release."""
    from dxc_toolchain import DEFAULT_LOCK, BINARIES, LICENSES, NOTICES, load_lock, verify_materialized
    selected = {name for name in payload if name.startswith('bin/dxc/')}
    if not selected:
        return {}
    lock = load_lock(lock_path or DEFAULT_LOCK)
    expected = {'bin/dxc/' + Path(name).name for name in BINARIES | LICENSES}
    if selected != expected or not directory:
        raise ValueError('DXC payload requires the exact reviewed compiler, library and licenses')
    root = verify_materialized(directory, lock)
    for name, digest in lock['files'].items():
        packaged = 'bin/dxc/' + Path(name).name
        if sha256(payload[packaged]) != digest:
            raise ValueError('Packaged DXC checksum mismatch: ' + packaged)
    licenses = [notice('dxc/' + name, (root / name).read_bytes()) for name in sorted(LICENSES | NOTICES)]
    return {'bin/dxc/' + Path(name).name: {
        'sha256': digest, 'package': 'microsoft-DirectXShaderCompiler', 'version': lock['tag'],
        'license': lock['license'], 'license_files': licenses, 'source_archives': [],
        'redistribution_basis': 'permissive-license', 'basis_note': lock['basis_note'],
        'homepage': lock['repository'], 'source_revision': lock['revision'],
        'source_url': lock['repository'] + '/tree/' + lock['revision'],
        'release_archive': lock['archive'], 'archive_member': name,
    } for name, digest in lock['files'].items() if name in BINARIES}


def collect(args):
    _, pin = locked_channel(args.lock, args.channel)
    payload = read_zip(args.host_package, prefix=pin['portable_root'])
    payload.update({p.name: p.read_bytes() for p in Path(args.backend_dir).glob('*.dll')})
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    msys = Path(args.msys_root)
    installed_packages, owners = installed_metadata(msys)
    evidence = json.loads(Path(args.source_evidence).read_text(encoding='utf-8')) if args.source_evidence else {}
    # Keep local paths meaningful when the assembled inventory has another parent.
    archives = evidence.get('source_archives', {})
    for item in archives.values():
        if 'path' in item:
            item['path'] = str((Path(args.source_evidence).parent / item['path']).resolve())
    inventory = {'schema_version': 1, 'files': {}, 'license_files': {}, 'source_archives': archives}
    cache = {}

    def notice(name, data):
        windows_name(name)
        relative = 'runtime-licenses/' + name
        path = destination.parent / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        inventory['license_files'][name] = {'path': relative, 'sha256': sha256(data)}
        return name

    for name, entry in evidence.get('license_files', {}).items():
        data = (Path(args.source_evidence).parent / entry['path']).read_bytes()
        if sha256(data) != entry['sha256']:
            raise ValueError(f'Reviewed license checksum mismatch: {name}')
        notice(name, data)

    dxc = dxc_inventory(payload, getattr(args, 'dxc_dir', None), notice)
    from aerolib_inputs import inventory as aerolib_inventory
    inventory['files'].update(aerolib_inventory(payload, getattr(args, 'aerolib_dir', None), notice, archives))

    own = {pin['launcher'], 'bin/sacredfire.exe', 'bin/bb-gpu-capabilities.exe', 'psn-bridge-backend.dll'}
    python_notice = next((name for name in payload if name.lower() == 'python/license.txt'), None)
    python_version = re.search(rb'Python (\d+\.\d+\.\d+)', payload.get('THIRD-PARTY.txt', b''))
    for name, data in sorted(payload.items()):
        if Path(name).suffix.lower() not in ('.dll', '.pyd', '.exe') or name in own:
            continue
        item = {'sha256': sha256(data), 'license_files': [], 'source_archives': [],
                'redistribution_basis': 'unresolved', 'package': 'unknown', 'version': 'unknown',
                'license': 'unknown'}
        if name in dxc:
            item.update(dxc[name])
        elif name.startswith('python/Lib/site-packages/iced_x86/'):
            notices = [p for p in payload if '.dist-info/' in p and
                       ('license' in p.lower() or 'copying' in p.lower())]
            match = next((re.search(r'iced_x86-([^/]+)\.dist-info/', p) for p in notices
                          if re.search(r'iced_x86-([^/]+)\.dist-info/', p)), None)
            item.update(package='iced-x86', version=match.group(1) if match else 'unknown', license='MIT',
                        license_files=[notice(p, payload[p]) for p in notices],
                        redistribution_basis='permissive-license',
                        basis_note='Original license from the hash-pinned wheel packaged by the host.')
        elif name.startswith('python/') and python_notice:
            item.update(package='python-embeddable',
                        version=python_version.group(1).decode() if python_version else 'unknown',
                        license='PSF-2.0 AND bundled dependency notices',
                        license_files=[notice(python_notice, payload[python_notice])],
                        redistribution_basis='permissive-license',
                        basis_note='Official embedded Python distribution; retain its complete bundled license file.')
        else:
            installed = msys / 'clang64/bin' / Path(name).name
            if installed.is_file() and sha256(installed.read_bytes()) == item['sha256']:
                try:
                    package = owners['clang64/bin/' + installed.name.casefold()]
                    if package not in cache:
                        fields = installed_packages[package]
                        version = fields['VERSION'][0]
                        license_name = ' '.join(fields.get('LICENSE', ['unknown'])).replace('spdx:', '')
                        notices = []
                        for entry in fields['FILES']:
                            file = msys / entry.lstrip('/')
                            if '/share/licenses/' in entry and file.is_file():
                                notices.append(notice(package + '/' + entry.split('/share/licenses/', 1)[1],
                                                      file.read_bytes()))
                        details = {'package': package, 'version': version, 'license': license_name,
                                   'homepage': fields.get('URL', [None])[0], 'license_files': notices}
                        reviewed = evidence.get('packages', {}).get(package + '@' + version)
                        if reviewed:
                            details.update(reviewed)
                        elif (not re.search(r'GPL|LGPL|AGPL', license_name, re.I)
                              and re.fullmatch(r'[A-Za-z0-9.\-+_ ()]+', license_name)
                              and all(re.match(r'^(MIT|BSD|Apache|ISC|Zlib|BSL|CC0|Public|Unlicense|LLVM)', token)
                                      for token in license_name.split())):
                            details.update(redistribution_basis='permissive-license',
                                           basis_note='Installed MSYS2 package metadata and retained license text.')
                        cache[package] = details
                    item.update(cache[package])
                except (subprocess.CalledProcessError, KeyError):
                    pass
        inventory['files'][name] = item
    destination.write_bytes(json_bytes(inventory))
    unresolved = sorted({entry['package'] + '@' + entry['version'] for entry in inventory['files'].values()
                         if entry['redistribution_basis'] == 'unresolved' or not entry['license_files']})
    print(json.dumps({'runtime_files': len(inventory['files']), 'unresolved_packages': unresolved}))
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('host-package', 'backend-dir', 'msys-root', 'lock', 'channel', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--source-evidence')
    parser.add_argument('--dxc-dir', help='Verified DXC directory from tools/dxc_toolchain.py')
    parser.add_argument('--aerolib-dir', help='Pinned import-name source from tools/aerolib_inputs.py')
    collect(parser.parse_args())


if __name__ == '__main__':
    main()
