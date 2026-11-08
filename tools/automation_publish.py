"""Publish tested distributions with a P2P main lease and explicit recovery receipt.

Only this trusted job receives write credentials. Downloaded packages are data:
they are fully checked, but no binary or script from them is ever executed here.
GitHub cannot atomically update Git refs and release assets together;
the pending state and final receipt make that boundary explicit and resumable.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import urllib.parse
import urllib.request

import automation_prepare as prepare
import automation_state
from distribution_support import json_bytes, read_zip, sha256, verify_manifest, windows_name
from distribution_validation import validate as validate_distributions


CHANNELS = prepare.CHANNELS
BLOCK_START = '<!-- ctrnf-p2p-automatic-distributions:start -->'
BLOCK_END = '<!-- ctrnf-p2p-automatic-distributions:end -->'


def command(*args, data=None):
    result = subprocess.run([str(arg) for arg in args], input=data,
                            capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'Publication command failed')
    return result.stdout.strip()


def api(path, *, method='GET', body=None):
    args = ['gh', 'api', '--method', method, path]
    if body is not None:
        args += ['--input', '-']
    output = command(*args, data=None if body is None else json.dumps(body))
    return json.loads(output) if output else None


def asset_record(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'name': path.name, 'sha256': digest.hexdigest(), 'size': path.stat().st_size}


def validate_components(files, components, plan, release_lock):
    expected_names = set(release_lock['components']) | {'ctrnf-p2p', 'steamworks-runtime'}
    if (set(components) != expected_names
            or components['ctrnf-p2p'] != {'revision': plan['candidate_revision'], 'license': 'MIT'}):
        raise ValueError('Mod component identity differs from the tested plan')
    for name, expected in release_lock['components'].items():
        actual = components[name]
        for field in ('revision', 'license'):
            if actual.get(field) != expected[field]:
                raise ValueError('Component differs from release-lock.json: ' + name)
        if name != 'signature-patch' and actual.get('version') != expected['version']:
            raise ValueError('Component version differs from release-lock.json: ' + name)
    steam = release_lock['steam_runtime']
    if (sha256(files['steam_api64.dll']) != steam['sha256']
            or components['steamworks-runtime']['sha256'] != steam['sha256']
            or components['steamworks-runtime'].get('sdk_version') != steam['sdk_version']):
        raise ValueError('Steam runtime differs from the permitted locked DLL')


def validate_standalone_mod(directory, plan, release_lock):
    name = f"ctrnf-p2p-mod-{plan['version']}-windows-x64-{plan['candidate_revision'][:12]}.zip"
    path = Path(directory) / name
    if sorted(Path(directory).glob('ctrnf-p2p-mod-*.zip')) != [path]:
        raise ValueError('Exactly the tested standalone mod archive is required')
    files = read_zip(path)
    manifest = verify_manifest(files, 'ctrnf-p2p-manifest.json')
    if (manifest.get('component') != 'ctrnf-p2p-mod' or manifest.get('platform') != 'windows-x64'
            or manifest.get('version') != plan['version'] or manifest.get('host') != release_lock['host']
            or manifest.get('build', {}).get('source_dirty') is not False
            or set(files) != set(manifest['files']) | {'ctrnf-p2p-manifest.json', 'ctrnf-p2p-SHA256SUMS.txt'}
            or json.loads(files['ctrnf-p2p-release-lock.json']) != release_lock
            or json.loads(files['ctrnf-p2p-build-info.json']) != manifest['build']):
        raise ValueError('Standalone mod identity, clean build or complete payload differs from the tested plan')
    validate_components(files, manifest['components'], plan, release_lock)
    checksum = path.with_suffix('.zip.sha256')
    digest = asset_record(path)['sha256']
    if checksum.read_text(encoding='utf-8').strip() != digest + '  ' + name:
        raise ValueError('Standalone mod external archive checksum mismatch')
    return files, manifest, digest, [path, checksum]


def validate_source_recipe(files, pin):
    """Bind embedded GPL recipe and patches to the trusted lock, in memory only."""
    name = windows_name(pin['recipe']['path'])
    raw = files.get(name)
    if raw is None or sha256(raw) != pin['recipe']['sha256']:
        raise ValueError('Embedded integration recipe differs from the tested plan')
    recipe = json.loads(raw)
    if (recipe.get('schema_version') != 1
            or recipe.get('upstream_repository') != pin['upstream']['repository']
            or not recipe.get('commits')):
        raise ValueError('Embedded integration recipe has invalid provenance')
    for entry in recipe['commits']:
        relative = windows_name(entry['patch'])
        path = str(PurePosixPath(name).parent / relative)
        if path not in files or sha256(files[path]) != entry['sha256']:
            raise ValueError('Embedded integration patch differs from the tested recipe')


def validate_assets(directory, plan, release_lock):
    """Bind every payload, source companion and pinned component to the trusted plan."""
    standalone_files, standalone, mod_digest, mod_assets = validate_standalone_mod(directory, plan, release_lock)
    assets = validate_distributions(directory, plan['version'], plan['candidate_revision'])
    for binary in sorted(Path(directory).glob('*-windows-x64.zip')):
        files = read_zip(binary)
        manifest = verify_manifest(files, 'p2p-distribution-manifest.json')
        channel = manifest['channel']
        pin = plan['new_lock']['channels'][channel]
        prefix = f"ctrnf-p2p-{channel}-{plan['version']}-{plan['candidate_revision'][:12]}"
        if binary.name != prefix + '-windows-x64.zip':
            raise ValueError('Distribution filename differs from the tested plan')
        if (manifest['host'] != pin or manifest.get('platform') != 'windows-x64'
                or manifest.get('unresolved_runtime_dependencies') != []
                or set(files) != set(manifest['files']) | {'p2p-distribution-manifest.json', 'p2p-SHA256SUMS.txt'}):
            raise ValueError('Host identity or manifested payload differs from the tested plan')
        build = manifest['host_build']
        if (build.get('source_revision') != pin['revision']
                or build.get('source_tree') != pin['source_tree']
                or build.get('integration_recipe') != pin['recipe']
                or build.get('shared_psn_tree') != pin['psn_tree']
                or build.get('clean_source') is not True
                or build.get('channel', channel) != channel
                or build.get('upstream_revision', pin['upstream']['revision']) != pin['upstream']['revision']
                or build.get('upstream_tag', pin['upstream']['tag']) != pin['upstream']['tag']):
            raise ValueError('Host build receipt differs from the tested plan')
        if (build.get('upstream_version') != pin['upstream']['tag']
                or files.get('bin/VERSION', b'').strip() != (pin['upstream']['tag'] + '-windows').encode()):
            raise ValueError('Host version differs from the tested upstream tag')
        own_binaries = {pin['launcher'], 'bin/sacredfire.exe', 'bin/bb-gpu-capabilities.exe',
                        'psn-bridge-backend.dll'}
        if set(build.get('binaries', {})) != own_binaries:
            raise ValueError('Host build receipt does not cover the four native binaries')
        for name in own_binaries:
            if sha256(files[name]) != build['binaries'][name]:
                raise ValueError('Host binary differs from its build receipt: ' + name)
        if json.loads(files['p2p-host-build.json']) != build:
            raise ValueError('Embedded host receipt differs from the distribution manifest')
        mod = verify_manifest(files, 'ctrnf-p2p-manifest.json')
        if (mod['components'] != manifest['components'] or mod['host'] != pin
                or mod['version'] != plan['version'] or mod.get('build', {}).get('source_dirty') is not False):
            raise ValueError('Embedded mod identity differs from the tested plan')
        if (manifest.get('input_archives', {}).get('mod') != mod_digest
                or mod.get('assembly', {}).get('input_mod_sha256') != mod_digest
                or mod['components'] != standalone['components'] or mod['build'] != standalone['build']
                or set(mod['files']) != set(standalone['files'])):
            raise ValueError('Complete distribution does not use the exact standalone mod build')
        adapted_files = {'ctrnf-p2p.ini', 'CTR-P2P-README.md', 'ctrnf-p2p-docs/INSTALLATION.md'}
        for name in set(standalone['files']) - adapted_files:
            if files[name] != standalone_files[name]:
                raise ValueError('Embedded mod payload differs from the standalone build: ' + name)
        validate_components(files, manifest['components'], plan, release_lock)
        source_name = manifest['sources']['archive']
        if source_name != prefix + '-source.zip':
            raise ValueError('Source filename differs from the tested plan')
        source_files = read_zip(Path(directory) / source_name)
        validate_source_recipe(source_files, pin)
        source = verify_manifest(source_files, 'source-manifest.json')
        if (source.get('host') != pin or source.get('channel') != channel
                or source.get('source_tree') != pin['source_tree']
                or source.get('psn_tree') != pin['psn_tree']
                or source.get('redistribution_ready') is not True
                or source.get('dependency_evidence_complete') is not True
                or set(source_files) != set(source['files']) | {'source-manifest.json'}
                or json.loads(source_files['distribution-lock.json']) != plan['new_lock']
                or json.loads(source_files['build-recipes/release-lock.json']) != release_lock
                or sha256(source_files['source-manifest.json']) != manifest['sources']['manifest_sha256']):
            raise ValueError('Corresponding source evidence differs from the tested plan')
        for name, dependency in source.get('runtime_dependencies', {}).items():
            if (name not in files or sha256(files[name]) != dependency.get('sha256')
                    or dependency.get('redistribution_ready') is not True):
                raise ValueError('Runtime payload differs from corresponding source evidence: ' + name)
    assets.extend(mod_assets)
    if len({path.name for path in assets}) != 10:
        raise ValueError('Exactly ten distinct channel/source/standalone-mod/checksum assets are required')
    return sorted(assets, key=lambda path: (0 if '-source.zip' in path.name else 1, path.name))


def public_name(pin):
    name = pin['display_name'].replace('/', '-') + '-' + pin['upstream']['tag'] + '-STEAM-P2P-windows-x64.zip'
    windows_name(name)
    if '/' in name or not re.fullmatch(r'[A-Za-z0-9_.+-]+', name):
        raise ValueError('Upstream identity cannot be used as a public package name')
    return name


def copy_asset(source, destination):
    """Retain deterministic bytes across publication retries; never silently replace a file."""
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected = dict(asset_record(source), name=destination.name)
    if destination.exists():
        if asset_record(destination) != expected:
            raise ValueError('Existing local publication artifact differs from the tested bytes')
    else:
        shutil.copyfile(source, destination)
    if asset_record(destination) != expected:
        raise ValueError('Publication copy differs from the tested bytes')
    return destination


def public_assets(directory, plan, release_lock):
    """Validate all retained build inputs, then expose only the two self-contained ZIPs."""
    validate_assets(directory, plan, release_lock)
    result = []
    for channel in CHANNELS:
        pin = plan['new_lock']['channels'][channel]
        original = Path(directory) / f"ctrnf-p2p-{channel}-{plan['version']}-{plan['candidate_revision'][:12]}-windows-x64.zip"
        result.append(copy_asset(original, Path(directory) / 'public' / public_name(pin)))
    return result


def owned_asset(name):
    """Only this project's current names and known historical release formats are retired."""
    legacy = (r'ctrnf-p2p-(?:channel-[ab]|getlostin-ctr-nitrofueled-pc|ryu7w7-octr-nitrofueled-pc)-'
              r'v[0-9][A-Za-z0-9.+-]*-[0-9a-f]{12}-(?:source|windows-x64)\.zip(?:\.sha256)?')
    mod = r'ctrnf-p2p-mod-v[0-9][A-Za-z0-9.+-]*-windows-x64(?:-[0-9a-f]{12})?\.zip(?:\.sha256)?'
    receipt = r'ctrnf-p2p-complete-v[0-9][A-Za-z0-9.+-]*-[0-9a-f]{12}\.json'
    current = r'(?:GetLostIn-CTR-NitroFueled-PC|Ryu7w7-OCTR-NitroFueled-PC)-v[0-9][A-Za-z0-9.+-]*-STEAM-P2P-windows-x64\.zip'
    return any(re.fullmatch(pattern, name) for pattern in (legacy, mod, receipt, current))


