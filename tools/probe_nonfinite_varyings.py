"""Recompile two private captured shaders for a development gameplay control.

This intentionally keeps the production chain untouched and is not an IPA
build path. A passing probe must be implemented and versioned in the real
translation chain, fully rebuilt and checked before it can be packaged.
"""
import json
from pathlib import Path
import subprocess
import sys
from visual_nonfinite_varyings import bridge

runtime = Path(sys.argv[1])
metadata = json.loads((runtime / 'runtime.json').read_text())
assert metadata['variant'] == 'nonfinite-probe'
records = {}
for key, stage in [('b8b1925cc16f8247_b', 'vs'), ('bf70b833d622277c_b', 'ps')]:
    path = next((runtime / 'shaders').glob('b-*/' + key + '.metal'))
    updated, locations = bridge(path.read_text(), stage)
    assert locations == [0, 1], 'Unexpected captured interface'
    path.write_text(updated)
    air = path.with_suffix('.probe.air')
    subprocess.run(['xcrun', '-sdk', 'macosx', 'metal', '-c', '-O1', '-fpreserve-invariance',
                    '-fmetal-math-mode=relaxed', str(path), '-o', str(air)], check=True, capture_output=True)
    subprocess.run(['xcrun', '-sdk', 'macosx', 'metallib', str(air), '-o', str(path.with_suffix('.metallib'))], check=True, capture_output=True)
    air.unlink()
    records[key] = locations
metadata['development_shader_probe'] = records
(runtime / 'runtime.json').write_text(json.dumps(metadata, indent=2) + '\n')
print('Prepared two private development interpolation controls; no IPA is built')
