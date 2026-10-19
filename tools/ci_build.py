"""Build/test the bridge and optionally prepare a locked Windows mod release."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import zipfile
from release_support import build_info, cmake_info, digest, output, run, version
from release_inputs import prepare

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', type=version)
    parser.add_argument('--package', action='store_true')
    args = parser.parse_args()
    source_revision = output('git', 'rev-parse', 'HEAD')
    tag = args.version or 'v0.1.0-ci.' + source_revision[:12]
    lock, deps = prepare(args.package)
    run('cmake', '-S', ROOT, '-B', ROOT / 'build/ci', '-A', 'x64',
        '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded', '-DEXPAT_MSVC_STATIC_CRT=ON',
        '-DBUILD_TESTING=ON', '-DOSW_INCLUDE_DIR=' + str(deps / 'provider/include'),
        '-DJSON_INCLUDE_DIR=' + str(deps / 'json/include'))
    run('cmake', '--build', ROOT / 'build/ci', '--config', 'Release', '--parallel', '2')
    run('ctest', '--test-dir', ROOT / 'build/ci', '-C', 'Release', '--output-on-failure', '--timeout', '120')
    if not args.package:
        return
    # Verify the original Valve signature as well as the locked archive/DLL hashes.
    run('pwsh', '-NoProfile', '-File', ROOT / 'tools/verify_steam_runtime.ps1', '-Path', deps / 'steam_api64.dll')
    info_path = deps / 'build-info.json'
    info = build_info()
    info.update(cmake_info(ROOT / 'build/ci'))
    info_path.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    archive = ROOT / 'dist' / f'ctrnf-p2p-mod-{tag}-windows-x64.zip'
    run(sys.executable, ROOT / 'tools/package_mod.py',
        '--bridge-build', ROOT / 'build/ci/Release', '--bridge-revision', source_revision,
        '--provider-package', deps / 'provider.zip', '--server-package', deps / 'server.zip',
        '--patch-xml', deps / 'patch.xml', '--patch-license', deps / 'patch-LICENSE',
        '--patch-revision', lock['components']['signature-patch']['revision'],
        '--json-license', deps / 'json/LICENSE', '--steam-runtime-file', deps / 'steam_api64.dll',
        '--steam-sdk-version', lock['steam_runtime']['sdk_version'],
        '--steam-runtime-sha256', lock['steam_runtime']['sha256'],
        '--release-lock', ROOT / 'release-lock.json', '--build-info', info_path,
        '--version', tag, '--output', archive)
    # Verify every payload again after reading the completed ZIP.
    with zipfile.ZipFile(archive) as package:
        manifest = json.loads(package.read('ctrnf-p2p-manifest.json'))
        if set(package.namelist()) != set(manifest['files']) | {'ctrnf-p2p-manifest.json', 'ctrnf-p2p-SHA256SUMS.txt'}:
            raise ValueError('Unexpected mod archive contents')
        for name, sha in manifest['files'].items():
            if digest(package.read(name)) != sha:
                raise ValueError(f'Packaged hash mismatch: {name}')
        smoke = ROOT / 'out/ci-package-smoke'
        smoke.mkdir(parents=True, exist_ok=True)
        for name in ('ctrnf-p2p-cli.exe', 'orbisteamworks.dll'):
            (smoke / name).write_bytes(package.read(name))
    # --help is read-only; the game and Steam are never started by this workflow.
    run(smoke / 'ctrnf-p2p-cli.exe', '--help', cwd=smoke)


if __name__ == '__main__':
    main()
