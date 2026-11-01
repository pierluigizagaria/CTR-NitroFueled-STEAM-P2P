"""Pin the shadPS4 import-name table shipped by the host portable packages."""
import argparse
import json
from pathlib import Path
import re

from distribution_support import json_bytes, read_zip, sha256
from release_support import download, revision, write_zip

DEFAULT_LOCK = Path(__file__).with_name('aerolib-lock.json')


def load_lock(path=DEFAULT_LOCK):
    lock = json.loads(Path(path).read_text(encoding='utf-8'))
    paths = {'aerolib.inl': 'src/core/aerolib/aerolib.inl', 'LICENSE': 'LICENSE'}
    if (lock.get('schema_version') != 1 or lock.get('license') != 'GPL-2.0-or-later'
            or lock.get('repository') != 'https://github.com/shadps4-emu/shadPS4'
            or set(lock.get('files', {})) != set(paths)):
        raise ValueError('Unsupported aerolib input lock')
    revision(lock['revision'])
    for name, item in lock['files'].items():
        expected = ('https://raw.githubusercontent.com/shadps4-emu/shadPS4/'
                    + lock['revision'] + '/' + paths[name])
        if (item['url'] != expected or item['source_path'] != paths[name]
                or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])):
            raise ValueError('Aerolib input is not bound to its official source revision')
    return lock


def verified_files(directory, lock):
    root = Path(directory)
    files = {}
    for name, spec in lock['files'].items():
        path = root / name
        if root.is_symlink() or path.is_symlink() or not path.is_file():
            raise ValueError('Aerolib input is not a regular file: ' + name)
        data = path.read_bytes()
        if sha256(data) != spec['sha256']:
            raise ValueError('Aerolib input checksum mismatch: ' + name)
        files[name] = data
    return files


def source_archive(directory, lock):
    root = Path(directory)
    inputs = verified_files(root, lock)
    files = {lock['files'][name]['source_path']: data for name, data in inputs.items()}
    files['PROVENANCE.json'] = json_bytes(lock)
    path = root / ('shadps4-aerolib-' + lock['revision'][:12] + '-source.zip')
    if path.exists():
        if path.is_symlink() or read_zip(path) != files:
            raise ValueError('Existing aerolib source archive differs from the pinned source')
    else:
        write_zip(path, files)
    return path


def materialize(destination, cache, host=None, lock_path=DEFAULT_LOCK):
    lock = load_lock(lock_path)
    destination, cache = Path(destination), Path(cache)
    if destination.is_symlink():
        raise ValueError('Aerolib destination is a symbolic link')
    files = {name: download(spec, cache / lock['revision'] / name).read_bytes()
             for name, spec in lock['files'].items()}
    for name, data in files.items():
        path = destination / name
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_bytes() != data)):
            raise ValueError('Existing aerolib input differs from the pinned source: ' + name)
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (destination / name).write_bytes(data)
    verified_files(destination, lock)
    source_archive(destination, lock)
    if host is not None:
        target = Path(host) / 'out' / 'aerolib.inl'
        if target.parent.is_symlink() or target.is_symlink():
            raise ValueError('Host aerolib destination contains a symbolic link')
        if target.exists() and (not target.is_file() or target.read_bytes() != files['aerolib.inl']):
            raise ValueError('Host aerolib input differs from the pinned source')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(files['aerolib.inl'])
    return destination


def inventory(payload, directory, notice, archives, lock_path=DEFAULT_LOCK):
    name = 'out/aerolib.inl'
    if name not in payload:
        return {}
    if directory is None:
        raise ValueError('Packaged aerolib requires pinned source evidence')
    lock = load_lock(lock_path)
    inputs = verified_files(directory, lock)
    if payload[name] != inputs['aerolib.inl']:
        raise ValueError('Packaged aerolib differs from the pinned source')
    source = source_archive(directory, lock)
    archives[source.name] = {'path': str(source.resolve()), 'sha256': sha256(source.read_bytes()),
                            'repository': lock['repository'], 'revision': lock['revision']}
    license_name = notice('shadps4-aerolib/LICENSE', inputs['LICENSE'])
    return {name: {'sha256': lock['files']['aerolib.inl']['sha256'], 'package': 'shadps4-aerolib',
        'version': lock['revision'], 'source_revision': lock['revision'], 'license': lock['license'],
        'source_url': lock['files']['aerolib.inl']['url'], 'license_files': [license_name],
        'source_archives': [source.name], 'redistribution_basis': 'corresponding-source',
        'basis_note': 'Exact unmodified GPL import-name source table, original copyright header, '
                      'license and pinned provenance included in the corresponding-source archive.'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--host-source', type=Path)
    parser.add_argument('--lock', type=Path, default=DEFAULT_LOCK)
    args = parser.parse_args()
    root = materialize(args.destination, args.cache, args.host_source, args.lock)
    print(json_bytes({'directory': str(root.resolve()), 'source': load_lock(args.lock)}).decode())


if __name__ == '__main__':
    main()
