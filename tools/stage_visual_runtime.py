#!/usr/bin/env python3
"""Keep only runnable game assets for repeated cloud screenshot sessions."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

manifest, target = map(Path, sys.argv[1:])
data = json.loads(manifest.read_text())
target.mkdir(parents=True, exist_ok=True)

def stage(src, name):
    src, dst = Path(src), target / name
    if src.is_dir():
        shutil.copytree(src, dst, copy_function=os.link)
    else:
        os.link(src, dst)
    return name

data['host'] = stage(data['host'], 'dmhost')
data['patched'] = stage(data['patched'], 'patched')
env = data['env']
env['DM_ROMFS'] = stage(env['DM_ROMFS'], 'romfs')
env['DM_FONT_DIR'] = stage(env['DM_FONT_DIR'], 'font')
profile = Path(env['DM_NVN_SHMAP']).parent
stage(profile, 'profile')
env['DM_NVN_SHMAP'] = 'profile/shader_map.tsv'
(target / 'shaders').mkdir()
for chain in Path(env['DM_MSL_DIR']).glob('b-*'):
    stage(chain, 'shaders/' + chain.name)
env['DM_MSL_DIR'] = 'shaders'
env['DM_ROOT'] = '.'
env['DM_SAVE'] = 'run/save'
env['DM_TEMP'] = 'run/temp'
data['cwd'] = 'run'
data['patch_sha256'] = {
    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
    for p in (manifest.parents[2] / 'build-config/patches').glob('legacy-*.patch')
}
(target / 'runtime.json').write_text(json.dumps(data, indent=2) + '\n')
print('Staged actual game runtime without keys or input packages')
