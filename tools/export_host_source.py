"""Export exact host Git objects, recursive submodules and dependency source evidence.

Working-tree files are never copied. In particular, local profiles and build-time
FSR patch applications cannot alter the source snapshot; tracked patch recipes are
exported with the host. ZIP entries are regular files, with original Git modes
recorded for consumers that need to restore executable bits or symbolic links.
"""
import argparse
import json
from pathlib import Path
import subprocess

from distribution_support import json_bytes, locked_channel, omitted_asset, sha256, windows_name
from release_support import download, output, write_zip

ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return output('git', '-C', repo, *args)


def export_git(repo, commit, prefix, files, modes, repositories):
    repo = Path(repo)
    if git(repo, 'rev-parse', f'{commit}^{{commit}}') != commit:
        raise ValueError('Source revision does not resolve to the requested commit')
    tree = subprocess.check_output(['git', '-C', str(repo), 'ls-tree', '-r', '-z', commit])
    entries = []
    for row in tree.split(b'\0'):
        if row:
            header, path = row.split(b'\t', 1)
            mode, kind, oid = header.decode('ascii').split()
            name = path.decode('utf-8')
            windows_name(name)
            entries.append((mode, kind, oid, name))
    blob_entries = [entry for entry in entries if entry[1] == 'blob']
    blob_data = subprocess.check_output(
        ['git', '-C', str(repo), 'cat-file', '--batch'],
        input=''.join(entry[2] + '\n' for entry in blob_entries).encode())
    offset = 0
    for mode, _, oid, name in blob_entries:
        end = blob_data.index(b'\n', offset)
        actual_oid, kind, size = blob_data[offset:end].split()
        size = int(size)
        if actual_oid.decode() != oid or kind != b'blob':
            raise ValueError('Unexpected Git object export')
        offset = end + 1
        target = prefix + name
        files[target] = blob_data[offset:offset + size]
        modes[target] = mode
        offset += size + 1
    for mode, kind, oid, name in entries:
        if kind != 'commit':
            continue
        child = repo / name
        if not child.exists():
            raise ValueError(f'Missing initialized submodule: {child}')
        # Read URLs from the committed .gitmodules, not mutable local Git config.
        modules = subprocess.check_output(
            ['git', '-C', str(repo), 'config', '--blob', commit + ':.gitmodules',
             '--get-regexp', r'^submodule\..*\.path$'], text=True)
        key = next((line.split()[0][:-5] for line in modules.splitlines()
                    if line.split(maxsplit=1)[1] == name), None)
        if not key:
            raise ValueError(f'Submodule URL missing from committed metadata: {name}')
        url = git(repo, 'config', '--blob', commit + ':.gitmodules', '--get', key + '.url')
        repositories.append({'path': prefix + name, 'revision': oid, 'repository': url})
        export_git(child, oid, prefix + name + '/', files, modes, repositories)


def dependency_files(inventory_path, files, cache):
    if not inventory_path:
        return {}, False
    inventory_path = Path(inventory_path)
    inventory = json.loads(inventory_path.read_text(encoding='utf-8'))
    if inventory.get('schema_version') != 1:
        raise ValueError('Unsupported dependency inventory')
    sources = inventory.get('source_archives', {})
    for name, item in sources.items():
        windows_name(name)
        if '/' in name:
            raise ValueError('Dependency source names must be basenames')
        if 'path' in item:
            data = (inventory_path.parent / item['path']).read_bytes()
            if sha256(data) != item['sha256']:
                raise ValueError(f'Dependency source checksum mismatch: {name}')
        else:
            data = download(item, cache / name).read_bytes()
        files['dependency-sources/' + name] = data
    notices = inventory.get('license_files', {})
    for name, item in notices.items():
        windows_name(name)
        data = (inventory_path.parent / item['path']).read_bytes()
        if sha256(data) != item['sha256']:
            raise ValueError(f'Dependency notice checksum mismatch: {name}')
        files['dependency-licenses/' + name] = data
    result = {}
    for name, item in inventory.get('files', {}).items():
        windows_name(name)
        record = {k: v for k, v in item.items() if k not in {'path', 'redistribution_ready'}}
        referenced_sources = record.get('source_archives', [])
        referenced_notices = record.get('license_files', [])
        if any(source not in sources for source in referenced_sources):
            raise ValueError(f'Missing dependency source archive for {name}')
        if any(notice not in notices for notice in referenced_notices):
            raise ValueError(f'Missing dependency license for {name}')
        basis = record.get('redistribution_basis')
        ready = bool(record.get('license') and record.get('version')
                     and referenced_notices and len(record.get('sha256', '')) == 64)
        if basis == 'corresponding-source':
            ready = ready and bool(referenced_sources)
        elif basis in ('permissive-license', 'runtime-exception', 'proprietary-redistributable'):
            ready = ready and bool(record.get('basis_note'))
        else:
            ready = False
        record['redistribution_ready'] = ready
        result[name] = record
    files['dependency-inventory.json'] = json_bytes({'schema_version': 1, 'files': result,
                                                    'source_archives': {k: {field: value for field, value in v.items()
                                                                           if field != 'path'} for k, v in sources.items()},
                                                    'license_files': {k: {'sha256': v['sha256']}
                                                                      for k, v in notices.items()}})
    return result, bool(result) and all(item['redistribution_ready'] for item in result.values())


