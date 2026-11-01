"""Resolve only the dependencies pinned by this mod's release-lock.json."""
import base64
import json
from pathlib import Path
import re
import urllib.parse
import xml.etree.ElementTree as ET
from release_support import archive_member, component, digest, download, output, revision

ROOT = Path(__file__).resolve().parents[1]


def runtime_archive_spec(steam):
    """Use the completed full package after public sidecars have been retired.

    The trusted repository's saved archive hash and the separately pinned DLL
    hash are both mandatory. Network/state errors never select an unverified
    fallback; the historical bootstrap is used only before this format exists.
    """
    parsed = urllib.parse.urlsplit(steam['archive']['url'])
    match = re.fullmatch(r'/([^/]+/[^/]+)/releases/download/[^/]+/[^/]+', parsed.path)
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or not match:
        raise ValueError('Steam bootstrap must identify this project GitHub release')
    slug = match.group(1)
    response = json.loads(output('gh', 'api', f'repos/{slug}/contents/automation-state.json?ref=automation/state'))
    if response.get('encoding') != 'base64' or response.get('size', 0) > 1024 * 1024:
        raise ValueError('Invalid runtime source state document')
    state = json.loads(base64.b64decode(response['content']))
    if state.get('schema_version') != 1 or state.get('status') not in ('pending', 'blocked', 'completed'):
        raise ValueError('Invalid runtime source automation state')
    spec = state.get('runtime_source')
    if spec is None:
        if state.get('publication_format') == 'two-complete-archives-v1':
            raise ValueError('Completed two-package publication has no retained runtime source')
        return steam['archive']
    selected = urllib.parse.urlsplit(spec.get('url', ''))
    prefix = f'/{slug}/releases/download/'
    if (selected.scheme != 'https' or selected.netloc != 'github.com' or selected.query or selected.fragment
            or not selected.path.startswith(prefix) or not re.fullmatch(r'[0-9a-f]{64}', spec.get('sha256', ''))
            or not re.fullmatch(r'(GetLostIn-CTR-NitroFueled-PC|Ryu7w7-OCTR-NitroFueled-PC)-v[0-9][A-Za-z0-9.+-]*-STEAM-P2P-windows-x64\.zip',
                                selected.path.rsplit('/', 1)[-1])):
        raise ValueError('Runtime source must be a verified complete package in the same repository')
    return spec


def prepare_runtime(steam, deps):
    spec = runtime_archive_spec(steam)
    # Content-addressed caching avoids reusing the older archive after rotation.
    runtime_archive = download(spec, Path(deps) / ('steam-runtime-' + spec['sha256'] + '.zip'))
    runtime = archive_member(runtime_archive, steam['member'])
    if digest(runtime) != steam['sha256']:
        raise ValueError('Steam runtime checksum mismatch')
    (Path(deps) / 'steam_api64.dll').write_bytes(runtime)


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
    prepare_runtime(lock['steam_runtime'], deps)
    return lock, deps
