"""Validation shared by complete, separately attributed host distributions."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

from release_support import revision, safe_name

RESERVED = re.compile(r'^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', re.I)
PRIVATE_DIRS = {'user', 'orig', 'dlc', 'backups', 'saves', 'savedata', 'profiles',
                'logs', 'data', '.git', '.npauth', '.cache'}
PRIVATE_FILES = {'bbport.ini', 'launcher.ini', 'patches.json', 'mods.json',
                 'eboot.bin', 'param.sfo', 'steam_appid.txt', 'steam_settings.ini'}
CHANNELS = ('getlostin-ctr-nitrofueled-pc', 'ryu7w7-octr-nitrofueled-pc')


def omitted_asset(name, *, source=False):
    """Known optional artwork/game-derived data, not source needed for the host build."""
    path = PurePosixPath(name)
    licensed_art = {'art/ctr-menu.ttf', 'art/ctr-menu-font-license.txt',
                    'art/ctr-menu-background.png', 'art/README.md'}
    if ((path.parts[0].casefold() == 'art' and name not in licensed_art)
            or path.parts[0].casefold() == 'steamgrid' or name.startswith('packaging/windows/steamgrid/')):
        return 'Optional upstream artwork has no redistribution grant in the host source license.'
    if (name.startswith(('scripts/ultrawide_21x9_data/shaders/', 'scripts/ultrawide_32x9_data/shaders/'))
            and path.suffix.casefold() == '.spv'):
        return 'Original game shader; obtain it from the player-owned game cache at runtime.'
    if source and (name in {'packaging/windows/icons/ctr.ico', 'launcher/io.github.sacredfire.Launcher.png'}
                   or (name.startswith('docs/') and path.suffix.casefold() in
                       {'.png', '.jpg', '.jpeg', '.webp', '.ico'})):
        return 'Optional documentation/branding artwork, not compiled source.'
    return None


def windows_name(name):
    safe_name(name)
    for part in PurePosixPath(name).parts:
        if (part.endswith((' ', '.')) or RESERVED.match(part)
                or any(ord(c) < 32 or c in '<>"|?*' for c in part)):
            raise ValueError(f'Unsafe Windows archive name: {name}')
    return name


def player_file(name, allowed_defaults=()):
    windows_name(name)
    parts = PurePosixPath(name).parts
    if (any(part.casefold() in PRIVATE_DIRS for part in parts)
            or (parts[-1].casefold() in PRIVATE_FILES and name not in allowed_defaults)
            or Path(name).suffix.casefold() in {'.pkg', '.pup', '.db', '.sqlite', '.sqlite3', '.pem', '.key', '.log'}
            or any(part.casefold().startswith(('cusa13795', '.env')) for part in parts)):
        raise ValueError(f'Private or game runtime file in package: {name}')


def read_zip(path, *, prefix=None):
    """Read regular files only, detecting aliases before stripping a portable root."""
    files, seen, total = {}, set(), 0
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            name = item.filename.rstrip('/') if item.is_dir() else item.filename
            windows_name(name)
            key = name.casefold()
            if key in seen:
                raise ValueError(f'Duplicate/case-alias archive member: {name}')
            seen.add(key)
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError(f'Non-regular archive member: {name}')
            if item.flag_bits & 1:
                raise ValueError('Encrypted input archives are unsupported')
            if prefix:
                if name == prefix and item.is_dir():
                    continue
                if not name.startswith(prefix + '/'):
                    raise ValueError(f'Unexpected portable root: {name}')
                name = name[len(prefix) + 1:]
            if item.is_dir():
                continue
            total += item.file_size
            if total > 2 * 1024**3 or item.file_size > 1024**3:
                raise ValueError('Input archive exceeds the distribution size limit')
            files[name] = archive.read(item)
    return files


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')


def checksums(files):
    return ''.join(f'{sha256(data)}  {name}\n' for name, data in sorted(files.items())).encode()


def locked_channel(path, channel):
    lock = json.loads(Path(path).read_text(encoding='utf-8'))
    if lock.get('schema_version') != 2 or channel not in CHANNELS:
        raise ValueError('Unsupported distribution lock/channel')
    pin = lock['channels'][channel]
    revision(pin['revision'])
    revision(pin['upstream']['revision'])
    revision(pin['psn_tree'])
    revision(pin['source_tree'])
    if ('branch' in pin or pin['host_mode'] not in ('psn', 'octr')
            or pin['repository'] != pin['upstream']['repository']):
        raise ValueError('Invalid upstream source/mode')
    for url in (pin['repository'], pin['upstream']['repository']):
        if not url.startswith('https://') or '@' in url.split('/')[2]:
            raise ValueError('Source repositories must use credential-free HTTPS URLs')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', pin['display_name']):
        raise ValueError('Distribution name must identify the upstream author/repository')
    if pin['repository'] != 'https://github.com/' + pin['display_name'] + '.git':
        raise ValueError('Distribution name differs from the upstream repository')
    windows_name(pin['recipe']['path'])
    if (not pin['recipe']['path'].startswith('integrations/' + pin['display_name'] + '/')
            or not re.fullmatch(r'[0-9a-f]{64}', pin['recipe']['sha256'])):
        raise ValueError('Invalid integration recipe path/checksum')
    windows_name(pin['launcher'])
    windows_name(pin['portable_root'])
    if '/' in pin['portable_root']:
        raise ValueError('Portable root must be one directory')
    return lock, pin


def verify_manifest(files, name):
    manifest = json.loads(files[name])
    expected = manifest['files']
    for path, checksum in expected.items():
        windows_name(path)
        if path not in files or sha256(files[path]) != checksum:
            raise ValueError(f'Manifest checksum mismatch: {path}')
    return manifest


def add_files(target, incoming, allowed_defaults=()):
    """Identical shared notices/payloads may overlap; never replace different data."""
    aliases = {name.casefold(): name for name in target}
    for name, data in incoming.items():
        player_file(name, allowed_defaults)
        previous = aliases.get(name.casefold())
        if previous is not None and (previous != name or target[previous] != data):
            raise ValueError(f'Conflicting distribution inputs: {previous} / {name}')
        aliases[name.casefold()] = name
        target[name] = data
