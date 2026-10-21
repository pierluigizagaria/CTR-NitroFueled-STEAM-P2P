"""Capture or materialize exact MSYS2 runtime corresponding-source/notice inputs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import urllib.request
import zipfile

from distribution_support import json_bytes, sha256, windows_name
from msys2_metadata import installed
from release_support import download


def source_tar(msys_root):
    """Use the locked native libarchive tool, not MSYS GNU tar's remote-path syntax."""
    tool = Path(msys_root) / 'clang64/bin/bsdtar.exe'
    if not tool.is_file():
        raise ValueError(f'Missing reviewed MSYS2 archive tool: {tool}')
    return tool


def archive_bytes(path, member, inner=None, *, tar='tar'):
    if inner and inner.startswith('git:'):
        _, commit, source_path = inner.split(':', 2)
        if not re.fullmatch('[0-9a-f]{40}', commit):
            raise ValueError('Git source notice requires a full commit')
        bare = Path(str(path) + '.objects') / member
        if not (bare / 'HEAD').exists():
            members = subprocess.check_output([str(tar), '-tf', str(path)], text=True).splitlines()
            for name in members:
                if not name.startswith(member + '/objects/') or name.endswith('/'):
                    continue
                windows_name(name)
                target = Path(str(path) + '.objects') / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(subprocess.check_output([str(tar), '-xOf', str(path), name]))
            bare.mkdir(parents=True, exist_ok=True)
            (bare / 'refs').mkdir(exist_ok=True)
            (bare / 'HEAD').write_text(commit + '\n')
            (bare / 'config').write_text('[core]\nrepositoryformatversion=0\nbare=true\n')
        return subprocess.check_output(['git', '--git-dir=' + str(bare), 'cat-file', '-p', commit + ':' + source_path])
    data = subprocess.check_output([str(tar), '-xOf', str(path), member])
    if inner is None:
        return data
    if member.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return archive.read(inner)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        return archive.extractfile(inner).read()


def source_notices(path, *, tar='tar'):
    members = subprocess.check_output([str(tar), '-tf', str(path)], text=True).splitlines()
    result = []
    for member in members:
        if not member.endswith(('.tar.gz', '.tar.xz', '.tar.bz2', '.tgz', '.tar', '.zip')):
            continue
        data = archive_bytes(path, member, tar=tar)
        try:
            if member.endswith('.zip'):
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    candidates = [(n, archive.read(n)) for n in archive.namelist()
                                  if len(Path(n).parts) <= 2 and not n.endswith('/')
                                  and re.match(r'^(COPYING|LICENSE|LICENCE|NOTICE|COPYRIGHT)', Path(n).name, re.I)]
            else:
                with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                    candidates = [(n.name, archive.extractfile(n).read()) for n in archive.getmembers()
                                  if n.isfile() and len(Path(n.name).parts) <= 2
                                  and re.match(r'^(COPYING|LICENSE|LICENCE|NOTICE|COPYRIGHT)', Path(n.name).name, re.I)]
            result.extend((member, inner, payload) for inner, payload in candidates if len(payload) < 1024 * 1024)
        except (tarfile.TarError, zipfile.BadZipFile):
            continue
    if not result:
        info_member = next((name for name in members if name.endswith('/.SRCINFO')), None)
        if info_member:
            info = archive_bytes(path, info_member, tar=tar).decode('utf-8')
            for alias, kind, value in re.findall(r'source = ([^\s:]+)::git\+[^\s]+#(commit|tag)=([^\s]+)', info):
                prefix = str(Path(info_member).parent.as_posix()) + '/' + alias
                commit = value
                if kind == 'tag':
                    refs = archive_bytes(path, prefix + '/packed-refs', tar=tar).decode('ascii').splitlines()
                    found = next((index for index, line in enumerate(refs)
                                  if line.endswith(' refs/tags/' + value)), None)
                    if found is None:
                        raise ValueError('Tagged source ref missing from source archive')
                    commit = refs[found].split()[0]
                    if found + 1 < len(refs) and refs[found + 1].startswith('^'):
                        commit = refs[found + 1][1:]
                for source_path in ('COPYING', 'LICENSE', 'LICENSE.txt'):
                    inner = 'git:' + commit + ':' + source_path
                    try:
                        result.append((prefix, inner, archive_bytes(path, prefix, inner, tar=tar)))
                    except subprocess.CalledProcessError:
                        continue
    return result


