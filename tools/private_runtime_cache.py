"""Reuse real game runtime through private release assets, never public caches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['restore', 'save'])
args = parser.parse_args()
repo = os.environ['BD_ASSET_REPOSITORY']
assert repo != os.environ['GITHUB_REPOSITORY']
tag = 'bd-visual-runtime-mac-legacy-v1'
root = Path('game-runtime')
scratch = Path('private-runtime-transfer')
scratch.mkdir(exist_ok=True)

def gh(*argv, check=True):
    return subprocess.run(['gh', *argv, '--repo', repo], capture_output=True, check=check, timeout=900)

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def output(value):
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write('found=' + value + '\n')

manifest = scratch / 'runtime-manifest.json'
if args.mode == 'restore':
    result = gh('release', 'download', tag, '--pattern', manifest.name, '--dir', str(scratch), '--clobber', check=False)
    if result.returncode:
        print('No private reusable game runtime yet', flush=True)
        output('false')
        raise SystemExit(0)
    data = json.loads(manifest.read_text())
    assert data['upstream'] == '1942eaa5e2a767809868994c27dfc5d692439fdc'
    assert data['chain'] == 'ea90ed511690'
    gh('release', 'download', tag, '--pattern', 'runtime.part-*', '--dir', str(scratch), '--clobber')
    archive = scratch / 'runtime.tar.zst'
    with archive.open('wb') as destination:
        for item in data['parts']:
            assert re.fullmatch(r'runtime\.part-[0-9]{2}', item['name'])
            part = scratch / item['name']
            assert part.stat().st_size == item['size'] and sha(part) == item['sha256']
            with part.open('rb') as source:
                shutil.copyfileobj(source, destination, 1024 * 1024)
    assert sha(archive) == data['archive_sha256']
    decompressor = subprocess.Popen(['zstd', '-dc', str(archive)], stdout=subprocess.PIPE)
    with tarfile.open(fileobj=decompressor.stdout, mode='r|') as tar:
        for member in tar:
            path = Path(member.name)
            assert not path.is_absolute() and path.parts[0] == 'game-runtime' and '..' not in path.parts
            tar.extract(member, filter='data')
    assert decompressor.wait() == 0
    output('true')
    print('Restored hash-verified runtime from the private repository', flush=True)
else:
    assert (root / 'runtime.json').is_file()
    assert not any(p.suffix.lower() in ('.keys', '.nsp', '.xci', '.ipa') for p in root.rglob('*') if p.is_file())
    archive = scratch / 'runtime.tar.zst'
    pack = subprocess.Popen(['tar', '-cf', '-', 'game-runtime'], stdout=subprocess.PIPE)
    with archive.open('wb') as destination:
        compressor = subprocess.run(['zstd', '-T0', '-3', '-c'], stdin=pack.stdout, stdout=destination, check=True)
    assert pack.wait() == 0
    gh('release', 'create', tag, '--title', 'Private reusable legacy game runtime', '--notes',
       'Private runnable game assets for visual inspection. No keys or public artifacts.', '--prerelease', check=False)
    parts = []
    with archive.open('rb') as source:
        index = 0
        while True:
            first = source.read(1024 * 1024)
            if not first:
                break
            part = scratch / f'runtime.part-{index:02d}'
            with part.open('wb') as destination:
                destination.write(first)
                remaining = 1536 * 1024 * 1024 - len(first)
                while remaining:
                    chunk = source.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        break
                    destination.write(chunk)
                    remaining -= len(chunk)
            parts.append({'name': part.name, 'size': part.stat().st_size, 'sha256': sha(part)})
            gh('release', 'upload', tag, str(part), '--clobber')
            print('Uploaded private runtime part', index, flush=True)
            index += 1
    data = {'upstream': '1942eaa5e2a767809868994c27dfc5d692439fdc', 'chain': 'ea90ed511690',
            'archive_sha256': sha(archive), 'parts': parts}
    manifest.write_text(json.dumps(data, indent=2) + '\n')
    gh('release', 'upload', tag, str(manifest), '--clobber')
    print('Reusable game runtime saved privately', flush=True)