def stage_name(expected):
    return 'ctrnf-p2p-pending-' + expected['sha256'][:16] + '-' + expected['name']


def previous_name(asset):
    return 'ctrnf-p2p-previous-' + str(asset['id']) + '-' + asset['name']


def remote_identity(asset):
    return {key: asset.get(key) for key in ('id', 'name', 'size', 'state', 'digest')}


def classify_refs(plan, bridge_head):
    if bridge_head == plan['base_revision']:
        return 'all-old'
    if bridge_head == plan['candidate_revision']:
        return 'all-new'
    raise ValueError('Remote main changed outside this plan; manual recovery is required')


class GitRefs:
    def __init__(self, repository, bridge_slug):
        self.repository = Path(repository)
        self.bridge_url = 'https://github.com/' + bridge_slug + '.git'

    def git(self, root, *args):
        return command('git', '-C', root, '-c', 'credential.helper=',
                       '-c', 'credential.helper=!gh auth git-credential', *args)

    def refs(self, root, remote, *patterns):
        result = self.git(root, 'ls-remote', '--refs', remote, *patterns)
        return {line.split()[1]: line.split()[0] for line in result.splitlines()}

    def heads(self):
        bridge = self.refs(self.repository, self.bridge_url, 'refs/heads/main')
        return bridge.get('refs/heads/main')

    def verify_write_access(self, plan):
        """Probe receive-pack authorization without changing refs or creating tags."""
        self.git(self.repository, 'push', '--dry-run',
                 '--force-with-lease=refs/heads/main:' + plan['base_revision'],
                 self.bridge_url, plan['base_revision'] + ':refs/heads/main')

    def promote_bridge(self, plan):
        self.git(self.repository, 'push', '--force-with-lease=refs/heads/main:' + plan['base_revision'],
                 self.bridge_url, plan['candidate_revision'] + ':refs/heads/main')


