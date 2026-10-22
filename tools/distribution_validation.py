"""Validate complete distributions and corresponding source companions."""
from pathlib import Path

from distribution_support import read_zip, sha256, verify_manifest


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
