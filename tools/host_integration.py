"""Reproduce separately licensed host integrations from upstream and tracked recipes.

Only upstream Git objects and hash-checked patches are consumed. Host integration
branches and credentials for another repository are deliberately unnecessary.
"""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from distribution_support import json_bytes, sha256, windows_name
from release_support import revision


def git(repo, *args, data=None, check=True):
    result = subprocess.run(['git', '-c', 'core.longpaths=true', '-c', 'core.autocrlf=false',
                             '-c', 'core.hooksPath=', '-C', str(repo), *map(str, args)],
                            input=data, capture_output=True)
    if check and result.returncode:
        raise ValueError(result.stderr.decode('utf-8', errors='replace').strip() or 'Git command failed')
    return result


def value(repo, *args):
    return git(repo, *args).stdout.decode('utf-8').strip()


def recipe_file(root, relative):
    windows_name(relative)
    path = Path(root) / relative
    if not path.resolve().is_relative_to(Path(root).resolve()) or path.is_symlink():
        raise ValueError('Recipe path escapes its repository')
    return path


def load_recipe(repository, pin):
    path = recipe_file(repository, pin['recipe']['path'])
    raw = path.read_bytes()
    if sha256(raw) != pin['recipe']['sha256']:
        raise ValueError('Integration recipe checksum mismatch')
    recipe = json.loads(raw)
    if recipe.get('schema_version') != 1 or recipe['upstream_repository'] != pin['upstream']['repository']:
        raise ValueError('Integration recipe is not for the locked upstream')
    revision(recipe['original_upstream_revision'])
    revision(recipe['original_integration_revision'])
    if not recipe['commits']:
        raise ValueError('Integration recipe contains no commits')
    seen = set()
    for entry in recipe['commits']:
        revision(entry['original_revision'])
        revision(entry['original_tree'])
        # Preserve Git identity/date headers verbatim, while rejecting extra headers.
        for field in ('author', 'committer'):
            if not re.fullmatch(r'[^\r\n<>]+ <[^\r\n<>]+> [0-9]+ [+-][0-9]{4}', entry[field]):
                raise ValueError('Malformed original commit identity/date')
        if not isinstance(entry['message'], str) or '\0' in entry['message']:
            raise ValueError('Malformed original commit message')
        patch = recipe_file(path.parent, entry['patch'])
        if patch in seen:
            raise ValueError('Repeated integration patch')
        seen.add(patch)
        data = patch.read_bytes()
        if sha256(data) != entry['sha256']:
            raise ValueError('Integration patch checksum mismatch: ' + entry['patch'])
        if b'GIT binary patch' in data or b'\0' in data:
            raise ValueError('Binary content is forbidden in integration patches')
        for deletion in entry['deletions']:
            windows_name(deletion['path'])
            revision(deletion['blob'])
            if deletion['mode'] not in ('100644', '100755'):
                raise ValueError('Only regular upstream files may be removed')
    return path, recipe


def current_result(destination, status):
    return {'schema_version': 1, 'status': status, 'host_source': str(destination),
            'candidate_worktree': str(destination),
            'candidate_revision': revision(value(destination, 'rev-parse', 'HEAD')),
            'source_tree': revision(value(destination, 'rev-parse', 'HEAD^{tree}')),
            'psn_tree': revision(value(destination, 'rev-parse', 'HEAD:platform/psn')),
            'clean_source': not bool(value(destination, 'status', '--porcelain'))}


def verify_result(result, pin, verify_pin):
    if not result['clean_source']:
        raise ValueError('Materialized integration is not clean')
    if result['psn_tree'] != pin['psn_tree']:
        raise ValueError('Integration changed the shared PSN tree; manual review is required')
    if verify_pin and any(result[key] != pin[field] for key, field in
                          (('candidate_revision', 'revision'), ('source_tree', 'source_tree'))):
        raise ValueError('Materialized integration differs from the locked revision/tree')


