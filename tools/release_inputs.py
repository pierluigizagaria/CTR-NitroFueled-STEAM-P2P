"""Resolve only the dependencies pinned by this mod's release-lock.json."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from release_support import archive_member, component, digest, download, revision

ROOT = Path(__file__).resolve().parents[1]


def prepare(full=False):
    lock = json.loads((ROOT / 'release-lock.json').read_text())
    if lock['schema_version'] != 1:
        raise ValueError('Unsupported release lock schema')
    deps = ROOT / 'out/ci-deps'
    download(lock['json']['header'], deps / 'json/include/nlohmann/json.hpp')
    download(lock['json']['license'], deps / 'json/LICENSE')
    pin = lock['components']['orbisteamworks']
    provider = download(pin, deps / 'provider.zip')
    _, files = component(provider, 'orbisteamworks', pin)
    header = deps / 'provider/include/orbisteamworks/osw.h'
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_bytes(files['include/orbisteamworks/osw.h'])
    if not full:
        return lock, deps
    pin = lock['components']['demonware-server']
    server = download(pin, deps / 'server.zip')
    component(server, 'demonware-server', pin)
    pin = lock['components']['signature-patch']
    revision(pin['revision'])
    patch_archive = download(pin, deps / 'patch.zip')
    patch = archive_member(patch_archive, 'ctrnf-server-signature-patch/CrashTeamRacingNitroFueled.xml')
    # Validate the patch before producing a player package, without a game installation.
    doc = ET.fromstring(patch)
    metadata = doc.findall('Metadata')
    if (doc.tag != 'Patch' or [node.text for node in doc.findall('TitleID/ID')] != [lock['host']['title_id']]
            or len(metadata) != 1 or metadata[0].get('AppVer') != lock['host']['game_version']
            or metadata[0].get('AppElf') != 'eboot.bin' or metadata[0].get('isEnabled') != 'false'):
        raise ValueError('Patch does not target the locked game')
    lines = metadata[0].findall('PatchList/Line')
    if len(lines) != 1 or lines[0].attrib != {'Type': 'bytes', 'Address': '0x00413ec0', 'Value': '909090909090'}:
        raise ValueError('Unexpected signature patch instructions')
    (deps / 'patch.xml').write_bytes(patch)
    (deps / 'patch-LICENSE').write_bytes(archive_member(patch_archive, 'ctrnf-server-signature-patch/LICENSE'))
    steam = lock['steam_runtime']
    runtime_archive = download(steam['archive'], deps / 'steam-runtime-source.zip')
    runtime = archive_member(runtime_archive, steam['member'])
    if digest(runtime) != steam['sha256']:
        raise ValueError('Steam runtime checksum mismatch')
    (deps / 'steam_api64.dll').write_bytes(runtime)
    return lock, deps
