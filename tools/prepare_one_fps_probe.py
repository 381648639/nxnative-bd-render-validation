"""Instrument the existing 30-fps branch for a real-game 1-fps control.

Only the development host is changed. The probe scales the period calculated
inside fps_target_30(), without adding another wait or bypassing that branch.
The ordinary target remains 30; value 1 is not a supported launcher target.
"""
import hashlib
import json
from pathlib import Path
import sys

repo, config, runtime = map(Path, sys.argv[1:])
path = repo / 'dm/gfx/nvn/hle_nvn.c'
source = path.read_text(encoding='utf-8')
original_sha = hashlib.sha256(path.read_bytes()).hexdigest()
old = '        uint64_t cap_period = (uint64_t)itv * 1000000000ull / 60;'
assert source.count(old) == 1
source = source.replace(old, old + '''
        // Development-only extreme control through the existing target branch.
        // No separate sleep: real acquire/slot/drawable pacing consumes this.
        const char *probe = getenv("DM_TEST_PACING_CAP_NS");
        if (probe && !strcmp(probe, "1000000000")) cap_period = 1000000000ull;
''')
old = '    if (idx >= 0 && idx < 4) o->avail[idx] = period ? slot + period : 0;'
assert source.count(old) == 1
source = source.replace(old, old + '''
    // Bounded per-present telemetry, no GPU readback or extra wait.
    static unsigned probe_samples;
    extern uint64_t mtl_present_count(void);
    if (++probe_samples <= 12000) {
        const char *target_env = getenv("DM_FPS_TARGET");
        const char *probe_env = getenv("DM_TEST_PACING_CAP_NS");
        LOG("[pacing-probe] seq=%llu at_ns=%llu shown=%llu period_ns=%llu target_env=%s cap_active=%d state=%p link=%d probe=%s",
            (unsigned long long)o->presents, (unsigned long long)now_ns(),
            (unsigned long long)mtl_present_count(), (unsigned long long)period,
            target_env ? target_env : "profile", fps_target_30(), dm_fps_state,
            mtl_link_active(), probe_env ? probe_env : "0");
    }
''')
path.write_text(source, encoding='utf-8')

# Add one narrow, development-only live control to the existing session driver.
session = config / 'tools/visual_session.py'
source = session.read_text(encoding='utf-8')
old = "                        elif 'shot' in step:"
assert source.count(old) == 1
source = source.replace(old, '''                        elif 'probe_fps' in step:
                            value = int(step['probe_fps'])
                            if value not in (1, 30):
                                raise ValueError('Pacing probe accepts only 1 or 30')
                            period = '1000000000' if value == 1 else '0'
                            command('env DM_TEST_PACING_CAP_NS=' + period)
                            pause(step.get('wait', 0))
''' + old)
compile(source, str(session), 'exec')
session.write_text(source, encoding='utf-8')

metadata = {
    'unmodified_hle_nvn_sha256': original_sha,
    'instrumented_hle_nvn_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    'mechanism': 'scale period inside the existing fps_target_30 branch; no new wait',
    'targets': [1, 30],
    'scope': 'development host using r5 pacing and privately cached shader assets',
    'shader_scope': 'existing two-shader non-finite development control, not a full r5 shader rebuild',
    'production_ipa_changed': False,
}
(runtime / 'one-fps-probe.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
print('Prepared bounded one-fps control through the existing production target branch')
