"""Observe the production shadow controller and active-size reader on the Mac."""
import hashlib
import json
from pathlib import Path
import sys

repo, config, runtime = map(Path, sys.argv[1:])
hashes = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in
          ('dm/host/hle_unity_screen.c', 'dm/host/hle_unity_quality.c', 'dm/ios/Sources/front_ios.m')}
path = repo / 'dm/host/hle_unity_quality.c'
source = path.read_text()
old = '    if (cap < 0 && !saved_object) return;'
assert source.count(old) == 1
source = source.replace(old, '    int observe_only = cap < 0 && !saved_object;')
old = '        if (object != saved_object || table != saved_table) {'
assert source.count(old) == 1
source = source.replace(old, '''        static int last_level = -1, last_shadow = -1;
        if (level != last_level || current != last_shadow) {
            int rw = 0, rh = 0;
            int known = dm_unity_screen_size(&rw, &rh);
            LOG("[quality-probe] vtable=+0x%llx level=%d shadow_enum=%d selected=%s active_render=%dx%d known=%d", (unsigned long long)(vtable - base), level, current, choice, rw, rh, known);
            last_level = level; last_shadow = current;
        }
        if (observe_only) return;
''' + old)
path.write_text(source)
path = config / 'tools/visual_session.py'
source = path.read_text()
old = "                        elif 'shot' in step:"
assert source.count(old) == 1
source = source.replace(old, '''                        elif 'shadow_quality' in step:
                            value = str(step['shadow_quality'])
                            if value not in ('native', 'balanced', 'low'):
                                raise ValueError('Unsupported shadow quality')
                            command('env DM_SHADOW_QUALITY=' + value)
                            pause(step.get('wait', 8))
''' + old)
compile(source, str(path), 'exec')
path.write_text(source)
(runtime / 'graphics-controls-probe.json').write_text(json.dumps({
    'production_sha256': hashes,
    'graphics_patch_sha256': hashlib.sha256((config / 'patches/graphics-controls.patch').read_bytes()).hexdigest(),
    'scope': 'Actual native shadow targets and render-size reader; not phone energy or thermal measurements',
}, indent=2) + '\n')