class GitHubRelease:
    def __init__(self, slug, tag):
        self.slug, self.tag = slug, tag

    def read(self):
        release = api('repos/' + self.slug + '/releases/tags/' + urllib.parse.quote(self.tag, safe=''))
        if release.get('tag_name') != self.tag or release.get('draft'):
            raise ValueError('The existing published preview release is required')
        pages = json.loads(command('gh', 'api', '--paginate', '--slurp',
            f"repos/{self.slug}/releases/{release['id']}/assets?per_page=100"))
        release['assets'] = [asset for page in pages for asset in page]
        if len({asset['name'] for asset in release['assets']}) != len(release['assets']):
            raise ValueError('Release contains duplicate asset names')
        return release

    def verify(self, asset, expected):
        if asset.get('size') != expected['size'] or asset.get('state') != 'uploaded':
            raise ValueError('Remote asset size/state differs: ' + expected['name'])
        digest = asset.get('digest')
        if digest:
            if digest != 'sha256:' + expected['sha256']:
                raise ValueError('Existing release asset differs; it will never be overwritten: ' + expected['name'])
            return
        # Older assets may lack GitHub's digest. Stream the public download instead.
        url = asset['browser_download_url']
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != 'github.com':
            raise ValueError('Unexpected release asset download URL')
        hashed, size = hashlib.sha256(), 0
        request = urllib.request.Request(url, headers={'User-Agent': 'ctrnf-p2p-publisher'})
        with urllib.request.urlopen(request, timeout=120) as response:
            if urllib.parse.urlsplit(response.url).scheme != 'https':
                raise ValueError('Release asset redirected away from HTTPS')
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                size += len(chunk)
                if size > expected['size']:
                    raise ValueError('Remote asset exceeds its expected size')
                hashed.update(chunk)
        if size != expected['size'] or hashed.hexdigest() != expected['sha256']:
            raise ValueError('Existing release asset differs; it will never be overwritten: ' + expected['name'])

    def ensure_asset(self, path, expected):
        if asset_record(path) != expected:
            raise ValueError('Local artifact changed during publication')
        found = {item['name']: item for item in self.read()['assets']}.get(expected['name'])
        if found is not None:
            prefix = 'ctrnf-p2p-pending-' + expected['sha256'][:16] + '-'
            public = expected['name'].removeprefix(prefix)
            empty_starter = (found.get('state') == 'starter' and found.get('size') == 0
                             and expected['name'].startswith(prefix) and owned_asset(public)
                             and public.endswith('-STEAM-P2P-windows-x64.zip'))
            if empty_starter:
                # GitHub can leave a zero-byte starter after an upload 502. Only
                # this transaction's hash-derived staging name may be removed.
                current = next((item for item in self.read()['assets'] if item['id'] == found['id']), None)
                if current is not None:
                    if remote_identity(current) != remote_identity(found):
                        raise ValueError('Incomplete upload changed before recovery')
                    try:
                        api(f"repos/{self.slug}/releases/assets/{found['id']}", method='DELETE')
                    except ValueError:
                        if any(item['id'] == found['id'] for item in self.read()['assets']):
                            raise
            else:
                self.verify(found, expected)
                return
        try:
            # The absence of --clobber is intentional. A concurrent upload cannot be replaced.
            command('gh', 'release', 'upload', self.tag, path, '--repo', self.slug)
        except ValueError:
            # An uncertain network result may have succeeded. Accept only the exact expected bytes.
            found = {item['name']: item for item in self.read()['assets']}.get(expected['name'])
            if found is None:
                raise
        else:
            found = {item['name']: item for item in self.read()['assets']}.get(expected['name'])
        if found is None:
            raise ValueError('Uploaded release asset is missing')
        self.verify(found, expected)

    def rename(self, asset, name):
        """A lost rename response is safe only if this exact asset ID acquired the name."""
        try:
            api(f"repos/{self.slug}/releases/assets/{asset['id']}", method='PATCH', body={'name': name})
        except ValueError:
            current = next((item for item in self.read()['assets'] if item['id'] == asset['id']), None)
            if current is None or current['name'] != name:
                raise
        current = next((item for item in self.read()['assets'] if item['id'] == asset['id']), None)
        if current is None or current['name'] != name:
            raise ValueError('Renamed release asset is missing')
        return current

    def promote_asset(self, expected, previous):
        assets = {item['name']: item for item in self.read()['assets']}
        current = assets.get(expected['name'])
        old = None
        if current is not None:
            try:
                self.verify(current, expected)
                return
            except ValueError:
                old = next((item for item in previous if item['id'] == current['id']), None)
                if old is None or remote_identity(current) != old:
                    raise ValueError('Public asset changed outside the saved replacement transaction')
        staged = assets.get(stage_name(expected))
        if staged is None:
            raise ValueError('Verified staged release asset is missing')
        self.verify(staged, dict(expected, name=stage_name(expected)))
        if old is not None:
            backup_name = previous_name(old)
            if backup_name in assets:
                raise ValueError('Previous-asset backup name already exists')
            self.rename(current, backup_name)
        self.verify(self.rename(staged, expected['name']), expected)

    def prune(self, previous, expected_records):
        """Delete only saved project-owned IDs after both final packages have been verified."""
        assets = self.read()['assets']
        by_name = {item['name']: item for item in assets}
        retained = set()
        for expected in expected_records:
            asset = by_name.get(expected['name'])
            if asset is None:
                raise ValueError('Cannot retire old downloads before the complete pair is available')
            self.verify(asset, expected)
            retained.add(asset['id'])
        for old in previous:
            current = next((item for item in self.read()['assets'] if item['id'] == old['id']), None)
            if current is None or current['id'] in retained:
                continue
            expected = dict(old, name=current['name'])
            if (current['name'] not in (old['name'], previous_name(old))
                    or remote_identity(current) != expected or not owned_asset(old['name'])):
                raise ValueError('Old asset changed outside the saved cleanup transaction')
            try:
                api(f"repos/{self.slug}/releases/assets/{old['id']}", method='DELETE')
            except ValueError:
                if any(item['id'] == old['id'] for item in self.read()['assets']):
                    raise
        remaining = {item['name']: item for item in self.read()['assets']}
        for expected in expected_records:
            if expected['name'] not in remaining:
                raise ValueError('Current download disappeared during cleanup')
            self.verify(remaining[expected['name']], expected)

    def notes(self, plan):
        release = self.read()
        body = release.get('body') or ''
        updated = release_block(self.slug, plan) + '\n'
        title = 'Steam P2P — latest builds'
        if updated != body or release.get('name') != title:
            api(f"repos/{self.slug}/releases/{release['id']}", method='PATCH', body={'body': updated, 'name': title})


