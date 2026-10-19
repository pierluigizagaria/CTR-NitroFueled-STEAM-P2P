# Expat source dependency

The bridge statically builds the XML parser from **Expat 2.9.0**, upstream release
tag `R_2_9_0`, downloaded from the official project:

- Release: https://github.com/libexpat/libexpat/releases/tag/R_2_9_0
- Source archive: https://github.com/libexpat/libexpat/releases/download/R_2_9_0/expat-2.9.0.tar.xz
- Archive SHA-256: `1e6371862cc31999b368c3b89b49994f0677e1bab5f1b2b85ae3741f5d803051`
- Retrieved: 2026-10-19.

`upstream/` contains unmodified source files from that archive: `lib/*.c`,
`lib/*.h`, the upstream CMake configuration and its required templates, the
change log, author list and `COPYING`. The parser uses the MIT license in
`upstream/COPYING`; upstream CMake retains its separate build-system license
notice. No host, provider, publisher or shadPS4 implementation is included.

The local wrapper builds only a static UTF-8 library with namespace support.
It disables parameter-entity support, tools, examples, tests, documentation,
package installation and download targets. The bridge rejects every DTD at its
opening declaration and registers no external-entity resolver. Ordinary XML
character references remain available. The upstream build detects platform
entropy APIs without adding a bridge dependency on operating-system XML APIs.
macOS runtime acceptance is not claimed.

No network access or system installation is needed to build this vendored source.
To update it, retrieve an official source release, record its version and archive
hash, replace this subset without editing upstream files, and rerun the bridge's
malformed-document and inactive-write regression tests.
