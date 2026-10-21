"""Read installed pacman metadata without invoking an MSYS subprocess."""
from pathlib import Path


def sections(path):
    result, key = {}, None
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.startswith('%') and line.endswith('%'):
            key = line.strip('%')
            result[key] = []
        elif line and key:
            result[key].append(line)
    return result


def installed(root):
    packages, owners = {}, {}
    for directory in sorted((Path(root) / 'var/lib/pacman/local').iterdir()):
        if not (directory / 'desc').exists():
            continue
        meta = sections(directory / 'desc')
        name = meta['NAME'][0]
        meta['FILES'] = sections(directory / 'files').get('FILES', [])
        packages[name] = meta
        for file in meta['FILES']:
            if not file.endswith('/'):
                owners[file.casefold()] = name
    return packages, owners
