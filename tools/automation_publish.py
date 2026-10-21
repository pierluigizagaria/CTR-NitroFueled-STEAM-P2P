"""Publish a tested two-channel plan with leases and an explicit recovery receipt.

Only this trusted job receives write credentials. Downloaded packages are data:
they are fully checked, but no binary or script from them is ever executed here.
GitHub cannot atomically update two repositories and release assets together;
the pending state and final receipt make that boundary explicit and resumable.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request

import automation_prepare as prepare
import automation_state
from distribution_support import json_bytes, read_zip, sha256, verify_manifest
from draft_distributions import validate as validate_distributions


CHANNELS = ('channel-a', 'channel-b')
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


def validate_assets(directory, plan, release_lock):
    """Bind every payload, source companion and pinned component to the trusted plan."""
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
                or build.get('shared_psn_tree') != pin['psn_tree']
                or build.get('clean_source') is not True
                or build.get('channel', channel) != channel
                or build.get('upstream_revision', pin['upstream']['revision']) != pin['upstream']['revision']
                or build.get('upstream_tag', pin['upstream']['tag']) != pin['upstream']['tag']):
            raise ValueError('Host build receipt differs from the tested plan')
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
        for name, expected in release_lock['components'].items():
            actual = manifest['components'][name]
            for field in ('revision', 'license'):
                if actual.get(field) != expected[field]:
                    raise ValueError('Component differs from release-lock.json: ' + name)
            if name != 'signature-patch' and actual.get('version') != expected['version']:
                raise ValueError('Component version differs from release-lock.json: ' + name)
        steam = release_lock['steam_runtime']
        if (sha256(files['steam_api64.dll']) != steam['sha256']
                or manifest['components']['steamworks-runtime']['sha256'] != steam['sha256']):
            raise ValueError('Steam runtime differs from the permitted locked DLL')
        source_name = manifest['sources']['archive']
        if source_name != prefix + '-source.zip':
            raise ValueError('Source filename differs from the tested plan')
        source_files = read_zip(Path(directory) / source_name)
        source = verify_manifest(source_files, 'source-manifest.json')
        if (source.get('host') != pin or source.get('channel') != channel
                or source.get('psn_tree') != pin['psn_tree']
                or source.get('redistribution_ready') is not True
                or source.get('dependency_evidence_complete') is not True
                or set(source_files) != set(source['files']) | {'source-manifest.json'}
                or json.loads(source_files['distribution-lock.json']) != plan['new_lock']
                or json.loads(source_files['build-recipes/release-lock.json']) != release_lock
                or sha256(source_files['source-manifest.json']) != manifest['sources']['manifest_sha256']):
            raise ValueError('Corresponding source evidence differs from the tested plan')
    if len({path.name for path in assets}) != 8:
        raise ValueError('Exactly eight distinct channel/source/checksum assets are required')
    return sorted(assets, key=lambda path: (0 if '-source.zip' in path.name else 1, path.name))


def classify_refs(plan, host_heads, bridge_head):
    old = {channel: plan['channels'][channel]['expected_old_revision'] for channel in CHANNELS}
    new = {channel: plan['channels'][channel]['candidate_revision'] for channel in CHANNELS}
    if host_heads == old and bridge_head == plan['base_revision']:
        return 'all-old'
    if host_heads == new and bridge_head == plan['base_revision']:
        return 'hosts-new'
    if host_heads == new and bridge_head == plan['candidate_revision']:
        return 'all-new'
    raise ValueError('Remote refs are mixed or changed outside this plan; manual recovery is required')


class GitRefs:
    def __init__(self, repository, host_source, bridge_slug, host_slug):
        self.repository, self.host_source = Path(repository), Path(host_source)
        self.bridge_url = 'https://github.com/' + bridge_slug + '.git'
        self.host_url = 'git@github.com:' + host_slug + '.git'

    def git(self, root, *args):
        return command('git', '-C', root, '-c', 'credential.helper=',
                       '-c', 'credential.helper=!gh auth git-credential', *args)

    def refs(self, root, remote, *patterns):
        result = self.git(root, 'ls-remote', '--refs', remote, *patterns)
        return {line.split()[1]: line.split()[0] for line in result.splitlines()}

    def heads(self):
        hosts = self.refs(self.host_source, self.host_url, 'refs/heads/p2p/channel-*')
        bridge = self.refs(self.repository, self.bridge_url, 'refs/heads/main')
        return ({channel: hosts.get('refs/heads/p2p/' + channel) for channel in CHANNELS},
                bridge.get('refs/heads/main'))

    def promote_hosts(self, plan):
        tags = self.refs(self.host_source, self.host_url, 'refs/tags/p2p/channel-*/*')
        options, specs = ['--atomic'], []
        for channel in CHANNELS:
            entry, branch = plan['channels'][channel], 'refs/heads/p2p/' + channel
            options += ['--force-with-lease=' + branch + ':' + entry['expected_old_revision']]
            specs += [entry['candidate_revision'] + ':' + branch]
            for sha in sorted({entry['expected_old_revision'], entry['candidate_revision']}):
                tag = 'refs/tags/p2p/' + channel + '/' + sha
                if tag in tags:
                    if tags[tag] != sha:
                        raise ValueError('Immutable source tag has another target: ' + tag)
                else:
                    options += ['--force-with-lease=' + tag + ':']
                    specs += [sha + ':' + tag]
        self.git(self.host_source, 'push', *options, self.host_url, *specs)

    def promote_bridge(self, plan):
        self.git(self.repository, 'push', '--force-with-lease=refs/heads/main:' + plan['base_revision'],
                 self.bridge_url, plan['candidate_revision'] + ':refs/heads/main')

    def verify_source_tags(self, plan):
        tags = self.refs(self.host_source, self.host_url, 'refs/tags/p2p/channel-*/*')
        for channel in CHANNELS:
            entry = plan['channels'][channel]
            for sha in {entry['expected_old_revision'], entry['candidate_revision']}:
                if tags.get('refs/tags/p2p/' + channel + '/' + sha) != sha:
                    raise ValueError('Source preservation tag is missing or changed: ' + channel)

    def rollback_hosts(self, plan):
        options, specs = ['--atomic'], []
        for channel in CHANNELS:
            entry, branch = plan['channels'][channel], 'refs/heads/p2p/' + channel
            options += ['--force-with-lease=' + branch + ':' + entry['candidate_revision']]
            specs += [entry['expected_old_revision'] + ':' + branch]
        self.git(self.host_source, 'push', *options, self.host_url, *specs)


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

    def notes(self, plan, receipt_name):
        release = self.read()
        body = release.get('body') or ''
        block = release_block(self.slug, plan, receipt_name)
        if BLOCK_START in body or BLOCK_END in body:
            if body.count(BLOCK_START) != 1 or body.count(BLOCK_END) != 1:
                raise ValueError('Ambiguous automatic release-notes block')
            start, end = body.index(BLOCK_START), body.index(BLOCK_END) + len(BLOCK_END)
            if start >= end:
                raise ValueError('Malformed automatic release-notes block')
            updated = body[:start] + block + body[end:]
        else:
            updated = body.rstrip() + '\n\n' + block + '\n'
        if updated != body:
            api(f"repos/{self.slug}/releases/{release['id']}", method='PATCH', body={'body': updated})


def release_block(slug, plan, receipt_name):
    base = f"https://github.com/{slug}/releases/download/{plan['version']}/"
    lines = [BLOCK_START, '### Latest completed automatic P2P build', '',
             'Bridge revision: `' + plan['candidate_revision'] + '`.', '']
    for channel in CHANNELS:
        prefix = f"ctrnf-p2p-{channel}-{plan['version']}-{plan['candidate_revision'][:12]}"
        lines += [f"- {channel}: [Windows x64]({base}{prefix}-windows-x64.zip), "
                  f"[corresponding sources]({base}{prefix}-source.zip)."]
    lines += ['', f'[Completion receipt and asset hashes]({base}{receipt_name}).', '',
              'Both channels passed offline build, adapter and package checks. '
              'Live multiplayer acceptance remains separate. Earlier preview assets remain available.', BLOCK_END]
    return '\n'.join(lines)


def begin_transaction(plan, records, release_id, *, resume=False):
    current, ref = automation_state.read_state()
    if resume:
        if (not current or current.get('status') != 'pending' or current.get('plan') != plan
                or current.get('assets') != records or current.get('release_id') != release_id
                or not current.get('source_run_id')):
            raise ValueError('Resume requires the original pending plan and exact retained build artifacts')
        return current, ref
    if current and current.get('status') == 'pending':
        raise ValueError('A pending publication must be resumed explicitly before starting another update')
    source_run = os.environ.get('GITHUB_RUN_ID', '')
    slug = os.environ.get('GH_REPO', '')
    if not source_run.isdigit():
        raise ValueError('Publication requires its original GitHub Actions run ID')
    pending = {'schema_version': 1, 'status': 'pending', 'plan': deepcopy(plan), 'assets': records,
               'release_id': release_id, 'source_run_id': source_run,
               'source_run_url': f'https://github.com/{slug}/actions/runs/{source_run}',
               'created_at': plan['commit_timestamp']}
    return pending, automation_state.write_state(pending, ref)


def publish(plan, assets, refs, release, *, resume=False):
    """A failed test never calls this function; every network write has a preceding receipt."""
    assets = sorted(assets, key=lambda path: (0 if '-source.zip' in path.name else 1, path.name))
    records = sorted((asset_record(path) for path in assets), key=lambda item: item['name'])
    phase = classify_refs(plan, *refs.heads())
    if phase != 'all-old' and not resume:
        raise ValueError('Promoted refs require explicit recovery of the original publication')
    remote_release = release.read()
    existing = {item['name']: item for item in remote_release['assets']}
    for expected in records:
        if expected['name'] in existing:
            release.verify(existing[expected['name']], expected)
    pending, state_ref = begin_transaction(plan, records, remote_release['id'], resume=resume)
    for path in assets:  # validate_assets orders all source assets before binary assets.
        release.ensure_asset(path, next(item for item in records if item['name'] == path.name))
    phase = classify_refs(plan, *refs.heads())
    if phase == 'all-old' and plan['changed']:
        try:
            refs.promote_hosts(plan)
        except ValueError:
            if refs.heads()[0] != {channel: plan['channels'][channel]['candidate_revision'] for channel in CHANNELS}:
                raise
        try:
            refs.verify_source_tags(plan)
            hosts, bridge = refs.heads()
            phase = classify_refs(plan, hosts, bridge)
            if hosts == {channel: plan['channels'][channel]['candidate_revision'] for channel in CHANNELS}:
                if bridge == plan['base_revision']:
                    phase = 'hosts-new'  # An upstream tag-only change can retain both host SHAs.
        except ValueError as error:
            # A main writer can race between native promotion and our bridge push,
            # including while source tags are being verified. Restore only the
            # native refs still at this transaction's exact candidate heads.
            hosts, bridge = refs.heads()
            if (hosts == {channel: plan['channels'][channel]['candidate_revision'] for channel in CHANNELS}
                    and bridge != plan['candidate_revision']):
                try:
                    refs.rollback_hosts(plan)
                except ValueError as rollback_error:
                    raise ValueError('Post-promotion checks failed and host rollback was rejected; '
                                     'the pending receipt requires manual recovery') from rollback_error
                raise ValueError('Post-promotion checks failed; host branches were restored with leases. '
                                 'The pending receipt and uploaded assets are retained') from error
            raise ValueError('Refs or source tags changed after native promotion; manual recovery is required') from error
    if phase == 'hosts-new':
        try:
            refs.promote_bridge(plan)
        except ValueError as error:
            hosts, bridge = refs.heads()
            if hosts == {channel: plan['channels'][channel]['candidate_revision'] for channel in CHANNELS}:
                if bridge == plan['candidate_revision']:
                    pass  # The push succeeded but its response was lost.
                else:
                    # Preserve another writer's bridge commit and never undo a later host update.
                    try:
                        refs.rollback_hosts(plan)
                    except ValueError as rollback_error:
                        raise ValueError('Bridge promotion failed and host rollback was rejected; '
                                         'the pending receipt requires manual recovery') from rollback_error
                    raise ValueError('Bridge promotion failed; host branches were restored with leases. '
                                     'The pending receipt and uploaded assets are retained') from error
            else:
                raise ValueError('Refs changed during bridge promotion; manual recovery is required') from error
    final_phase = classify_refs(plan, *refs.heads())
    if final_phase != ('all-new' if plan['changed'] else 'all-old'):
        raise ValueError('Publication did not promote both repositories')
    if plan['changed']:
        refs.verify_source_tags(plan)
    # Notification/incident metadata can be added after a failed attempt. It must
    # never change the immutable completion bytes on a later exact-plan resume.
    receipt = {key: pending[key] for key in ('schema_version', 'plan', 'assets', 'release_id',
                                           'source_run_id', 'source_run_url', 'created_at')}
    receipt['status'] = 'completed'
    name = f"ctrnf-p2p-complete-{plan['version']}-{plan['candidate_revision'][:12]}.json"
    receipt_path = Path(assets[0]).parent / name
    receipt_path.write_bytes(json_bytes(receipt))
    # This last release asset is the completion marker; partial uploads never advertise one.
    release.ensure_asset(receipt_path, asset_record(receipt_path))
    release.notes(plan, name)
    completed = dict(receipt, completion_asset=name,
                     completion={'asset': name, 'revision': plan['candidate_revision'],
                                 'run_url': pending['source_run_url']})
    automation_state.write_state(completed, state_ref)
    return completed


def materialize_candidates(plan, repository, host_source, refs, *, resume=False):
    """A completed main push may leave a resumed checkout at the candidate commit."""
    if resume:
        pending, _ = automation_state.read_state()
        if not pending or pending.get('status') != 'pending' or pending.get('plan') != plan:
            raise ValueError('Resume requires the exact recorded pending plan')
    phase = classify_refs(plan, *refs.heads())
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
        prepare.prepare_host(plan, channel, host_source, validate_remote=not resume)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'dist', 'host-source'):
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
    refs = GitRefs(repository, args.host_source, slug, plan['host_repository'])
    release_lock = json.loads((repository / 'release-lock.json').read_text(encoding='utf-8'))
    assets = validate_assets(args.dist, plan, release_lock)
    materialize_candidates(plan, repository, args.host_source, refs, resume=args.resume)
    release = GitHubRelease(slug, plan['version'])
    if args.verify_only:
        if classify_refs(plan, *refs.heads()) != 'all-old':
            raise ValueError('Verification requires unchanged locked remote refs')
        release.read()
        print(json.dumps({'status': 'verified', 'candidate_revision': plan['candidate_revision'],
                          'assets': [asset_record(path) for path in assets], 'published': False}))
    else:
        result = publish(plan, assets, refs, release, resume=args.resume)
        print(json.dumps({'status': result['status'], 'completion_asset': result['completion_asset'],
                          'candidate_revision': plan['candidate_revision']}))


if __name__ == '__main__':
    main()
