"""Plan and reproduce exact upstream-update commits without publishing any refs."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

from distribution_support import json_bytes, locked_channel, sha256
import prepare_upstream_update as updater
from release_support import revision, version


CHANNELS = ('channel-a', 'channel-b')


def git(repo, *args, data=None, env=None):
    result = subprocess.run(['git', '-C', str(repo), *map(str, args)], input=data,
                            capture_output=True, env=env)
    if result.returncode:
        raise ValueError(result.stderr.decode('utf-8', errors='replace').strip() or 'Git command failed')
    return result.stdout.decode('utf-8').strip()


def clean(repo, expected=None):
    current = revision(git(repo, 'rev-parse', 'HEAD'))
    if expected is not None and current != expected:
        raise ValueError('The checkout is not at the plan base revision')
    if git(repo, 'status', '--porcelain'):
        raise ValueError('Automation preparation requires a clean checkout')
    return current


def identity_value(identity):
    if not isinstance(identity, dict) or set(identity) != {'name', 'email'}:
        raise ValueError('Commit identity requires exactly name and email')
    for value in identity.values():
        if (not isinstance(value, str) or not value.strip()
                or any(ord(char) < 32 or char in '<>' for char in value)):
            raise ValueError('Invalid commit identity')
    if '@' not in identity['email']:
        raise ValueError('Commit identity requires an email address')
    return dict(identity)


def timestamp_value(timestamp):
    parsed = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ')
    if parsed.strftime('%Y-%m-%dT%H:%M:%SZ') != timestamp:
        raise ValueError('Commit timestamp must be UTC YYYY-MM-DDTHH:MM:SSZ')
    return timestamp


def host_url(slug):
    if not isinstance(slug, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', slug):
        raise ValueError('Controlled host repository must be an owner/repository slug')
    return 'https://github.com/' + slug.removesuffix('.git') + '.git'


def config(repo):
    value = json.loads((Path(repo) / 'automation.json').read_text(encoding='utf-8'))
    if value.get('schema_version') != 1:
        raise ValueError('Unsupported automation configuration')
    version(value['release_tag'])
    host_url(value['host_repository'])
    identity_value(value['commit_identity'])
    return value


def validate_lock(lock):
    if set(lock.get('channels', {})) != set(CHANNELS):
        raise ValueError('The automation requires exactly both locked channels')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'lock.json'
        path.write_bytes(json_bytes(lock))
        for channel in CHANNELS:
            locked_channel(path, channel)
    if len({lock['channels'][channel]['psn_tree'] for channel in CHANNELS}) != 1:
        raise ValueError('Both channels must use the same locked PSN tree')


def check_host(repo, lock, repository, *, validate_remote=True):
    expected_url = host_url(repository)
    actual_url = git(repo, 'config', '--get', 'remote.origin.url')
    if actual_url.removesuffix('.git') != expected_url.removesuffix('.git'):
        raise ValueError('Host origin is not the configured controlled repository')
    for channel in CHANNELS:
        pin = lock['channels'][channel]
        if pin['repository'].removesuffix('.git') != expected_url.removesuffix('.git'):
            raise ValueError('The host lock differs from the controlled repository')
        # The inspector fetches origin before planning; publication must separately use these leases.
        if validate_remote:
            remote = git(repo, 'rev-parse', '--verify', 'refs/remotes/origin/' + pin['branch'])
            if remote != pin['revision']:
                raise ValueError('Fetched host channel head differs from the lock: ' + channel)
        if git(repo, 'rev-parse', pin['revision'] + ':platform/psn') != pin['psn_tree']:
            raise ValueError('Fetched host PSN tree differs from the lock: ' + channel)


@contextmanager
def commit_environment(identity, timestamp, *, author=False):
    """Apply process-local Git settings; preserve original authors during cherry-picks."""
    identity_value(identity)
    timestamp_value(timestamp)
    with tempfile.TemporaryDirectory() as directory:
        updates = {'GIT_COMMITTER_NAME': identity['name'], 'GIT_COMMITTER_EMAIL': identity['email'],
                   'GIT_COMMITTER_DATE': timestamp}
        for field, value in (('NAME', identity['name']), ('EMAIL', identity['email']), ('DATE', timestamp)):
            updates['GIT_AUTHOR_' + field] = value if author else None
        count = int(os.environ.get('GIT_CONFIG_COUNT', '0'))
        options = (('commit.gpgsign', 'false'), ('commit.cleanup', 'verbatim'),
                   ('i18n.commitEncoding', 'UTF-8'), ('rerere.enabled', 'false'),
                   ('core.hooksPath', str(Path(directory).resolve())))
        for offset, (key, value) in enumerate(options):
            updates['GIT_CONFIG_KEY_' + str(count + offset)] = key
            updates['GIT_CONFIG_VALUE_' + str(count + offset)] = value
        updates['GIT_CONFIG_COUNT'] = str(count + len(options))
        previous = {key: os.environ.get(key) for key in updates}
        try:
            for key, value in updates.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def fingerprint(base, lock, tag):
    targets = {channel: lock['channels'][channel]['upstream'] for channel in CHANNELS}
    return sha256(json_bytes({'base_revision': base, 'upstream': targets, 'version': tag}))


def message(old, new):
    changes = [channel + ': ' + old['channels'][channel]['upstream']['tag'] + ' -> '
               + new['channels'][channel]['upstream']['tag'] + ' ('
               + new['channels'][channel]['upstream']['revision'][:12] + ')'
               for channel in CHANNELS if old['channels'][channel] != new['channels'][channel]]
    return 'Update native P2P channels from upstream releases\n\n' + '\n'.join(changes) + '\n'


def prospective_commit(repo, base, old, new, identity, timestamp, commit_message):
    if old == new:
        return base
    mode = git(repo, 'ls-tree', base, '--', 'distribution-lock.json').split()[0]
    if mode != '100644':
        raise ValueError('distribution-lock.json must be a regular non-executable tracked file')
    with tempfile.TemporaryDirectory() as directory, commit_environment(identity, timestamp, author=True):
        environment = os.environ.copy()
        environment['GIT_INDEX_FILE'] = str(Path(directory).resolve() / 'candidate-index')
        git(repo, 'read-tree', base, env=environment)
        blob = git(repo, 'hash-object', '-w', '--stdin', data=json_bytes(new), env=environment)
        git(repo, 'update-index', '--cacheinfo', '100644,' + blob + ',distribution-lock.json', env=environment)
        tree = git(repo, 'write-tree', env=environment)
        candidate = revision(git(repo, 'commit-tree', tree, '-p', base,
                                 data=commit_message.encode('utf-8'), env=environment))
    if git(repo, 'diff-tree', '--no-commit-id', '--name-only', '-r', base, candidate) != 'distribution-lock.json':
        raise ValueError('The prospective commit changed more than the distribution lock')
    return candidate


def validate_plan(receipt):
    if receipt.get('schema_version') != 1:
        raise ValueError('Unsupported automation plan')
    old, new = receipt['original_lock'], receipt['new_lock']
    validate_lock(old)
    validate_lock(new)
    revision(receipt['base_revision'])
    revision(receipt['candidate_revision'])
    identity_value(receipt['commit_identity'])
    timestamp_value(receipt['commit_timestamp'])
    version(receipt['version'])
    expected_url = host_url(receipt['host_repository'])
    if any(old['channels'][channel]['repository'].removesuffix('.git') != expected_url.removesuffix('.git')
           for channel in CHANNELS):
        raise ValueError('The plan lock differs from the controlled repository')
    if type(receipt['changed']) is not bool or type(receipt['verify']) is not bool:
        raise ValueError('Plan changed/verify flags must be booleans')
    if set(receipt['channels']) != set(CHANNELS):
        raise ValueError('The plan must cover both channels')
    expected = deepcopy(old)
    for channel in CHANNELS:
        entry, before, after = receipt['channels'][channel], old['channels'][channel], new['channels'][channel]
        revision(entry['candidate_revision'])
        if type(entry['changed']) is not bool:
            raise ValueError('Channel changed flags must be booleans')
        if (entry['expected_old_revision'] != before['revision'] or entry['psn_tree'] != before['psn_tree']
                or entry['candidate_revision'] != after['revision'] or entry['upstream'] != after['upstream']):
            raise ValueError('Channel provenance does not match the lock: ' + channel)
        if entry['changed'] != (before['upstream'] != after['upstream']):
            raise ValueError('Inconsistent changed-channel flag')
        if not entry['changed'] and before['revision'] != after['revision']:
            raise ValueError('An unchanged upstream cannot replace its integration commit')
        expected['channels'][channel]['revision'] = entry['candidate_revision']
        expected['channels'][channel]['upstream']['tag'] = after['upstream']['tag']
        expected['channels'][channel]['upstream']['revision'] = after['upstream']['revision']
    if expected != new or receipt['changed'] != (old != new):
        raise ValueError('Only channel/upstream revisions and upstream tags may change')
    if receipt['fingerprint'] != fingerprint(receipt['base_revision'], new, receipt['version']):
        raise ValueError('Plan fingerprint mismatch')
    if receipt['commit_message'] != message(old, new):
        raise ValueError('Unexpected prospective commit message')
    if not receipt['changed'] and receipt['candidate_revision'] != receipt['base_revision']:
        raise ValueError('Unchanged verification must use the base commit')


def replay(host_repo, old_lock, channel, upstream, identity, timestamp):
    with tempfile.TemporaryDirectory() as directory, commit_environment(identity, timestamp):
        lock = Path(directory) / 'lock.json'
        lock.write_bytes(json_bytes(old_lock))
        result = updater.prepare(argparse.Namespace(host_source=host_repo, lock=lock, channel=channel,
            upstream_tag=upstream['tag'], upstream_revision=upstream['revision']))
    if result['status'] not in {'prepared', 'unchanged'}:
        error = ValueError('Upstream replay did not produce a clean candidate: ' + channel)
        error.candidate = result
        raise error
    if result['psn_tree'] != old_lock['channels'][channel]['psn_tree']:
        error = ValueError('Automatic replay changed the shared PSN tree: ' + channel)
        error.candidate = result
        raise error
    if result.get('candidate_worktree'):
        try:
            clean(result['candidate_worktree'], result['candidate_revision'])
        except ValueError as error:
            error.candidate = result
            raise
    return result


def plan(base_repo, host_repo, latest_reports, fixed_timestamp, identity=None, verify=False):
    base_repo, host_repo = Path(base_repo).resolve(), Path(host_repo).resolve()
    base = clean(base_repo)
    settings = config(base_repo)
    selected_identity = identity_value(identity or settings['commit_identity'])
    if selected_identity != settings['commit_identity']:
        raise ValueError('Commit identity differs from automation.json')
    timestamp_value(fixed_timestamp)
    old = json.loads((base_repo / 'distribution-lock.json').read_text(encoding='utf-8'))
    validate_lock(old)
    check_host(host_repo, old, settings['host_repository'])
    if set(latest_reports) != set(CHANNELS):
        raise ValueError('Official release reports must cover both channels')
    new, channels = deepcopy(old), {}
    for channel in CHANNELS:
        before, report = old['channels'][channel], latest_reports[channel]
        target = {'repository': report['upstream_repository'], 'tag': report['upstream_tag'],
                  'revision': revision(report['upstream_revision'])}
        if (report.get('channel') != channel or report.get('locked_upstream') != before['upstream']
                or target['repository'] != before['upstream']['repository']):
            raise ValueError('Release report is stale or refers to another upstream: ' + channel)
        changed = target != before['upstream']
        if report.get('status') != ('changed' if changed else 'unchanged'):
            raise ValueError('Release report status disagrees with its revision')
        candidate = before['revision']
        if changed:
            result = replay(host_repo, old, channel, target, selected_identity, fixed_timestamp)
            candidate = result['candidate_revision']
        new['channels'][channel]['revision'] = candidate
        new['channels'][channel]['upstream'] = target
        channels[channel] = {'changed': changed, 'expected_old_revision': before['revision'],
                             'candidate_revision': candidate, 'psn_tree': before['psn_tree'], 'upstream': target}
    commit_message = message(old, new)
    candidate = prospective_commit(base_repo, base, old, new, selected_identity, fixed_timestamp, commit_message)
    clean(base_repo, base)
    receipt = {'schema_version': 1, 'base_revision': base, 'candidate_revision': candidate,
               'original_lock': old, 'new_lock': new, 'channels': channels,
               'commit_identity': selected_identity, 'commit_timestamp': fixed_timestamp,
               'commit_message': commit_message, 'version': settings['release_tag'],
               'host_repository': settings['host_repository'], 'changed': old != new, 'verify': bool(verify),
               'fingerprint': fingerprint(base, new, settings['release_tag'])}
    validate_plan(receipt)
    return receipt


def apply_bridge(receipt, repo):
    validate_plan(receipt)
    repo = Path(repo).resolve()
    clean(repo, receipt['base_revision'])
    settings = config(repo)
    if (settings['commit_identity'] != receipt['commit_identity']
            or settings['release_tag'] != receipt['version']
            or settings['host_repository'] != receipt['host_repository']
            or json.loads((repo / 'distribution-lock.json').read_text(encoding='utf-8')) != receipt['original_lock']):
        raise ValueError('Base checkout configuration differs from the plan')
    candidate = prospective_commit(repo, receipt['base_revision'], receipt['original_lock'], receipt['new_lock'],
                                   receipt['commit_identity'], receipt['commit_timestamp'], receipt['commit_message'])
    if candidate != receipt['candidate_revision']:
        raise ValueError('Recreated bridge candidate does not match the planned revision')
    git(repo, 'checkout', '--detach', candidate)
    clean(repo, candidate)
    return {'schema_version': 1, 'status': 'materialized', 'candidate_revision': candidate,
            'changed': receipt['changed'], 'clean_source': True, 'repository': str(repo)}


def prepare_host(receipt, channel, hostrepo, *, validate_remote=True):
    """Recreate a candidate; resume callers may separately validate old/new remote leases."""
    validate_plan(receipt)
    if channel not in CHANNELS:
        raise ValueError('Unknown host channel')
    hostrepo = Path(hostrepo).resolve()
    old, entry = receipt['original_lock'], receipt['channels'][channel]
    check_host(hostrepo, old, receipt['host_repository'], validate_remote=validate_remote)
    if entry['changed']:
        result = replay(hostrepo, old, channel, entry['upstream'], receipt['commit_identity'], receipt['commit_timestamp'])
    else:
        result = {'candidate_revision': entry['candidate_revision'], 'psn_tree': entry['psn_tree']}
    if result['candidate_revision'] != entry['candidate_revision'] or result['psn_tree'] != entry['psn_tree']:
        error = ValueError('Recreated host candidate does not match the planned revision and PSN tree')
        error.candidate = result
        raise error
    if not result.get('candidate_worktree'):
        if git(hostrepo, 'rev-parse', 'HEAD') == entry['candidate_revision'] and not git(hostrepo, 'status', '--porcelain'):
            result['candidate_worktree'] = str(hostrepo)
    if not result.get('candidate_worktree'):
        listing = git(hostrepo, 'worktree', 'list', '--porcelain', '-z').split('\0')
        owner = Path(listing[0].removeprefix('worktree ')).resolve()
        directory = (owner / 'out/worktrees' / ('verify-' + channel + '-' + uuid.uuid4().hex[:10])).resolve()
        if not directory.is_relative_to(owner):
            raise ValueError('Candidate path escapes the host checkout')
        directory.parent.mkdir(parents=True, exist_ok=True)
        git(hostrepo, 'worktree', 'add', '--detach', directory, entry['candidate_revision'])
        result['candidate_worktree'] = str(directory)
    clean(result['candidate_worktree'], entry['candidate_revision'])
    return {'schema_version': 1, 'status': 'materialized', 'channel': channel,
            'candidate_revision': entry['candidate_revision'], 'psn_tree': entry['psn_tree'],
            'candidate_worktree': result['candidate_worktree'], 'host_source': result['candidate_worktree'],
            'clean_source': True}


def output_destination(path, repositories, inputs):
    destination = Path(path).resolve()
    if destination in {Path(item).resolve() for item in inputs if item}:
        raise ValueError('Output must not replace an input')
    for repository in repositories:
        if not repository:
            continue
        root = Path(repository).resolve()
        if destination.is_relative_to(root):
            relative = destination.relative_to(root).as_posix()
            tracked = git(root, 'ls-files', '--', relative)
            ignored = subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', '--', relative],
                                     capture_output=True).returncode == 0
            if tracked or not ignored:
                raise ValueError('Output inside a source checkout must be an ignored untracked path')
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    planning = commands.add_parser('plan')
    for name in ('repository', 'host-source', 'reports', 'timestamp', 'output'):
        planning.add_argument('--' + name, required=True)
    planning.add_argument('--verify', action='store_true')
    bridge = commands.add_parser('materialize-bridge')
    for name in ('repository', 'plan', 'output'):
        bridge.add_argument('--' + name, required=True)
    host = commands.add_parser('materialize-host')
    for name in ('host-source', 'plan', 'channel', 'output'):
        host.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        destination = output_destination(args.output,
            (getattr(args, 'repository', None), getattr(args, 'host_source', None)),
            (getattr(args, 'plan', None), getattr(args, 'reports', None)))
        if args.operation == 'plan':
            result = plan(args.repository, args.host_source,
                          json.loads(Path(args.reports).read_text(encoding='utf-8')), args.timestamp, verify=args.verify)
        else:
            receipt = json.loads(Path(args.plan).read_text(encoding='utf-8'))
            result = apply_bridge(receipt, args.repository) if args.operation == 'materialize-bridge' else prepare_host(receipt, args.channel, args.host_source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(json_bytes(result))
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({'schema_version': 1, 'status': 'failed', 'error': str(error),
                          'candidate': getattr(error, 'candidate', None)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
