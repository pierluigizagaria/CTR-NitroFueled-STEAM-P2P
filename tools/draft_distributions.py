"""Validate both full distributions and their source companions before drafting."""
import argparse
import json
from pathlib import Path

from distribution_support import read_zip, sha256, verify_manifest
from release_support import output, revision, run, version


def validate(directory, tag, commit):
    directory = Path(directory)
    binaries = sorted(directory.glob('*-windows-x64.zip'))
    if len(binaries) != 2:
        raise ValueError('Exactly two channel binary packages are required')
    assets, channels = [], set()
    for binary in binaries:
        files = read_zip(binary)
        manifest = verify_manifest(files, 'p2p-distribution-manifest.json')
        if (manifest.get('component') != 'ctrnf-p2p-distribution' or manifest['version'] != tag
                or manifest['components']['ctrnf-p2p']['revision'] != commit
                or manifest.get('redistribution_ready') is not True
                or manifest.get('build', {}).get('source_dirty') is not False):
            raise ValueError('Distribution source/version/cleanliness evidence is incomplete')
        channels.add(manifest['channel'])
        source_name = manifest['sources']['archive']
        if Path(source_name).name != source_name:
            raise ValueError('Invalid source companion filename')
        source = directory / source_name
        if sha256(source.read_bytes()) != manifest['sources']['sha256']:
            raise ValueError('Corresponding source companion checksum mismatch')
        source_files = read_zip(source)
        source_manifest = verify_manifest(source_files, 'source-manifest.json')
        if (source_manifest['revision'] != manifest['host']['revision']
                or source_manifest.get('host') != manifest['host']
                or source_manifest.get('source_tree') != manifest['host']['source_tree']
                or source_manifest.get('build_recipe', {}).get('revision') != commit
                or source_manifest.get('build_recipe', {}).get('source_dirty') is not False):
            raise ValueError('Corresponding source/build recipe differs from the release')
        for archive in (binary, source):
            checksum = archive.with_suffix('.zip.sha256')
            if checksum.read_text().strip() != sha256(archive.read_bytes()) + '  ' + archive.name:
                raise ValueError('External archive checksum mismatch')
            assets.extend((archive, checksum))
    if channels != {'getlostin-ctr-nitrofueled-pc', 'ryu7w7-octr-nitrofueled-pc'}:
        raise ValueError('Both distinct channels are required')
    return assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, type=version)
    parser.add_argument('--revision', required=True, type=revision)
    parser.add_argument('--dist', default='dist')
    args = parser.parse_args()
    assets = validate(args.dist, args.version, args.revision)
    releases = json.loads(output('gh', 'api', '--paginate', '--slurp', 'repos/{owner}/{repo}/releases'))
    if any(release['tag_name'] == args.version for page in releases for release in page):
        raise ValueError('Release already exists; reviewed additive publication must preserve its original assets')
    refs = json.loads(output('gh', 'api', 'repos/{owner}/{repo}/git/matching-refs/tags/' + args.version))
    if any(ref['ref'] == 'refs/tags/' + args.version for ref in refs):
        raise ValueError('Tag already exists; this draft helper never retargets existing tags')
    body = Path(args.dist) / 'complete-release-notes.md'
    body.write_text('Experimental complete Windows x64 P2P distributions based on '
                    'GetLostIn/CTR-NitroFueled-PC and Ryu7w7/OCTR-NitroFueled-PC.\n\n'
                    'Each archive includes a rebuilt host and mod. Download the matching source companion '
                    'for the exact host, submodules and dependency sources. Game files are not included.\n\n'
                    'Offline build, adapter and package checks passed. Live Steam/multiple-PC game acceptance '
                    'is not established. Keep peers on the same upstream distribution and package version.\n',
                    encoding='utf-8')
    run('gh', 'release', 'create', args.version, *assets, '--target', args.revision, '--draft', '--prerelease',
        '--latest=false', '--title', args.version + ' complete P2P previews', '--notes-file', body)


if __name__ == '__main__':
    main()
