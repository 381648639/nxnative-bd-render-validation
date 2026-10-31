"""Verify the new package's identity and bundled audio policy without extraction."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import zipfile


def verify(ipa, patches, revision):
    with zipfile.ZipFile(ipa) as z:
        info = plistlib.loads(z.read("Payload/DmIOS.app/Info.plist"))
        if info["CFBundleIdentifier"] != "org.nxnative.0100000011d90000":
            raise ValueError("Unexpected bundle identifier")
        if info["CFBundleShortVersionString"] != "1.3.0":
            raise ValueError("Unexpected game version")
        if info["MinimumOSVersion"] != "16.1":
            raise ValueError("The iOS 16.1 deployment target changed")
        policy = z.read("Payload/DmIOS.app/dm/env.txt").decode("utf-8")
        values = dict(line.split("=", 1) for line in policy.splitlines() if line and not line.startswith("#"))
        if values.get("DM_AUDIO_SESSION_CATEGORY") != "playback_mix":
            raise ValueError("Playback/MixWithOthers audio policy was not packaged")
        if any(k.startswith(("DM_NVN_PASSDUMP", "DM_NVN_SHDUMP")) for k in values):
            raise ValueError("Temporary rendering diagnostics must not be bundled")
        skinning = [n for n in z.namelist() if n.endswith("/2c1e06378edbd813_b.metallib")]
        if len(skinning) != 1:
            raise ValueError("The required Unity skinning kernel is missing or duplicated")
        result = {
            "revision": revision,
            "upstream_sha": os.environ["UPSTREAM_SHA"],
            "build_config_sha": os.environ["GITHUB_SHA"],
            "patch_sha256": hashlib.sha256(Path(patches[0]).read_bytes()).hexdigest(),
            "patches_sha256": {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in patches},
            "bundle_id": info["CFBundleIdentifier"],
            "game_version": info["CFBundleShortVersionString"],
            "minimum_ios": info["MinimumOSVersion"],
            "audio_session_category": values["DM_AUDIO_SESSION_CATEGORY"],
            "skinning_kernel": skinning[0],
            "ipa_size": Path(ipa).stat().st_size,
            "device_gameplay_verified": False,
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="r3")
    parser.add_argument("ipa")
    parser.add_argument("patches", nargs="+")
    args = parser.parse_args()
    print(json.dumps(verify(args.ipa, args.patches, args.revision), indent=2))
