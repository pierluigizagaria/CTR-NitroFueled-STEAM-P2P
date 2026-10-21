"""Assemble a clean host portable archive, verified mod, backend and source sidecar."""
import argparse
import configparser
import io
import json
from pathlib import Path

from distribution_support import (add_files, checksums, json_bytes, locked_channel,
                                  omitted_asset, read_zip, sha256, verify_manifest)
from release_support import version, write_zip


def player_guide(channel, tag, pin, source_name):
    return f'''# CTR:NF P2P complete preview — {channel}

This package includes the rebuilt native host, its PSN adapter, the independent
Steam P2P bridge, provider and local publisher server. Game and firmware files
are not included. Build/package tests do not establish live multiplayer acceptance.

1. Extract this package to a new folder.
2. Supply your own CUSA13795 game files with update 01.21 using the host launcher.
3. Start Steam and sign in, then open `ctrnf-p2p.exe`.
4. Use the native launcher to choose your game files and start the game.

Always enter P2P through `ctrnf-p2p.exe`. It starts the local server and enables
the required signature patch. Use the same channel and complete package build
on both PCs, with distinct Steam accounts. This preview is {tag}; compare the
full ZIP filename when updating. The configured host mode is `{pin['host_mode']}`.
AppID 480 is Valve's SDK example ID; it is not an AppID assigned to this project.

For updates use a complete package for this channel. Stock upstream updates are
disabled in this integration build because they replace the required adapter.
Preserve existing native settings, saves and server data; never overwrite your
`ctrnf-p2p.ini` with defaults when updating. Normal and unlock-all progression
share the local database; `server.unlock_all` changes only the active economy mode.

Read `ctrnf-p2p-docs/CONFIGURATION.md` for component settings. A Steam account
change ends the current session. Restart the bridge after closing/restarting the
game. `ctrnf-p2p-cli.exe --check` is a read-only file/configuration check.

The original host is attributed in LICENSE, THIRD-PARTY.txt and the manifest:
{pin['upstream']['repository']} at {pin['upstream']['tag']}.
This integration's source commit is {pin['revision']} in {pin['repository']}.
The matching host/submodule/dependency source companion is `{source_name}`;
its hash is in `p2p-distribution-manifest.json`. Keep it available alongside this ZIP.
Separate bridge, provider, server, patch and Valve licenses remain under licenses/.
This package does not relicense its components or include other Steamworks SDK files.
'''.encode('utf-8')


