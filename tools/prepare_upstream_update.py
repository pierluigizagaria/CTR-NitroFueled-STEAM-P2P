"""Replay one locked integration on an upstream release in a retained candidate worktree.

The channel branch, current checkout and lock are never updated. Fetches only the
explicit upstream tag into a unique private ref. A conflict remains available for
manual resolution; build, review and promotion are separate operations.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request
import uuid

from distribution_support import locked_channel
from release_support import revision


def git(repo, *args, check=True):
    result = subprocess.run(['git', '-C', str(repo), *map(str, args)],
                            text=True, capture_output=True)
    if check and result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or 'Git command failed')
    return result


def value(repo, *args):
    return git(repo, *args).stdout.strip()


def commit(repo, name):
    return revision(value(repo, 'rev-parse', '--verify', name + '^{commit}'))


def upstream_api(repository):
    parsed = urllib.parse.urlsplit(repository)
    match = re.fullmatch(r'/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?', parsed.path)
    if (parsed.scheme != 'https' or parsed.netloc.lower() != 'github.com'
            or parsed.query or parsed.fragment or not match):
        raise ValueError('Latest-release checks require the locked official HTTPS GitHub repository')
    return 'https://api.github.com/repos/' + '/'.join(match.groups())


def github_json(url):
    request = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'ctrnf-p2p-upstream-check'})
    with urllib.request.urlopen(request, timeout=30) as response:
        if urllib.parse.urlsplit(response.url).scheme != 'https':
            raise ValueError('Release metadata redirected away from HTTPS')
        return json.load(response)


def latest(lock, channel):
    _, pin = locked_channel(lock, channel)
    api = upstream_api(pin['upstream']['repository'])
    release = github_json(api + '/releases/latest')
    tag = release['tag_name']
    if not isinstance(tag, str) or not tag or release.get('draft') or release.get('prerelease'):
        raise ValueError('The latest endpoint did not return a stable published release')
    item = github_json(api + '/git/ref/tags/' + urllib.parse.quote(tag, safe=''))['object']
    for _ in range(8):
        sha = revision(item['sha'])
        if item['type'] == 'commit':
            break
        if item['type'] != 'tag':
            raise ValueError('The release tag does not identify a commit')
        item = github_json(api + '/git/tags/' + sha)['object']
    else:
        raise ValueError('Excessive annotated-tag indirection')
    changed = (tag, sha) != (pin['upstream']['tag'], pin['upstream']['revision'])
    return {'schema_version': 1, 'status': 'changed' if changed else 'unchanged',
            'channel': channel, 'upstream_repository': pin['upstream']['repository'],
            'upstream_tag': tag, 'upstream_revision': sha,
            'locked_upstream': pin['upstream'], 'read_only': True}


def build_commands(worktree):
    cwd = str(worktree)
    return [{'cwd': cwd, 'argv': args} for args in (
        ['git', 'submodule', 'update', '--init', '--recursive'],
        ['bash', 'build.sh', '--test'],
        ['python', '-B', '-m', 'unittest', 'discover', '-s', 'tests'],
        ['cmake', '-S', 'platform/psn', '-B', 'out/psn-bridge', '-G', 'Ninja',
         '-DCMAKE_BUILD_TYPE=Release', '-DPSN_BRIDGE_BACKEND=ON'],
        ['cmake', '--build', 'out/psn-bridge'],
        ['ctest', '--test-dir', 'out/psn-bridge', '--output-on-failure'])]


def prepare(args):
    _, pin = locked_channel(args.lock, args.channel)
    repo = Path(args.host_source).resolve()
    new_revision = revision(args.upstream_revision)
    if git(repo, 'check-ref-format', 'refs/tags/' + args.upstream_tag, check=False).returncode:
        raise ValueError('Invalid upstream tag name')
    old_revision = commit(repo, pin['upstream']['revision'])
    integration = commit(repo, pin['revision'])
    if value(repo, 'rev-parse', integration + ':platform/psn') != pin['psn_tree']:
        raise ValueError('The locked integration does not contain the locked PSN tree')
    channel_ref = git(repo, 'show-ref', '--verify', '--hash', 'refs/heads/' + pin['branch'], check=False)
    if channel_ref.returncode == 0 and channel_ref.stdout.strip() != integration:
        raise ValueError('The local channel branch differs from the lock; review it before preparing an update')
    if git(repo, 'merge-base', '--is-ancestor', old_revision, integration, check=False).returncode:
        raise ValueError('The locked upstream is not an ancestor of the integration')
    commits = value(repo, 'rev-list', '--reverse', '--topo-order',
                    old_revision + '..' + integration).splitlines()
    parent = old_revision
    for sha in commits:
        if value(repo, 'rev-list', '--parents', '-n', '1', sha).split()[1:] != [parent]:
            raise ValueError('Non-linear integration history needs manual review; no commits were replayed')
        parent = sha

    # The first worktree is the owning checkout even when --host-source is itself a worktree.
    listing = value(repo, 'worktree', 'list', '--porcelain', '-z').split('\0')
    if not listing[0].startswith('worktree ') or 'bare' in listing:
        raise ValueError('An owning non-bare host checkout is required')
    owner = Path(listing[0][len('worktree '):]).resolve()
    destination = (owner / 'out' / 'worktrees').resolve()
    if not destination.is_relative_to(owner):
        raise ValueError('The candidate worktree directory escapes the owning host checkout')
    nonce = uuid.uuid4().hex[:10]
    label = args.channel + '-' + new_revision[:12] + '-' + nonce
    fetched_ref = 'refs/p2p-candidates/' + label + '/upstream'
    git(repo, 'fetch', '--no-tags', '--no-write-fetch-head', '--no-recurse-submodules',
        '--no-auto-maintenance', pin['upstream']['repository'],
        'refs/tags/' + args.upstream_tag + ':' + fetched_ref)
    if commit(repo, fetched_ref) != new_revision:
        raise ValueError('The fetched official upstream tag differs from --upstream-revision')
    if git(repo, 'merge-base', '--is-ancestor', old_revision, new_revision, check=False).returncode:
        raise ValueError('The requested release rewrites or predates the locked upstream; review it manually')
    if new_revision == old_revision:
        return {'schema_version': 1, 'status': 'unchanged', 'channel': args.channel,
                'upstream_tag': args.upstream_tag, 'upstream_revision': new_revision,
                'candidate_revision': integration, 'psn_tree': pin['psn_tree'],
                'fetched_ref': fetched_ref, 'lock_modified': False}

    candidate = destination / ('p2p-' + label)
    branch = 'p2p/candidate/' + label
    result = {'schema_version': 1, 'channel': args.channel, 'candidate_branch': branch,
              'candidate_worktree': str(candidate), 'upstream_repository': pin['upstream']['repository'],
              'upstream_tag': args.upstream_tag, 'upstream_revision': new_revision,
              'previous_integration_revision': integration, 'previous_upstream_revision': old_revision,
              'integration_commits': commits, 'fetched_ref': fetched_ref, 'lock_modified': False,
              'promotion_required': True, 'next_commands': build_commands(candidate),
              'build_note': 'Use the locked MSYS2 toolchain and nlohmann-json dependency; '
                            'pass PSN_JSON_INCLUDE_DIR if CMake cannot find its package.'}
    try:
        destination.mkdir(parents=True, exist_ok=True)
        git(repo, 'worktree', 'add', '-b', branch, candidate, new_revision)
        if commits:
            # Git >= 2.45 drops adopted changes and retains the sequencer on conflict.
            picked = git(candidate, 'cherry-pick', '--empty=drop', *commits, check=False)
            if picked.returncode:
                conflicts = value(candidate, 'diff', '--name-only', '--diff-filter=U').splitlines()
                result.update(status='conflict' if conflicts else 'failed', conflicts=conflicts,
                              candidate_revision=commit(candidate, 'HEAD'),
                              diagnostic=(picked.stderr or picked.stdout).strip(),
                              resume_command=['git', '-C', str(candidate), 'cherry-pick', '--continue'],
                              abort_command=['git', '-C', str(candidate), 'cherry-pick', '--abort'])
                result['next_commands'] = []
                return result
        candidate_revision = commit(candidate, 'HEAD')
        tree = value(candidate, 'rev-parse', candidate_revision + ':platform/psn')
        result.update(status='prepared', candidate_revision=candidate_revision, psn_tree=revision(tree),
                      psn_tree_changed=tree != pin['psn_tree'])
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        # Retain and identify even a partially created worktree; never clean it destructively.
        result.update(status='failed', diagnostic=str(error), next_commands=[])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', required=True)
    parser.add_argument('--channel', required=True, choices=('channel-a', 'channel-b'))
    parser.add_argument('--host-source')
    parser.add_argument('--upstream-tag')
    parser.add_argument('--upstream-revision')
    parser.add_argument('--check-latest', action='store_true', help='Read official release metadata only')
    args = parser.parse_args()
    if not args.check_latest and not all((args.host_source, args.upstream_tag, args.upstream_revision)):
        parser.error('Preparing an update requires --host-source, --upstream-tag and --upstream-revision')
    try:
        result = latest(args.lock, args.channel) if args.check_latest else prepare(args)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({'schema_version': 1, 'status': 'failed', 'error': str(error)}))
        return 1
    print(json.dumps(result, indent=2))
    return 2 if result['status'] == 'conflict' else 1 if result['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