def capture(args):
    root, cache = Path(args.msys_root), Path(args.cache)
    tar = source_tar(root)
    cache.mkdir(parents=True, exist_ok=True)
    packages, owners = installed(root)
    names = {owners.get('clang64/bin/' + file.name.casefold())
             for directory in args.binary_dir for file in Path(directory).glob('*.dll')} - {None}
    build_names = {'mingw-w64-clang-x86_64-' + name for name in
                   ('vulkan-headers', 'vulkan-loader', 'vulkan-memory-allocator', 'glslang',
                    'sdl3', 'fmt', 'boost', 'robin-map', 'xxhash', 'ffmpeg', 'zydis',
                    'spirv-tools', 'spirv-headers', 'spirv-cross', 'zlib')}
    names = sorted(names | (build_names & packages.keys()))
    lock = {'schema_version': 1, 'packages': {}, 'source_archives': {}, 'license_files': {}}

    def one(name):
        meta = packages[name]
        package = {'license_files': [], 'source_archives': []}
        notices, archives = {}, {}
        license_name = ' '.join(meta.get('LICENSE', ['unknown'])).replace('spdx:', '')
        for member in meta['FILES']:
            file = root / member
            if '/share/licenses/' in member and file.is_file():
                key = name + '/' + member.split('/share/licenses/', 1)[1]
                notices[key] = {'installed_path': member, 'sha256': sha256(file.read_bytes())}
                package['license_files'].append(key)
        copyleft = bool(re.search(r'GPL|LGPL|AGPL|MPL', license_name, re.I))
        custom = 'custom' in license_name.lower() or not package['license_files']
        if copyleft or custom or name in build_names:
            filename = meta['BASE'][0] + '-' + meta['VERSION'][0] + '.src.tar.zst'
            url = 'https://repo.msys2.org/mingw/sources/' + filename
            archive = cache / filename
            if not archive.is_file():
                temporary = archive.with_suffix(archive.suffix + '.partial')
                with urllib.request.urlopen(url, timeout=180) as response:
                    with temporary.open('wb') as output:
                        while block := response.read(1024 * 1024):
                            output.write(block)
                temporary.replace(archive)
            archives[filename] = {'url': url, 'sha256': sha256(archive.read_bytes())}
            package['source_archives'].append(filename)
            if not package['license_files']:
                for member, inner, data in source_notices(archive, tar=tar):
                    key = name + '/' + Path(member).name + '/' + (inner.split(':', 2)[-1] if inner.startswith('git:') else inner)
                    windows_name(key)
                    notices[key] = {'archive': filename, 'member': member, 'inner_member': inner,
                                    'sha256': sha256(data)}
                    package['license_files'].append(key)
            package.update(redistribution_basis='corresponding-source',
                           basis_note='Exact MSYS2 source package, including build recipe, patches and upstream source archive.')
        else:
            package.update(redistribution_basis='permissive-license',
                           basis_note='Exact installed package license and notice files; license metadata: ' + license_name)
        if not package['license_files']:
            raise ValueError('No license notice found for ' + name)
        print(name + '@' + meta['VERSION'][0] + ': ' + package['redistribution_basis'], flush=True)
        return name + '@' + meta['VERSION'][0], package, notices, archives

    with ThreadPoolExecutor(max_workers=4) as pool:
        for key, package, notices, archives in pool.map(one, names):
            lock['packages'][key] = package
            lock['license_files'].update(notices)
            lock['source_archives'].update(archives)
    Path(args.lock).write_bytes(json_bytes(lock))
    print(f'Locked {len(names)} runtime packages, {len(lock["source_archives"])} corresponding-source archives')


def materialize(args):
    root, cache, destination = Path(args.msys_root), Path(args.cache), Path(args.output)
    tar = source_tar(root)
    lock = json.loads(Path(args.lock).read_text(encoding='utf-8'))
    if lock.get('schema_version') != 1:
        raise ValueError('Unsupported source lock')
    evidence = {'schema_version': 1, 'packages': lock['packages'], 'source_archives': {}, 'license_files': {}}
    for name, spec in lock['source_archives'].items():
        file = download(spec, cache / name)
        evidence['source_archives'][name] = spec | {'path': str(file.resolve())}
    for name, spec in lock['license_files'].items():
        windows_name(name)
        if 'installed_path' in spec:
            data = (root / spec['installed_path']).read_bytes()
        else:
            data = archive_bytes(cache / spec['archive'], spec['member'], spec.get('inner_member'), tar=tar)
        if sha256(data) != spec['sha256']:
            raise ValueError('Runtime license changed: ' + name)
        file = destination.parent / 'reviewed-licenses' / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        evidence['license_files'][name] = {'path': str(file.resolve()), 'sha256': spec['sha256']}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(json_bytes(evidence))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('capture', 'materialize'))
    for name in ('msys-root', 'cache', 'lock'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--binary-dir', action='append', default=[])
    parser.add_argument('--output')
    args = parser.parse_args()
    (capture if args.operation == 'capture' else materialize)(args)


if __name__ == '__main__':
    main()
