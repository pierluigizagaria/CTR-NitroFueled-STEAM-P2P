"""Capture hash-pinned CLANG64 package inputs or install that reviewed lock."""
import argparse
import json
from pathlib import Path
import subprocess

from distribution_support import json_bytes, sha256
from msys2_metadata import installed
from release_support import download


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('capture', 'install'))
    parser.add_argument('--msys-root', required=True)
    parser.add_argument('--lock', required=True)
    args = parser.parse_args()
    root = Path(args.msys_root)
    path = Path(args.lock)
    if args.operation == 'capture':
        packages, _ = installed(root)
        records = []
        missing = []
        for name, meta in packages.items():
            if not name.startswith('mingw-w64-clang-x86_64-'):
                continue
            version = meta['VERSION'][0]
            matches = sorted((root / 'var/cache/pacman/pkg').glob(f'{name}-{version}-*.pkg.tar.*'))
            matches = [p for p in matches if not p.name.endswith('.sig')]
            if len(matches) != 1:
                missing.append(name + '@' + version)
                continue
            package = matches[0]
            records.append({'name': name, 'version': version, 'filename': package.name,
                            'url': 'https://repo.msys2.org/mingw/clang64/' + package.name,
                            'sha256': sha256(package.read_bytes())})
        if missing:
            raise ValueError('Exact installed archives absent from cache: ' + ', '.join(missing))
        path.write_bytes(json_bytes({'schema_version': 1, 'environment': 'CLANG64', 'packages': records}))
        print(f'Locked {len(records)} compiler/library packages')
    else:
        lock = json.loads(path.read_text(encoding='utf-8'))
        if lock['schema_version'] != 1 or lock['environment'] != 'CLANG64':
            raise ValueError('Unsupported toolchain lock')
        paths = [download(item, root / 'var/cache/pacman/pkg' / item['filename']) for item in lock['packages']]
        # All CLANG64 transitive packages come from the same reviewed snapshot.
        subprocess.run([str(root / 'usr/bin/pacman.exe'), '--noconfirm', '-U', '--needed',
                        *map(str, paths)], check=True)
        actual, _ = installed(root)
        for item in lock['packages']:
            if actual[item['name']]['VERSION'][0] != item['version']:
                raise ValueError(f'Installed dependency version differs: {item["name"]}')


if __name__ == '__main__':
    main()
