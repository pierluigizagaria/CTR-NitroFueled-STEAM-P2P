#!/usr/bin/env python3
"""Assemble a Windows mod from explicit, independently built component artifacts."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile
from release_support import component, write_zip


def digest(data):
    return hashlib.sha256(data).hexdigest()


def steam_runtime(sdk_archive, expected_sha256):
    entry = "sdk/redistributable_bin/win64/steam_api64.dll"
    with zipfile.ZipFile(sdk_archive) as archive:
        if archive.namelist().count(entry) != 1:
            raise ValueError("Steamworks SDK: expected one Windows x64 redistributable")
        runtime = archive.read(entry)
    if digest(runtime) != expected_sha256:
        raise ValueError("Steamworks SDK: runtime hash does not match the verified release input")
    return runtime


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
    runtime_input = parser.add_mutually_exclusive_group(required=True)
    runtime_input.add_argument("--steam-sdk-archive", type=Path)
    runtime_input.add_argument("--steam-runtime-file", type=Path)
    parser.add_argument("--release-lock", type=Path)
    parser.add_argument("--build-info", type=Path)
    parser.add_argument("--steam-sdk-version", required=True)
    parser.add_argument("--steam-runtime-sha256", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for revision in (args.bridge_revision, args.patch_revision):
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            parser.error("source revisions must be full Git commit IDs")
    if not re.fullmatch(r"[0-9a-f]{64}", args.steam_runtime_sha256):
        parser.error("Steam runtime hash must be a lowercase SHA-256 digest")
    root = Path(__file__).resolve().parents[1]
    provider, provider_files = component(args.provider_package, "orbisteamworks")
    server, server_files = component(args.server_package, "demonware-server")
    lock = json.loads(args.release_lock.read_text()) if args.release_lock else None
    if lock:
        component(args.provider_package, "orbisteamworks", lock["components"]["orbisteamworks"])
        component(args.server_package, "demonware-server", lock["components"]["demonware-server"])
        for path, pin in ((args.provider_package, lock["components"]["orbisteamworks"]),
                          (args.server_package, lock["components"]["demonware-server"])):
            if digest(path.read_bytes()) != pin["sha256"]:
                raise ValueError("Component archive differs from release lock")
        patch = lock["components"]["signature-patch"]
        if (args.patch_revision != patch["revision"] or digest(args.patch_xml.read_bytes()) != patch["xml_sha256"]
                or digest(args.patch_license.read_bytes()) != patch["license_sha256"]):
            raise ValueError("Signature patch differs from release lock")
        if (args.steam_sdk_version != lock["steam_runtime"]["sdk_version"]
                or args.steam_runtime_sha256 != lock["steam_runtime"]["sha256"]):
            raise ValueError("Steam runtime differs from release lock")
    files = {
        name: (args.bridge_build / name).read_bytes()
        for name in ("ctrnf-p2p.exe", "ctrnf-p2p-cli.exe")
    }
    files["orbisteamworks.dll"] = provider_files["orbisteamworks.dll"]
    files["demonware-server.exe"] = server_files["demonware-server.exe"]
    runtime = (args.steam_runtime_file.read_bytes() if args.steam_runtime_file else
               steam_runtime(args.steam_sdk_archive, args.steam_runtime_sha256))
    if digest(runtime) != args.steam_runtime_sha256:
        raise ValueError("Steam runtime hash mismatch")
    files["steam_api64.dll"] = runtime
    if args.release_lock:
        files["ctrnf-p2p-release-lock.json"] = args.release_lock.read_bytes()
    if args.build_info:
        files["ctrnf-p2p-build-info.json"] = args.build_info.read_bytes()
    files["ctrnf-p2p.ini"] = (root / "ctrnf-p2p.example.ini").read_bytes()
    files["patches/CrashTeamRacingNitroFueled.xml"] = args.patch_xml.read_bytes()
    files["licenses/ctrnf-p2p/LICENSE"] = (root / "LICENSE").read_bytes()
    files["licenses/ctrnf-p2p/expat.txt"] = (root / "third_party/expat/upstream/COPYING").read_bytes()
    files["licenses/ctrnf-p2p/nlohmann-json.txt"] = args.json_license.read_bytes()
    files["licenses/signature-patch/LICENSE"] = args.patch_license.read_bytes()
    files["licenses/steamworks/NOTICE.txt"] = (root / "third_party/steamworks/NOTICE.txt").read_bytes()
    for name, payload in (("orbisteamworks", provider_files), ("demonware-server", server_files)):
        files[f"licenses/{name}/LICENSE"] = payload["LICENSE"]
        for entry, data in payload.items():
            if entry.startswith("licenses/"):
                files[f"licenses/{name}/third-party/{entry[len('licenses/'):]}"] = data
    for name in ("INSTALLATION.md", "CONFIGURATION.md"):
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
            "steamworks-runtime": {
                "sdk_version": args.steam_sdk_version,
                "license": "Valve Steamworks SDK Access Agreement",
                "license_url": "https://partner.steamgames.com/documentation/sdk_access_agreement",
                "sdk_path": "sdk/redistributable_bin/win64/steam_api64.dll",
                "sha256": args.steam_runtime_sha256,
            },
        },
        "files": {name: digest(data) for name, data in sorted(files.items())},
    }
    if lock:
        manifest["host"] = lock["host"]
    if args.build_info:
        manifest["build"] = json.loads(args.build_info.read_text())
    files["ctrnf-p2p-manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    files["ctrnf-p2p-SHA256SUMS.txt"] = "".join(
        f"{digest(data)}  {name}\n" for name, data in sorted(files.items())
    ).encode()
    write_zip(args.output, files)
    print(f"{args.output.name}: {len(files)} files; SHA-256 {digest(args.output.read_bytes())}")


if __name__ == "__main__":
    main()