def release_block(slug, plan):
    base = f"https://github.com/{slug}/releases/download/{plan['version']}/"
    lines = [BLOCK_START, '### Latest Windows builds', '']
    for channel in CHANNELS:
        pin = plan['new_lock']['channels'][channel]
        lines += [f"- [{pin['display_name']} **{pin['upstream']['tag']}**]({base}{public_name(pin)})"]
    lines += ['', 'Each ZIP includes the port, Steam P2P mod, corresponding sources, licenses and build provenance. '
              'Game files are not included.', BLOCK_END]
    return '\n'.join(lines)


def begin_transaction(plan, records, remote_release, *, resume=False):
    current, ref = automation_state.read_state()
    if resume:
        if (not current or current.get('status') != 'pending' or current.get('plan') != plan
                or current.get('assets') != records or current.get('release_id') != remote_release['id']
                or not current.get('source_run_id') or current.get('publication_format') != 'two-complete-archives-v1'):
            raise ValueError('Resume requires the original pending plan and exact retained build artifacts')
        return current, ref
    if current and current.get('status') == 'pending':
        raise ValueError('A pending publication must be resumed explicitly before starting another update')
    source_run = os.environ.get('GITHUB_RUN_ID', '')
    slug = os.environ.get('GH_REPO', '')
    if not source_run.isdigit():
        raise ValueError('Publication requires its original GitHub Actions run ID')
    pending = {'schema_version': 1, 'status': 'pending', 'plan': deepcopy(plan), 'assets': records,
               'release_id': remote_release['id'], 'source_run_id': source_run,
               'publication_format': 'two-complete-archives-v1',
               'previous_assets': [remote_identity(asset) for asset in remote_release['assets'] if owned_asset(asset['name'])],
               'runtime_source': (current or {}).get('runtime_source'),
               'source_run_url': f'https://github.com/{slug}/actions/runs/{source_run}',
               'created_at': plan['commit_timestamp']}
    return pending, automation_state.write_state(pending, ref)


