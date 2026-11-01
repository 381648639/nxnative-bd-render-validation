"""Verify the new package's identity and bundled audio policy without extraction."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
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
        chain = None
        visual = None
        if revision in ('r4', 'r5'):
            chain = os.environ['EXPECTED_CHAIN']
            buckets = {re.search(r'/b-([0-9a-f]+)/', n).group(1) for n in z.namelist()
                       if n.endswith('.metallib') and re.search(r'/b-([0-9a-f]+)/', n)}
            if buckets != {chain}:
                raise ValueError('The IPA contains stale or mixed translation chains')
            source = z.read('Payload/DmIOS.app/msl/b-' + chain + '/nonpoint-v1/b8b1925cc16f8247_b.metal').decode()
            if 'dm_nonfinite_1' not in source or '!isfinite(out.m_31)' not in source:
                raise ValueError('The television vertex shader lacks the non-finite bridge')
            visual = json.loads(Path('visual-evidence/verdict.json').read_text())
            if visual['verdict'] != 'pass' or visual['run_id'] != os.environ['GITHUB_RUN_ID']:
                raise ValueError('This exact production build has no passing Mac visual verdict')
        if revision == 'r5':
            launcher = json.loads(z.read('Payload/DmIOS.app/dm/launcher.json'))
            target = next(s for s in launcher['settings'] if s['env'] == 'DM_FPS_TARGET')
            if target['default'] != '30':
                raise ValueError('The new package must default to 30 fps')
            marker = b'presentation target 30 fps: at least two 60 Hz vsyncs per frame'
            if marker not in z.read('Payload/DmIOS.app/DmIOS'):
                raise ValueError('The rebuilt executable does not contain the presentation cap')
            if 'DM_FPS_TARGET' in values or 'DM_PRESENT_INTERVAL' in values:
                raise ValueError('The cap must be compiled in, not supplied by a bundled env override')
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
            "shader_chain": chain,
            "mac_gameplay_verdict": visual,
            "default_fps": '30' if revision == 'r5' else None,
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="r3")
    parser.add_argument("ipa")
    parser.add_argument("patches", nargs="+")
    args = parser.parse_args()
    print(json.dumps(verify(args.ipa, args.patches, args.revision), indent=2))
