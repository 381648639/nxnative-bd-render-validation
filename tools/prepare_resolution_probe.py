"""Add bounded resolution telemetry and live controls to a development host."""
import hashlib
import json
from pathlib import Path
import sys

repo, config, runtime = map(Path, sys.argv[1:])
path = repo / 'dm/host/hle_unity_screen.c'
source = path.read_text()
production_hash = hashlib.sha256(path.read_bytes()).hexdigest()
original_guard = '    if (!selected && !modified) return;   // bit-exact original behavior'
assert source.count(original_guard) == 1
source = source.replace(original_guard, '    int original_only = !selected && !modified;   // development: observe without writing')
old = '            if (pending == want) return;'
assert source.count(old) == 1
source = source.replace(old, '''            // Development-only size proof; no GPU readback or timing change.
            static int last_w, last_h, last_mode;
            if (current[0] != last_w || current[1] != last_h || mode != last_mode) {
                LOG("[resolution-probe] actual=%dx%d selected=%s mode=%d pending=%dx%d", current[0], current[1], resolution, mode, (int32_t)pending, (int32_t)(pending >> 32));
                last_w = current[0]; last_h = current[1]; last_mode = mode;
            }
            if (original_only) return;
''' + old)
path.write_text(source)

path = repo / 'dm/gfx/nvn/hle_nvn.c'
source = path.read_text()
old = '    o->magic = MAGIC(\'T\', \'E\', \'X\', 0); o->d = s->d; o->pool = s->pool; o->off = s->off;'
assert source.count(old) == 1
source = source.replace(old, old + '''
    static unsigned resolution_allocations;
    if (o->d.width >= 256 && o->d.height >= 144 && resolution_allocations++ < 3000)
        LOG("[resolution-probe] texture=%dx%d format=%d flags=%d", o->d.width, o->d.height, o->d.format, o->d.flags);
''')
path.write_text(source)

path = config / 'tools/visual_session.py'
source = path.read_text()
old = "                        elif 'shot' in step:"
assert source.count(old) == 1
source = source.replace(old, '''                        elif 'resolution' in step:
                            value = str(step['resolution'])
                            if value not in ('native', '1280x720', '960x540', '640x360'):
                                raise ValueError('Unsupported resolution probe value')
                            command('env DM_SCREEN_RESOLUTION=' + value)
                            pause(step.get('wait', 8))
''' + old)
compile(source, str(path), 'exec')
path.write_text(source)
(runtime / 'resolution-probe.json').write_text(json.dumps({
    'production_source_sha256': production_hash,
    'scope': 'Native Unity screen requests and texture size proof; not a phone power measurement',
    'shader_scope': 'Privately cached shaders with the existing two-shader non-finite control',
    'production_package_changed': False,
}, indent=2) + '\n')