def publish(plan, assets, refs, release, *, resume=False):
    """A failed test never calls this function; every network write has a preceding receipt."""
    assets = sorted(assets, key=lambda path: path.name)
    if {path.name for path in assets} != {public_name(plan['new_lock']['channels'][channel]) for channel in CHANNELS}:
        raise ValueError('Publication requires exactly the two current upstream packages')
    records = sorted((asset_record(path) for path in assets), key=lambda item: item['name'])
    phase = classify_refs(plan, refs.heads())
    if phase != 'all-old' and not resume:
        raise ValueError('Promoted refs require explicit recovery of the original publication')
    remote_release = release.read()
    pending, state_ref = begin_transaction(plan, records, remote_release, resume=resume)
    for path in assets:
        expected = next(item for item in records if item['name'] == path.name)
        # A resumed transaction may already have promoted either final name.
        current = next((item for item in release.read()['assets'] if item['name'] == path.name), None)
        if current is not None:
            try:
                release.verify(current, expected)
                continue
            except ValueError:
                pass
        staged = copy_asset(path, path.parent / 'staging' / stage_name(expected))
        release.ensure_asset(staged, dict(expected, name=staged.name))
    phase = classify_refs(plan, refs.heads())
    if phase == 'all-old' and plan['changed']:
        try:
            refs.promote_bridge(plan)
        except ValueError as error:
            # A response can be lost after a successful leased push. Never undo
            # another writer's commit; retain the transaction for manual recovery.
            if refs.heads() != plan['candidate_revision']:
                raise ValueError('P2P main promotion failed; the pending receipt and '
                                 'uploaded assets are retained for recovery') from error
    final_phase = classify_refs(plan, refs.heads())
    if final_phase != ('all-new' if plan['changed'] else 'all-old'):
        raise ValueError('Publication did not reach the planned P2P main revision')
    for expected in records:
        release.promote_asset(expected, pending['previous_assets'])
    current_assets = {asset['name']: asset for asset in release.read()['assets']}
    for expected in records:
        if expected['name'] not in current_assets:
            raise ValueError('Current package is missing before recording its runtime source')
        release.verify(current_assets[expected['name']], expected)
    slug = os.environ['GH_REPO']
    runtime_archive = records[0]
    runtime_source = {'url': f"https://github.com/{slug}/releases/download/{plan['version']}/{runtime_archive['name']}",
                      'sha256': runtime_archive['sha256']}
    # Public names can be reused by mod-only updates. Save their current verified
    # bytes before notes/cleanup so a later failure cannot retain an obsolete hash.
    if pending.get('runtime_source') != runtime_source:
        pending = dict(pending, runtime_source=runtime_source)
        state_ref = automation_state.write_state(pending, state_ref)
    release.notes(plan)
    release.prune(pending['previous_assets'], records)
    # Completion is recorded on the state branch, not as a third download.
    receipt = {key: pending[key] for key in ('schema_version', 'plan', 'assets', 'release_id',
                                           'source_run_id', 'source_run_url', 'created_at')}
    receipt['status'] = 'completed'
    completed = dict(receipt, publication_format='two-complete-archives-v1', runtime_source=runtime_source,
                     completion={'revision': plan['candidate_revision'],
                                 'run_url': pending['source_run_url']})
    automation_state.write_state(completed, state_ref)
    return completed