def export(args):
    lock, pin = locked_channel(args.lock, args.channel)
    if git(args.host_source, 'rev-parse', pin['revision'] + ':platform/psn') != pin['psn_tree']:
        raise ValueError('The committed PSN module differs from the locked tree')
    files, modes, submodules = {}, {}, []
    export_git(args.host_source, pin['revision'], 'host/', files, modes, submodules)
    omissions = {}
    for name in list(files):
        # Do not remove upstream library files; scope the policy to the host's own tree.
        if any(name.startswith(module['path'] + '/') for module in submodules):
            continue
        reason = omitted_asset(name.removeprefix('host/'), source=True)
        if reason:
            omissions[name] = {'sha256': sha256(files.pop(name)), 'reason': reason}
            modes.pop(name, None)
    if 'host/LICENSE' not in files or 'host/build.sh' not in files:
        raise ValueError('Host license/build recipe missing from source export')
    files['distribution-lock.json'] = json_bytes(lock)
    # The exact builder recipe is a distinct MIT component, never relicensed as host code.
    for pattern in ('tools/*.py', 'tools/msys2-*.json', '.github/workflows/*distribution*.yml'):
        for path in sorted(ROOT.glob(pattern)):
            files['build-recipes/' + path.relative_to(ROOT).as_posix()] = path.read_bytes()
    files['build-recipes/LICENSE'] = (ROOT / 'LICENSE').read_bytes()
    files['build-recipes/release-lock.json'] = (ROOT / 'release-lock.json').read_bytes()
    release_lock = json.loads((ROOT / 'release-lock.json').read_text(encoding='utf-8'))
    for name, spec in [('build-inputs/nlohmann/json.hpp', release_lock['json']['header']),
                       ('build-inputs/nlohmann/LICENSE', release_lock['json']['license'])]:
        files[name] = download(spec, ROOT / 'out/source-inputs' / Path(name).name).read_bytes()
    runtime, ready = dependency_files(args.dependency_inventory, files, Path(args.output).parent / 'source-cache')
    files['SOURCE-README.txt'] = (
        'Complete tracked host source, recursively pinned submodules, original licenses and patch recipes.\n'
        'host/ is GPL-2.0-or-later; individual bundled components retain their own licenses.\n'
        'No game files, installed profiles or mutable working-tree files were copied.\n'
        'Standalone Windows rebuild (this archive has no Git history):\n'
        '1. Install MSYS2, then from the archive root run Python:\n'
        '   python build-recipes/tools/lock_msys2.py install --msys-root C:/msys64\n'
        '     --lock build-recipes/tools/msys2-packages.json\n'
        '2. In the MSYS2 CLANG64 shell, from the archive root run:\n'
        '   BB_P2P_DISTRIBUTION=ON BB_VERSION=' + pin['upstream']['tag'] + '-' + args.channel + ' bash host/build.sh --test\n'
        '   build.sh applies tracked gpu/patches to the exported FSR originals.\n'
        '3. Build the optional backend independently:\n'
        '   cmake -S host/platform/psn -B backend -G Ninja -DCMAKE_BUILD_TYPE=Release\n'
        '     -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++\n'
        '     -DPSN_BRIDGE_BACKEND=ON -DPSN_HOST_TESTS=ON\n'
        '     -DPSN_JSON_INCLUDE_DIR=<absolute-path-to-build-inputs>\n'
        '   cmake --build backend\n'
        '   ctest --test-dir backend --output-on-failure\n'
        'ci_distribution.py is the release workflow for a Git checkout and requires Git history.\n'
        'Version banners can differ without Git; binary-identical rebuilding is not claimed.\n'
        'ZIP stores symlink targets as text. git_file_modes in source-manifest.json records\n'
        'original executable modes and symlinks (120000) for restoration on Unix.\n'
        'Dependency source/notice coverage is recorded separately; consult redistribution_ready.\n'
    ).encode()
    recipe = {'repository': 'https://github.com/pierluigizagaria/ctrnf-p2p',
              'revision': git(ROOT, 'rev-parse', 'HEAD'),
              'source_dirty': bool(git(ROOT, 'status', '--porcelain'))}
    manifest = {'schema_version': 1, 'component': 'ctrnf-p2p-host-source', 'channel': args.channel,
                'revision': pin['revision'], 'psn_tree': pin['psn_tree'], 'host': pin,
                'submodules': submodules, 'git_file_modes': modes, 'runtime_dependencies': runtime,
                'excluded_non_source_assets': omissions,
                'build_recipe': recipe, 'dependency_evidence_complete': ready,
                'redistribution_ready': ready and not recipe['source_dirty'],
                'files': {name: sha256(data) for name, data in sorted(files.items())}}
    files['source-manifest.json'] = json_bytes(manifest)
    write_zip(args.output, files)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('host-source', 'lock', 'channel', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--dependency-inventory')
    result = export(parser.parse_args())
    print(json.dumps({'revision': result['revision'], 'submodules': len(result['submodules']),
                      'redistribution_ready': result['redistribution_ready']}))


if __name__ == '__main__':
    main()
