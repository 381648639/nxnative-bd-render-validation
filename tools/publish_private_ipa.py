"""Publish a split unsigned IPA only to the owner's private build repository."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

repo = os.environ['BD_ASSET_REPOSITORY']
meta = json.loads(subprocess.check_output(['gh', 'api', 'repos/' + repo]))
assert meta['private'], 'IPA storage must remain private'
ipa = next(Path('game-input').glob('*.ipa'))
folder = Path('private-ipa-transfer')
folder.mkdir(exist_ok=True)
tag = 'bd-ios-r3-' + os.environ['GITHUB_RUN_ID']

def gh(*argv):
    subprocess.run(['gh', *argv, '--repo', repo], check=True, timeout=900)

gh('release', 'create', tag, '--title', 'Private Brilliant Diamond iOS 16 r3 build',
   '--notes', 'Unsigned iOS 16.1 package. See provenance and separate gameplay evidence. A completed build is not an iPhone validation.', '--prerelease')
parts, total = [], hashlib.sha256()
with ipa.open('rb') as source:
    index = 0
    while True:
        first = source.read(1024 * 1024)
        if not first:
            break
        part = folder / f'PokemonBrilliantDiamond-r3.ipa.part-{index:02d}'
        digest = hashlib.sha256()
        with part.open('wb') as destination:
            destination.write(first)
            digest.update(first)
            total.update(first)
            remaining = 1536 * 1024 * 1024 - len(first)
            while remaining:
                chunk = source.read(min(remaining, 1024 * 1024))
                if not chunk:
                    break
                destination.write(chunk)
                digest.update(chunk)
                total.update(chunk)
                remaining -= len(chunk)
        parts.append({'name': part.name, 'size': part.stat().st_size, 'sha256': digest.hexdigest()})
        gh('release', 'upload', tag, str(part))
        index += 1
manifest = folder / 'ipa-manifest.json'
manifest.write_text(json.dumps({'title_id': '0100000011D90000', 'version': '1.3.0', 'revision': 'r3',
                                'size': ipa.stat().st_size, 'sha256': total.hexdigest(), 'parts': parts,
                                'source_repository': os.environ['GITHUB_REPOSITORY'],
                                'source_commit': os.environ['GITHUB_SHA'], 'device_gameplay_verified': False}, indent=2) + '\n')
gh('release', 'upload', tag, str(manifest), 'build-provenance-r3.json')
print('Unsigned IPA stored privately in', repo, tag, flush=True)
