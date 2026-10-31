#!/usr/bin/env python3
"""Instrument the development build only; shipped iOS sources are unaffected."""
from pathlib import Path
import sys

repo = Path(sys.argv[1])
script = repo / "scripts/build_ipa_from_nsp.py"
source = script.read_text()
old = "cmd = shlex.split(line); cmd[cmd.index('-o') + 1] = out"
assert source.count(old) == 1
source = source.replace(old, "cmd = shlex.split(line); cmd.insert(1, '-DDM_NVN_LEGACY_RENDERER_TEST=1'); cmd[cmd.index('-o') + 1] = out")
old = "    run(cmd, logs / 'mac_host_build.log', env=env, cwd=host)"
assert source.count(old) == 1
source = source.replace(old, "    (logs / 'mac_host_command.json').write_text(json.dumps([str(c) for c in cmd], indent=2) + '\\n')\n" + old)
start = source.index("def mac_run(")
end = source.index("\n\nMTL_ARCH_M", start)
section = source[start:end]
old = "if gfx == 'nvn' and g.table('shader_pairs.tsv').is_file():"
assert section.count(old) == 1
# The modern Metal 4 pipeline tool cannot prebuild a legacy host's pipelines.
# Legacy replay creates its own Metal 2/3 pipelines while running the game.
section = section.replace(old, "if False:  # Visual harness: legacy replay has no modern pipeline prebuild")
old = "    q = lambda v: shlex.quote(str(v))"
assert section.count(old) == 1
section = section.replace(old, """    (work / 'visual-runtime.json').write_text(json.dumps({
        'host': str(host), 'patched': str(patched), 'cwd': str(rd),
        'env': {k: str(v) for k, v in renv.items()},
        'renderer': 'legacy', 'compile_define': 'DM_NVN_LEGACY_RENDERER_TEST=1',
        'upstream': '1942eaa5e2a767809868994c27dfc5d692439fdc',
        'scope': 'Real guest game on macOS Metal; not an A15 device test'
    }, indent=2) + '\\n')
    q = lambda v: shlex.quote(str(v))""")
source = source[:start] + section + source[end:]
compile(source, str(script), "exec")
script.write_text(source)

# Development-only controls: the production legacy host exposes an inert live
# texture-dump entry point, although its frame-selected exporter is implemented.
# Hand requests from the input thread to the submission thread before collecting
# the following frame. All Metal work remains on the submission thread.
legacy = repo / 'dm/gfx/nvn/nvn_mtl_legacy.inc'
text = legacy.read_text()
old = 'static void td_dump(void);'
assert text.count(old) == 1
text = text.replace(old, old + '''
static pthread_mutex_t g_td_live_mu = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int g_td_live_pending;
static char g_td_live_requested[1024], g_td_live_active[1024];
''')
old = 'void td_note(MTLRenderPassDescriptor *pd, NSUInteger nc) {'
assert text.count(old) == 1
text = text.replace(old, old + '''
    if (atomic_load_explicit(&g_td_live_pending, memory_order_acquire)) {
        pthread_mutex_lock(&g_td_live_mu);
        strlcpy(g_td_live_active, g_td_live_requested, sizeof g_td_live_active);
        atomic_store_explicit(&g_td_live_pending, 0, memory_order_release);
        pthread_mutex_unlock(&g_td_live_mu);
        g_td_path = g_td_live_active;
        g_td_frame = (long)atomic_load(&g_cur_frame) + 1;
        g_td_done = 0; g_td_w = g_td_h = 0;
        g_td_list = [NSMutableArray array];
    }
''')
old = 'void dm_gfx_texdump_next(const char *path) { (void)path; }'
assert text.count(old) == 1
text = text.replace(old, '''void dm_gfx_texdump_next(const char *path) {
    if (!path || !*path) return;
    pthread_mutex_lock(&g_td_live_mu);
    strlcpy(g_td_live_requested, path, sizeof g_td_live_requested);
    atomic_store_explicit(&g_td_live_pending, 1, memory_order_release);
    pthread_mutex_unlock(&g_td_live_mu);
}''')
legacy.write_text(text)
print("Development host will compile legacy replay and export its real game runtime paths")