def materialize(repository, pin, destination, source_cache=None, upstream=None, verify_pin=True):
    """Fetch one upstream tag and apply its checked recipe in a new local checkout.

    A local source_cache is an optional offline source of the exact upstream tag;
    it is never modified. Failures retain the destination for diagnosis. No refs
    are pushed and no original host checkout or branch is changed.
    """
    repository, destination = Path(repository).resolve(), Path(destination).resolve()
    recipe_path, recipe = load_recipe(repository, pin)
    target = dict(upstream or pin['upstream'])
    if target['repository'] != pin['upstream']['repository']:
        raise ValueError('Cannot change the official upstream repository')
    revision(target['revision'])
    if git(repository, 'check-ref-format', 'refs/tags/' + target['tag'], check=False).returncode:
        raise ValueError('Invalid upstream tag name')
    if destination == repository or not destination.is_relative_to(repository / 'out'):
        raise ValueError('Materialization destination must be inside the P2P repository out directory')
    receipt_path = destination / '.git' / 'p2p-recipe.json'
    inputs = {'recipe_sha256': pin['recipe']['sha256'], 'upstream': target}
    if destination.exists() and any(destination.iterdir()):
        if not receipt_path.is_file():
            raise ValueError('Existing destination is not the same completed integration')
        receipt = json.loads(receipt_path.read_bytes())
        if receipt.get('inputs') != inputs:
            raise ValueError('Existing destination is not the same completed integration')
        result = current_result(destination, 'unchanged')
        if any(result[key] != receipt.get(key) for key in ('candidate_revision', 'source_tree', 'psn_tree')):
            raise ValueError('Existing destination differs from its completed integration receipt')
        verify_result(result, pin, verify_pin)
        return result
    destination.mkdir(parents=True, exist_ok=True)
    try:
        git(destination, 'init', '-q')
        git(destination, 'config', 'core.autocrlf', 'false')
        git(destination, 'config', 'core.longpaths', 'true')
        git(destination, 'remote', 'add', 'origin', target['repository'])
        source = str(Path(source_cache).resolve()) if source_cache else target['repository']
        git(destination, 'fetch', '--no-tags', '--no-write-fetch-head', '--no-recurse-submodules',
            '--no-auto-maintenance', source, 'refs/tags/' + target['tag'] + ':refs/p2p/upstream')
        fetched = revision(value(destination, 'rev-parse', 'refs/p2p/upstream^{commit}'))
        if fetched != target['revision']:
            raise ValueError('The fetched official upstream tag differs from its locked revision')
        # A rewrite or older release must never silently replace the current base.
        original = recipe['original_upstream_revision']
        if git(destination, 'merge-base', '--is-ancestor', original, fetched, check=False).returncode:
            raise ValueError('The requested upstream rewrites or predates the original recipe base')
        if git(destination, 'merge-base', '--is-ancestor', pin['upstream']['revision'], fetched,
               check=False).returncode:
            raise ValueError('The requested upstream rewrites or predates the currently locked release')
        git(destination, 'checkout', '-q', '--detach', fetched)
        parent = fetched
        for entry in recipe['commits']:
            patch = recipe_file(recipe_path.parent, entry['patch']).read_bytes()
            if patch:
                # No fuzzy/three-way fallback: a conflicting release needs owner review.
                git(destination, 'apply', '--index', '--whitespace=nowarn', '-', data=patch)
            for deletion in entry['deletions']:
                line = value(destination, 'ls-files', '--stage', '--', deletion['path'])
                expected = deletion['mode'] + ' ' + deletion['blob'] + ' 0\t' + deletion['path']
                if line != expected:
                    raise ValueError('Upstream deletion target changed: ' + deletion['path'])
                git(destination, 'rm', '-q', '--', deletion['path'])
            tree = revision(value(destination, 'write-tree'))
            header = ('tree ' + tree + '\nparent ' + parent + '\nauthor ' + entry['author']
                      + '\ncommitter ' + entry['committer'] + '\n\n')
            raw = header.encode('utf-8') + entry['message'].encode('utf-8')
            parent = revision(git(destination, 'hash-object', '-t', 'commit', '-w', '--stdin', data=raw)
                              .stdout.decode().strip())
            if fetched == original and (parent != entry['original_revision'] or tree != entry['original_tree']):
                raise ValueError('Recipe failed to reproduce an original integration commit')
            git(destination, 'update-ref', 'HEAD', parent)
        result = current_result(destination, 'prepared')
        verify_result(result, pin, verify_pin)
        receipt_path.write_bytes(json_bytes(dict(inputs=inputs, **{key: result[key] for key in
                                 ('candidate_revision', 'source_tree', 'psn_tree')})))
        return result
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        error.candidate = {'status': 'conflict' if isinstance(error, ValueError) else 'failed',
                           'candidate_worktree': str(destination), 'host_source': str(destination),
                           'diagnostic': str(error)}
        raise


