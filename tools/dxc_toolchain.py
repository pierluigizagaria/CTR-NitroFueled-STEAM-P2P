"""Materialize the pinned Windows DXC compiler and its complete license notices.

Only the x64 compiler and library used for SPIR-V are selected. The DXIL signer,
headers, import libraries and other architectures are never extracted.
"""
import argparse
import json
from pathlib import Path
import re
import stat
import zipfile

from distribution_support import json_bytes, sha256, windows_name
from release_support import download, revision

DEFAULT_LOCK = Path(__file__).with_name('dxc-lock.json')
BINARIES = {'bin/x64/dxc.exe', 'bin/x64/dxcompiler.dll'}
LICENSES = {'LICENSE-LLVM.txt', 'LICENCE-MIT.txt'}
NOTICES = {'LICENSE.TXT', 'ThirdPartyNotices.txt'}


def load_lock(path=DEFAULT_LOCK):
    lock = json.loads(Path(path).read_text(encoding='utf-8'))
    if (lock.get('schema_version') != 1
            or lock.get('repository') != 'https://github.com/microsoft/DirectXShaderCompiler'
            or set(lock.get('files', {})) != BINARIES | LICENSES
            or set(lock.get('notices', {})) != NOTICES):
        raise ValueError('Unsupported DXC lock or selected files')
    revision(lock['revision'])
    if not re.fullmatch(r'v[0-9.]+', lock['tag']):
        raise ValueError('Invalid DXC release tag')
    prefix = lock['repository'] + '/releases/download/' + lock['tag'] + '/'
    if not lock['archive']['url'].startswith(prefix):
        raise ValueError('DXC archive is not from its official pinned release')
    for name, item in lock['notices'].items():
        expected = ('https://raw.githubusercontent.com/microsoft/DirectXShaderCompiler/'
                    + lock['revision'] + '/' + name)
        if item['url'] != expected:
            raise ValueError('DXC notice is not from its pinned source revision')
    hashes = [lock['archive']['sha256'], *lock['files'].values(),
              *(item['sha256'] for item in lock['notices'].values())]
    if not all(re.fullmatch(r'[0-9a-f]{64}', value) for value in hashes):
        raise ValueError('DXC inputs require SHA-256 digests')
    return lock


def safe_target(root, name):
    windows_name(name)
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('DXC output escapes its destination')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('DXC output contains a symbolic link')
        if part == root:
            break
    return path


def selected_files(archive_path, lock):
    """Read only allow-listed, regular ZIP entries after validating every name."""
    files, seen = {}, set()
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            name = entry.filename.rstrip('/') if entry.is_dir() else entry.filename
            windows_name(name)
            if name.casefold() in seen:
                raise ValueError('Duplicate DXC archive entry')
            seen.add(name.casefold())
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError('DXC archive contains a non-regular entry')
            if name in lock['files']:
                if entry.is_dir() or entry.file_size > 64 * 1024 * 1024:
                    raise ValueError('Invalid DXC selected file')
                data = archive.read(entry)
                if sha256(data) != lock['files'][name]:
                    raise ValueError('DXC member checksum mismatch: ' + name)
                files[name] = data
    if set(files) != set(lock['files']):
        raise ValueError('DXC archive is missing a required compiler or license file')
    return files


def verify_materialized(root, lock):
    root = Path(root)
    expected = lock['files'] | {name: item['sha256'] for name, item in lock['notices'].items()}
    for name, digest in expected.items():
        path = safe_target(root, name)
        if not path.is_file() or sha256(path.read_bytes()) != digest:
            raise ValueError('DXC materialized checksum mismatch: ' + name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != set(expected):
        raise ValueError('DXC destination contains unexpected files')
    return root


def materialize(destination, cache, lock_path=DEFAULT_LOCK):
    lock = load_lock(lock_path)
    destination, cache = Path(destination), Path(cache)
    archive = download(lock['archive'], cache / lock['archive']['url'].rsplit('/', 1)[1])
    files = selected_files(archive, lock)
    for name, spec in lock['notices'].items():
        files[name] = download(spec, cache / lock['revision'] / name).read_bytes()
    # Verify existing files before writing anything; do not silently repair a tampered tool.
    for name, data in files.items():
        path = safe_target(destination, name)
        if path.exists() and (not path.is_file() or path.read_bytes() != data):
            raise ValueError('Existing DXC tool differs from the pinned input: ' + name)
    for name, data in files.items():
        path = safe_target(destination, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return verify_materialized(destination, lock)


def provenance(lock):
    return {key: lock[key] for key in ('repository', 'tag', 'revision', 'archive', 'files', 'notices')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, default=DEFAULT_LOCK)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    args = parser.parse_args()
    result = materialize(args.destination, args.cache, args.lock)
    print(json_bytes({'directory': str(result.resolve()), **provenance(load_lock(args.lock))}).decode())


if __name__ == '__main__':
    main()
