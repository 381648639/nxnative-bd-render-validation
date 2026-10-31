#!/usr/bin/env python3
"""Reuse unchanged real game assets while rebuilding only the patched host."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

repo, config, runtime, variant = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
assert variant in ('r2', 'r3')
if variant == 'r2':
    for name in ('legacy-prediction.patch', 'legacy-diagnostics.patch'):
        subprocess.run(['git', '-C', str(repo), 'apply', '-R', str((config / 'patches' / name).resolve())], check=True)
flags = '-O1 -g -Wall -Wno-unused-function -DDM_NVN_LEGACY_RENDERER_TEST=1'
cmd = ['make', '-C', str(repo / 'dm/host'), 'GAME=0100000011D90000', 'CFLAGS=' + flags, 'dmhost']
print('Building development host:', ' '.join(cmd), flush=True)
subprocess.run(cmd, check=True)
shutil.copyfile(repo / 'dm/host/dmhost', runtime / 'dmhost')
(runtime / 'dmhost').chmod(0o755)
data = json.loads((runtime / 'runtime.json').read_text())
data['variant'] = variant
names = ['legacy-renderer.patch'] + (['legacy-diagnostics.patch', 'legacy-prediction.patch'] if variant == 'r3' else [])
data['patch_sha256'] = {name: hashlib.sha256((config / 'patches' / name).read_bytes()).hexdigest() for name in names}
data['host_compile_command'] = cmd
(runtime / 'runtime.json').write_text(json.dumps(data, indent=2) + '\n')