def materialize_candidates(plan, repository, refs, *, resume=False, source_cache=None):
    """A completed main push may leave a resumed checkout at the candidate commit."""
    if resume:
        pending, _ = automation_state.read_state()
        if not pending or pending.get('status') != 'pending' or pending.get('plan') != plan:
            raise ValueError('Resume requires the exact recorded pending plan')
    phase = classify_refs(plan, refs.heads())
    if not resume and phase != 'all-old':
        raise ValueError('Promoted refs require explicit recovery of the original publication')
    head = prepare.clean(repository)
    allowed = {plan['base_revision'], plan['candidate_revision']} if resume else {plan['base_revision']}
    if head not in allowed:
        raise ValueError('The checkout changed outside the pending plan; manual recovery is required')
    if head != plan['base_revision']:
        prepare.git(repository, 'checkout', '--detach', plan['base_revision'])
    prepare.apply_bridge(plan, repository)
    for channel in CHANNELS:
        prepare.prepare_host(plan, channel, repository, source_cache=source_cache)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'dist'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--repository', default='.')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.verify_only and args.resume:
        parser.error('--verify-only and --resume are mutually exclusive')
    plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
    prepare.validate_plan(plan)
    if bool(plan.get('verify')) != args.verify_only:
        raise ValueError('Verification plans cannot publish or be converted to publication plans')
    repository = Path(args.repository).resolve()
    slug = os.environ.get('GH_REPO', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', slug):
        raise ValueError('GH_REPO must identify the controlled bridge repository')
    origin = prepare.git(repository, 'config', '--get', 'remote.origin.url')
    if origin.removesuffix('.git') != 'https://github.com/' + slug:
        raise ValueError('Bridge origin differs from GH_REPO')
    refs = GitRefs(repository, slug)
    release_lock = json.loads((repository / 'release-lock.json').read_text(encoding='utf-8'))
    assets = public_assets(args.dist, plan, release_lock)
    materialize_candidates(plan, repository, refs, resume=args.resume)
    release = GitHubRelease(slug, plan['version'])
    if args.verify_only:
        if classify_refs(plan, refs.heads()) != 'all-old':
            raise ValueError('Verification requires unchanged locked remote refs')
        refs.verify_write_access(plan)
        release.read()
        print(json.dumps({'status': 'verified', 'candidate_revision': plan['candidate_revision'],
                          'assets': [asset_record(path) for path in assets], 'published': False}))
    else:
        result = publish(plan, assets, refs, release, resume=args.resume)
        print(json.dumps({'status': result['status'], 'assets': result['assets'],
                          'candidate_revision': plan['candidate_revision']}))


if __name__ == '__main__':
    main()