def assemble(args):
    tag = version(args.version)
    _, pin = locked_channel(args.lock, args.channel)
    host = read_zip(args.host_package, prefix=pin['portable_root'])
    omitted = {}
    # Upstream optional launcher artwork has no redistribution grant in the source tree.
    # Omit it explicitly, retaining its hashes as evidence of the input transformation.
    for name in list(host):
        if omitted_asset(name):
            omitted[name] = sha256(host.pop(name))
    for required in (pin['launcher'], 'bin/sacredfire.exe', 'run.py', 'LICENSE', 'THIRD-PARTY.txt'):
        if required not in host:
            raise ValueError(f'Host portable input is missing {required}')
    mod = read_zip(args.mod_package)
    manifest = verify_manifest(mod, 'ctrnf-p2p-manifest.json')
    if (manifest.get('component') != 'ctrnf-p2p-mod' or manifest['version'] != tag
            or manifest['platform'] != 'windows-x64'):
        raise ValueError('Unexpected mod identity/version/platform')
    if set(mod) != set(manifest['files']) | {'ctrnf-p2p-manifest.json', 'ctrnf-p2p-SHA256SUMS.txt'}:
        raise ValueError('Mod ZIP contains unmanifested payloads')
    source = read_zip(args.source_package)
    source_manifest = verify_manifest(source, 'source-manifest.json')
    if set(source) != set(source_manifest['files']) | {'source-manifest.json'}:
        raise ValueError('Source companion contains unmanifested payloads')
    if (source_manifest.get('component') != 'ctrnf-p2p-host-source'
            or source_manifest.get('channel') != args.channel
            or source_manifest.get('revision') != pin['revision']
            or source_manifest.get('psn_tree') != pin['psn_tree']):
        raise ValueError('Source companion does not match the locked host')
    defaults = set()
    if 'bbport.ini' in host:
        if host['bbport.ini'] != source.get('host/packaging/windows/portable/bbport.ini'):
            raise ValueError('Host settings are not the exact committed portable defaults')
        defaults.add('bbport.ini')
    backend = {}
    if args.backend_dir:
        for file in sorted(Path(args.backend_dir).iterdir()):
            if file.suffix.casefold() == '.dll':
                if file.is_symlink() or not file.is_file():
                    raise ValueError(f'Backend runtime is not a regular file: {file.name}')
                backend[file.name] = file.read_bytes()
    if 'psn-bridge-backend.dll' not in backend:
        raise ValueError('The selected PSN integration requires psn-bridge-backend.dll')
    build_manifest = json.loads(Path(args.host_build_manifest).read_text(encoding='utf-8'))
    if (build_manifest.get('schema_version') != 1 or build_manifest.get('source_revision') != pin['revision']
            or build_manifest.get('shared_psn_tree') != pin['psn_tree']
            or build_manifest.get('clean_source') is not True):
        raise ValueError('Host build evidence does not match the clean locked source')
    for name in (pin['launcher'], 'bin/sacredfire.exe', 'bin/bb-gpu-capabilities.exe', 'psn-bridge-backend.dll'):
        if name not in host | backend or build_manifest.get('binaries', {}).get(name) != sha256((host | backend)[name]):
            raise ValueError('Host build artifact checksum mismatch: ' + name)

    config = configparser.ConfigParser(interpolation=None)
    config.read_string(mod['ctrnf-p2p.ini'].decode('utf-8-sig'))
    config.set('game', 'host', pin['host_mode'])
    stream = io.StringIO()
    config.write(stream)
    mod['ctrnf-p2p.ini'] = stream.getvalue().encode('utf-8')
    guide = player_guide(args.channel, tag, pin, Path(args.source_package).name)
    mod['CTR-P2P-README.md'] = guide
    mod['ctrnf-p2p-docs/INSTALLATION.md'] = guide
    manifest['host'] = pin
    manifest['assembly'] = {'input_mod_sha256': sha256(Path(args.mod_package).read_bytes()),
                            'changes': ['ctrnf-p2p.ini: game.host=' + pin['host_mode'],
                                        'Player installation guides describe the complete package.']}
    manifest['files']['ctrnf-p2p.ini'] = sha256(mod['ctrnf-p2p.ini'])
    for name in ('CTR-P2P-README.md', 'ctrnf-p2p-docs/INSTALLATION.md'):
        manifest['files'][name] = sha256(mod[name])
    mod['ctrnf-p2p-manifest.json'] = json_bytes(manifest)
    mod['ctrnf-p2p-SHA256SUMS.txt'] = checksums({k: v for k, v in mod.items()
                                              if k != 'ctrnf-p2p-SHA256SUMS.txt'})
    files = {}
    if 'p2p-distribution.json' in host:
        marker = json.loads(host.pop('p2p-distribution.json'))
        if marker.get('channel') != args.channel:
            raise ValueError('Host portable marker belongs to a different channel')
    add_files(files, host, defaults)
    add_files(files, backend)
    add_files(files, mod)
    generated = {'p2p-distribution.json': json_bytes({
        'schema_version': 1, 'channel': args.channel, 'version': tag,
        'host_revision': pin['revision'], 'host_mode': pin['host_mode'],
        'updates': 'Install a complete package from this distribution; stock updates are disabled.'})}
    add_files(files, generated)
    add_files(files, {'p2p-host-build.json': json_bytes(build_manifest)})
    add_files(files, {'licenses/runtime/' + name.removeprefix('dependency-licenses/'): data
                      for name, data in source.items() if name.startswith('dependency-licenses/')})
    add_files(files, {'HOST-LICENSE-NOTICE.txt': (
        'The original host source retains its GPL-2.0-or-later license and contributor notices.\n'
        'This Windows host build links the GPL-3.0-or-later FFmpeg package and is distributed\n'
        'under GPL version 3 or later. Full dependency license texts, including GPLv3,\n'
        'are in licenses/runtime/. Separately distributed components retain their own licenses.\n'
        'The accompanying source ZIP includes the host, submodules, build recipes, patches\n'
        'and corresponding sources of bundled copyleft dependencies. See the source manifest\n'
        'for exact revisions, archive hashes and the source repository of each component.\n'
    ).encode()})

    inventory = source_manifest.get('runtime_dependencies', {})
    unresolved = []
    host_binaries = {pin['launcher'], 'bin/sacredfire.exe', 'bin/bb-gpu-capabilities.exe',
                     'psn-bridge-backend.dll'}
    for name, data in (host | backend).items():
        if Path(name).suffix.casefold() not in ('.dll', '.pyd', '.exe') or name in host_binaries:
            continue
        item = inventory.get(name)
        if (not item or item.get('sha256') != sha256(data)
                or not item.get('redistribution_ready')):
            unresolved.append(name)
    complete = (not unresolved and source_manifest.get('redistribution_ready') is True
                and source_manifest.get('build_recipe', {}).get('source_dirty') is False)
    if args.require_redistribution_ready and not complete:
        raise ValueError('Dependency source/notice evidence is incomplete: ' + ', '.join(unresolved))
    sources = {'archive': Path(args.source_package).name,
               'sha256': sha256(Path(args.source_package).read_bytes()),
               'manifest_sha256': sha256(source['source-manifest.json'])}
    distribution = {'schema_version': 1, 'component': 'ctrnf-p2p-distribution',
                    'channel': args.channel, 'version': tag, 'platform': 'windows-x64',
                    'host': pin, 'host_build': build_manifest,
                    'components': manifest['components'], 'build': manifest.get('build', {}),
                    'sources': sources, 'redistribution_ready': complete,
                    'unresolved_runtime_dependencies': sorted(unresolved),
                    'input_archives': {'host': sha256(Path(args.host_package).read_bytes()),
                                       'mod': sha256(Path(args.mod_package).read_bytes())},
                    'omitted_optional_artwork': omitted,
                    'qualification': 'Offline build/package checks only; live multiplayer is unqualified.',
                    'files': {name: sha256(data) for name, data in sorted(files.items())}}
    add_files(files, {'p2p-distribution-manifest.json': json_bytes(distribution)})
    add_files(files, {'p2p-SHA256SUMS.txt': checksums(files)})
    write_zip(args.output, files)
    verify_manifest(read_zip(args.output), 'p2p-distribution-manifest.json')
    return distribution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('host-package', 'host-build-manifest', 'mod-package', 'source-package', 'lock', 'channel', 'version', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--backend-dir', required=True)
    parser.add_argument('--require-redistribution-ready', action='store_true')
    manifest = assemble(parser.parse_args())
    print(json.dumps({'channel': manifest['channel'],
                      'redistribution_ready': manifest['redistribution_ready'],
                      'unresolved_runtime_dependencies': manifest['unresolved_runtime_dependencies']}))


if __name__ == '__main__':
    main()