def export_recipe(source, upstream_revision, integration_revision, destination, upstream_repository):
    """Export a linear existing integration, without embedding removed binary assets."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Recipe export destination must be empty')
    revision(upstream_revision)
    revision(integration_revision)
    commits = value(source, 'rev-list', '--reverse', upstream_revision + '..' + integration_revision).splitlines()
    parent, entries = upstream_revision, []
    destination.mkdir(parents=True, exist_ok=True)
    for index, commit in enumerate(commits, 1):
        raw = git(source, 'cat-file', 'commit', commit).stdout.decode('utf-8')
        headers, message = raw.split('\n\n', 1)
        fields = {}
        for header in headers.splitlines():
            key, item = header.split(' ', 1)
            if key not in ('tree', 'parent', 'author', 'committer') or key in fields:
                raise ValueError('Recipe export needs unsigned linear UTF-8 commits')
            fields[key] = item
        if fields['parent'] != parent:
            raise ValueError('Non-linear integration history needs manual review')
        deleted = git(source, 'diff', '--name-only', '--diff-filter=D', '--no-renames', '-z',
                      parent, commit).stdout.decode('utf-8').split('\0')
        deleted = [path for path in deleted if path]
        deletions = []
        for path in deleted:
            windows_name(path)
            meta = value(source, 'ls-tree', parent, '--', path).split()
            if meta[0] not in ('100644', '100755') or meta[1] != 'blob':
                raise ValueError('Unsupported deletion target')
            deletions.append({'path': path, 'mode': meta[0], 'blob': meta[2]})
        exclusions = [':(exclude)' + path for path in deleted]
        patch = git(source, 'diff', '--binary', '--full-index', '--no-renames', parent, commit,
                    '--', '.', *exclusions).stdout
        if b'GIT binary patch' in patch or b'\0' in patch:
            raise ValueError('A non-deletion binary change requires explicit source review')
        name = f'{index:04d}-{commit[:12]}.patch'
        (destination / name).write_bytes(patch)
        entries.append({'original_revision': commit, 'original_tree': fields['tree'],
                        'author': fields['author'], 'committer': fields['committer'],
                        'message': message, 'patch': name, 'sha256': sha256(patch),
                        'deletions': deletions})
        parent = commit
    result = {'schema_version': 1, 'upstream_repository': upstream_repository,
              'original_upstream_revision': upstream_revision,
              'original_integration_revision': integration_revision, 'commits': entries}
    (destination / 'recipe.json').write_bytes(json_bytes(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default='.')
    parser.add_argument('--lock', default='distribution-lock.json')
    parser.add_argument('--channel', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--source-cache')
    args = parser.parse_args()
    from distribution_support import locked_channel
    _, pin = locked_channel(Path(args.repository) / args.lock, args.channel)
    print(json.dumps(materialize(args.repository, pin, args.destination, args.source_cache), indent=2))


if __name__ == '__main__':
    main()
