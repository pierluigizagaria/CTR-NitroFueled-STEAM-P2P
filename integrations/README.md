# Host integration recipes

These integrations belong to their respective GPL-licensed host projects. They
are separate from the MIT bridge implementation and are not compiled into it.

* `GetLostIn/CTR-NitroFueled-PC` derives from
  <https://github.com/GetLostIn/CTR-NitroFueled-PC>.
* `Ryu7w7/OCTR-NitroFueled-PC` derives from
  <https://github.com/Ryu7w7/OCTR-NitroFueled-PC>.

Each directory retains the upstream GPL license. Original human authors,
commit dates, messages and revision identifiers are retained in `recipe.json`.
The integration patches were authored by Pierluigi Zagaria. The GetLostIn mutex
layout change credits Ryu7w7's original implementation in its commit message.
All pre-existing upstream copyright and license notices remain in the rebuilt
host and its complete corresponding source package.

The recipe starts at an official upstream release tag. Patches are checked by
SHA-256 before application, and the resulting Git commit, source tree and shared
PSN adapter tree are checked against `distribution-lock.json`. Deleted optional
artwork and original game shaders are represented only by their path and Git
blob identifier: their contents are never embedded in a patch. Neither game
files nor Steamworks binaries belong in this directory.

`tools/host_integration.py` reproduces the existing integrations exactly and can
apply the same series to a newer upstream release. Conflicts, changed deletion
targets, unexpected adapter changes and mismatched hashes stop the update for
review. The generated host checkout stays in the P2P repository's ignored `out/`
directory. Historical integration branches remain available as provenance but
are not an input to the build or release pipeline.

For a local reproduction, run:

```console
python tools/host_integration.py --channel getlostin-ctr-nitrofueled-pc --destination out/integrations/getlostin
python tools/host_integration.py --channel ryu7w7-octr-nitrofueled-pc --destination out/integrations/ryu7w7
```

The optional `--source-cache` argument reads an existing local Git repository
containing the exact official tag. It does not modify that repository. Runtime
builds, tests, source export and release publication remain separate validated
steps after source reproduction.
