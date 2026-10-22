"""Check official releases and replay tracked recipes entirely inside the P2P repository.

The lock and existing checkouts are preserved. A conflict retains its candidate
for review; build, tests and publication are separate operations.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request
import uuid

from distribution_support import CHANNELS, locked_channel
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
    """Apply a tracked P2P recipe to an official upstream release locally."""
    from host_integration import materialize
    _, pin = locked_channel(args.lock, args.channel)
    repository = Path(args.repository).resolve()
    target = dict(pin['upstream'], tag=args.upstream_tag,
                  revision=revision(args.upstream_revision))
    destination = getattr(args, 'destination', None)
    if not destination:
        destination = repository / 'out/integrations' / (args.channel + '-' + uuid.uuid4().hex[:10])
    common = {'schema_version': 1, 'channel': args.channel, 'upstream': target,
              'upstream_tag': target['tag'], 'upstream_revision': target['revision'],
              'upstream_repository': target['repository'], 'lock_modified': False,
              'previous_integration_revision': pin['revision'],
              'previous_upstream_revision': pin['upstream']['revision']}
    try:
        result = materialize(repository, pin, destination,
                             source_cache=getattr(args, 'source_cache', None), upstream=target,
                             verify_pin=target == pin['upstream'])
        result.update(common, next_commands=build_commands(Path(result['host_source'])))
        return result
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        result = getattr(error, 'candidate', {'status': 'failed'})
        result.update(common, diagnostic=str(error), next_commands=[])
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', required=True)
    parser.add_argument('--channel', required=True, choices=CHANNELS)
    parser.add_argument('--repository', default='.')
    parser.add_argument('--destination')
    parser.add_argument('--source-cache')
    parser.add_argument('--upstream-tag')
    parser.add_argument('--upstream-revision')
    parser.add_argument('--check-latest', action='store_true', help='Read official release metadata only')
    args = parser.parse_args()
    if not args.check_latest and not all((args.upstream_tag, args.upstream_revision)):
        parser.error('Preparing an update requires --upstream-tag and --upstream-revision')
    try:
        result = latest(args.lock, args.channel) if args.check_latest else prepare(args)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({'schema_version': 1, 'status': 'failed', 'error': str(error)}))
        return 1
    print(json.dumps(result, indent=2))
    return 2 if result['status'] == 'conflict' else 1 if result['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
