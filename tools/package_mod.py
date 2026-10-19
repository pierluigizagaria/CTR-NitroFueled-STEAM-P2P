#!/usr/bin/env python3
"""Assemble a Windows mod from explicit, independently built component artifacts."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def component(path, expected):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f"{expected}: duplicate archive entries")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest["component"] != expected:
            raise ValueError(f"expected {expected} package")
        payload = {}
        for name, sha in manifest["files"].items():
            parts = PurePosixPath(name)
            if parts.is_absolute() or ".." in parts.parts or "\\" in name:
                raise ValueError(f"{expected}: unsafe path")
            data = archive.read(name)
            if digest(data) != sha:
                raise ValueError(f"{expected}: hash mismatch for {name}")
            payload[name] = data
        if "LICENSE" not in payload or not any(n.startswith("licenses/") for n in payload):
            raise ValueError(f"{expected}: license notices missing")
        return manifest, payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-build", type=Path, required=True)
    parser.add_argument("--bridge-revision", required=True)
    parser.add_argument("--provider-package", type=Path, required=True)
    parser.add_argument("--server-package", type=Path, required=True)
    parser.add_argument("--patch-xml", type=Path, required=True)
    parser.add_argument("--patch-license", type=Path, required=True)
    parser.add_argument("--patch-revision", required=True)
    parser.add_argument("--json-license", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for revision in (args.bridge_revision, args.patch_revision):
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            parser.error("source revisions must be full Git commit IDs")
    root = Path(__file__).resolve().parents[1]
    provider, provider_files = component(args.provider_package, "orbisteamworks")
    server, server_files = component(args.server_package, "demonware-server")
    files = {
        name: (args.bridge_build / name).read_bytes()
        for name in ("ctrnf-p2p.exe", "ctrnf-p2p-cli.exe")
    }
    files["orbisteamworks.dll"] = provider_files["orbisteamworks.dll"]
    files["demonware-server.exe"] = server_files["demonware-server.exe"]
    files["ctrnf-p2p.example.ini"] = (root / "ctrnf-p2p.example.ini").read_bytes()
    files["patches/CrashTeamRacingNitroFueled.xml"] = args.patch_xml.read_bytes()
    files["licenses/ctrnf-p2p/LICENSE"] = (root / "LICENSE").read_bytes()
    files["licenses/ctrnf-p2p/expat.txt"] = (root / "third_party/expat/upstream/COPYING").read_bytes()
    files["licenses/ctrnf-p2p/nlohmann-json.txt"] = args.json_license.read_bytes()
    files["licenses/signature-patch/LICENSE"] = args.patch_license.read_bytes()
    for name, payload in (("orbisteamworks", provider_files), ("demonware-server", server_files)):
        files[f"licenses/{name}/LICENSE"] = payload["LICENSE"]
        for entry, data in payload.items():
            if entry.startswith("licenses/"):
                files[f"licenses/{name}/third-party/{entry[len('licenses/'):]}"] = data
    for name in ("INSTALLATION.md", "CONFIGURATION.md", "ARCHITECTURE.md", "TWO_PC.md", "PACKAGE_README.md", "VALIDATION.md"):
        files[f"ctrnf-p2p-docs/{name}"] = (root / "docs" / name).read_bytes()
    files["CTR-P2P-README.md"] = (root / "docs/PACKAGE_README.md").read_bytes()
    manifest = {
        "component": "ctrnf-p2p-mod",
        "version": args.version,
        "platform": "windows-x64",
        "components": {
            "ctrnf-p2p": {"revision": args.bridge_revision, "license": "MIT"},
            "orbisteamworks": {k: provider[k] for k in ("revision", "version", "license")},
            "demonware-server": {k: server[k] for k in ("revision", "version", "license")},
            "signature-patch": {"revision": args.patch_revision, "license": "MIT"},
        },
        "files": {name: digest(data) for name, data in sorted(files.items())},
    }
    files["ctrnf-p2p-manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    files["ctrnf-p2p-SHA256SUMS.txt"] = "".join(
        f"{digest(data)}  {name}\n" for name, data in sorted(files.items())
    ).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Refuse to replace an existing artifact; releases should be immutable.
    with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    print(f"{args.output.name}: {len(files)} files; SHA-256 {digest(args.output.read_bytes())}")


if __name__ == "__main__":
    main()
