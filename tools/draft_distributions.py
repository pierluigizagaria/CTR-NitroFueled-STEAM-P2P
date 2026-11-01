"""Validate both full distributions and their source companions before drafting."""
import argparse
import json
from pathlib import Path

from distribution_validation import validate
from release_support import output, revision, run, version


ROOT = Path(__file__).resolve().parents[1]


def validate_draft(directory, tag, commit, repository=ROOT):
    from automation_publish import public_assets
    repository = Path(repository)
    lock = json.loads((repository / 'distribution-lock.json').read_text(encoding='utf-8'))
    release_lock = json.loads((repository / 'release-lock.json').read_text(encoding='utf-8'))
    plan = {'new_lock': lock, 'version': tag, 'candidate_revision': commit}
    return public_assets(directory, plan, release_lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, type=version)
    parser.add_argument('--revision', required=True, type=revision)
    parser.add_argument('--dist', default='dist')
    args = parser.parse_args()
    assets = validate_draft(args.dist, args.version, args.revision)
    releases = json.loads(output('gh', 'api', '--paginate', '--slurp', 'repos/{owner}/{repo}/releases'))
    if any(release['tag_name'] == args.version for page in releases for release in page):
        raise ValueError('Release already exists; use the automatic publisher to replace its current pair')
    refs = json.loads(output('gh', 'api', 'repos/{owner}/{repo}/git/matching-refs/tags/' + args.version))
    if any(ref['ref'] == 'refs/tags/' + args.version for ref in refs):
        raise ValueError('Tag already exists; this draft helper never retargets existing tags')
    body = Path(args.dist) / 'complete-release-notes.md'
    body.write_text('Experimental complete Windows x64 P2P distributions.\n\n'
                    + '\n'.join('- ' + asset.name for asset in assets)
                    + '\n\nEach ZIP includes the port, Steam P2P mod, corresponding sources, licenses and '
                    'build provenance. Game files are not included.\n', encoding='utf-8')
    run('gh', 'release', 'create', args.version, *assets, '--target', args.revision, '--draft', '--prerelease',
        '--latest=false', '--title', args.version + ' complete P2P previews', '--notes-file', body)


if __name__ == '__main__':
    main()
