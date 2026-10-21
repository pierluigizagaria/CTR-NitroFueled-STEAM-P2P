"""Build one pinned host independently, then assemble its complete P2P distribution."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from distribution_support import json_bytes, locked_channel, read_zip, sha256
from release_support import output, run, version

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrix', action='store_true')
    parser.add_argument('--channel', choices=('channel-a', 'channel-b'))
    parser.add_argument('--host-source', type=Path)
    parser.add_argument('--msys-root', type=Path)
    parser.add_argument('--mod-package', type=Path)
    parser.add_argument('--version', type=version)
    parser.add_argument('--host-package', type=Path, help='Use an explicit prebuilt portable archive')
    parser.add_argument('--host-build-manifest', type=Path)
    parser.add_argument('--backend-dir', type=Path)
    parser.add_argument('--require-redistribution-ready', action='store_true')
    args = parser.parse_args()
    lock_path = ROOT / 'distribution-lock.json'
    if args.matrix:
        matrix = []
        for channel in ('channel-a', 'channel-b'):
            _, pin = locked_channel(lock_path, channel)
            repository = pin['repository'].removeprefix('https://github.com/').removesuffix('.git')
            if repository.count('/') != 1 or not pin['repository'].startswith('https://github.com/'):
                raise ValueError('Workflow checkout requires a GitHub repository')
            matrix.append({'channel': channel, 'repository': repository, 'revision': pin['revision']})
        if len({locked_channel(lock_path, row['channel'])[1]['psn_tree'] for row in matrix}) != 1:
            raise ValueError('Channel PSN module trees differ; review the shared ABI before release')
        print(json.dumps({'include': matrix}, separators=(',', ':')))
        return
    if not all((args.channel, args.host_source, args.msys_root, args.mod_package, args.version)):
        parser.error('Build/assembly requires channel, host-source, msys-root, mod-package and version')
    _, pin = locked_channel(lock_path, args.channel)
    host = args.host_source.resolve()
    if output('git', '-C', host, 'rev-parse', 'HEAD') != pin['revision']:
        raise ValueError('Host checkout differs from the locked integration revision')
    if output('git', '-C', host, 'rev-parse', 'HEAD:platform/psn') != pin['psn_tree']:
        raise ValueError('Host PSN subtree differs from the locked integration')
    source_dirty = bool(output('git', '-C', host, '-c', 'core.longpaths=true', 'status', '--porcelain'))
    deps = ROOT / 'out/distribution' / args.channel
    deps.mkdir(parents=True, exist_ok=True)
    backend = args.backend_dir or host / 'out/p2p-psn/backends'
    receipt = args.host_build_manifest or deps / 'host-build-manifest.json'
    package = args.host_package
    if package is None:
        if source_dirty:
            raise ValueError('Start host build from a clean checkout with initialized submodules')
        env = os.environ | {'BB_P2P_DISTRIBUTION': 'ON', 'MSYS2_ROOT': str(args.msys_root.resolve())}
        run('bash', 'build.sh', '--test', cwd=host, env=env)
        # Test the local-shader preservation change; the upstream broad suite has
        # separately documented unrelated baseline failures on Windows.
        if (host / 'tests/test_ultrawide_local_shaders.py').exists():
            run(sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests',
                '-p', 'test_ultrawide_local_shaders.py', cwd=host, env=env)
        release_lock = json.loads((ROOT / 'release-lock.json').read_text())
        from release_support import download
        header = download(release_lock['json']['header'], deps / 'json/include/nlohmann/json.hpp')
        run('cmake', '-S', host / 'platform/psn', '-B', backend.parent, '-G', 'Ninja',
            '-DCMAKE_BUILD_TYPE=Release', '-DPSN_BRIDGE_BACKEND=ON', '-DPSN_HOST_TESTS=ON',
            '-DCMAKE_C_COMPILER=clang', '-DCMAKE_CXX_COMPILER=clang++',
            '-DPSN_JSON_INCLUDE_DIR=' + str(header.parent.parent), env=env)
        run('cmake', '--build', backend.parent, '--parallel', '2', env=env)
        run('ctest', '--test-dir', backend.parent, '--output-on-failure', '--timeout', '60', env=env)
        portable_dir = deps / 'portable'
        run(sys.executable, host / 'packaging/windows/make_portable.py', '--version', args.version,
            '--dist', portable_dir, cwd=host, env=env)
        package = portable_dir / 'CTR-NitroFueled-PC-portable-windows.zip'
        files = read_zip(package, prefix=pin['portable_root'])
        files['psn-bridge-backend.dll'] = (backend / 'psn-bridge-backend.dll').read_bytes()
        receipt.write_bytes(json_bytes({'schema_version': 1, 'source_revision': pin['revision'],
            'shared_psn_tree': pin['psn_tree'], 'clean_source': True,
            'binaries': {name: sha256(files[name]) for name in
                         (pin['launcher'], 'bin/sacredfire.exe', 'bin/bb-gpu-capabilities.exe', 'psn-bridge-backend.dll')},
            'commands': ['BB_P2P_DISTRIBUTION=ON bash build.sh --test',
                         'cmake platform/psn PSN_BRIDGE_BACKEND=ON PSN_HOST_TESTS=ON',
                         'ctest --output-on-failure', 'packaging/windows/make_portable.py'],
            'tests': ['native PSN CTest', 'PSN backend CTest and HTTP fixtures', 'local shader fixtures when present']}))
    elif not args.host_build_manifest or not args.backend_dir:
        parser.error('Prebuilt input requires --host-build-manifest and --backend-dir')
    evidence = deps / 'source-evidence.json'
    run(sys.executable, ROOT / 'tools/msys2_source_evidence.py', 'materialize',
        '--msys-root', args.msys_root, '--cache', ROOT / 'out/distribution-sources',
        '--lock', ROOT / 'tools/msys2-source-lock.json', '--output', evidence)
    inventory = deps / 'runtime-inventory.json'
    run(sys.executable, ROOT / 'tools/collect_runtime_sources.py', '--host-package', package,
        '--backend-dir', backend, '--msys-root', args.msys_root, '--lock', lock_path,
        '--channel', args.channel, '--source-evidence', evidence, '--output', inventory)
    suffix = output('git', '-C', ROOT, 'rev-parse', '--short=12', 'HEAD')
    stem = f'ctrnf-p2p-{args.channel}-{args.version}-{suffix}'
    source_zip = ROOT / 'dist' / (stem + '-source.zip')
    run(sys.executable, ROOT / 'tools/export_host_source.py', '--host-source', host,
        '--lock', lock_path, '--channel', args.channel, '--dependency-inventory', inventory, '--output', source_zip)
    run(sys.executable, ROOT / 'tools/package_distribution.py', '--host-package', package,
        '--host-build-manifest', receipt, '--backend-dir', backend, '--mod-package', args.mod_package,
        '--source-package', source_zip, '--lock', lock_path, '--channel', args.channel,
        '--version', args.version, '--output', ROOT / 'dist' / (stem + '-windows-x64.zip'),
        *(['--require-redistribution-ready'] if args.require_redistribution_ready else []))


if __name__ == '__main__':
    main()
