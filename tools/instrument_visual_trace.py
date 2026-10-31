#!/usr/bin/env python3
"""Development-only GPU pixel history armed by the next live texture capture.

One captured frame splits draws at render-pass boundaries so the existing
asynchronous pixel readback can identify each writer. This is diagnostic code,
not a production renderer change; compare ordinary frames before and after.
"""
from pathlib import Path
import sys

repo = Path(sys.argv[1])
legacy = repo / 'dm/gfx/nvn/nvn_mtl_legacy.inc'
source = legacy.read_text()

def replace_once(old, new):
    global source
    assert source.count(old) == 1, old[:100]
    source = source.replace(old, new)

replace_once('static void pixel_history_begin(MTLRenderPassDescriptor *pd, NSUInteger nc);',
             'static uint64_t g_visual_trace_frame = UINT64_MAX;\n'
             'static void pixel_history_begin(MTLRenderPassDescriptor *pd, NSUInteger nc);')
replace_once('g_td_frame = (long)atomic_load(&g_cur_frame) + 1;',
             'g_td_frame = (long)atomic_load(&g_cur_frame) + 1;\n'
             '        g_visual_trace_frame = (uint64_t)g_td_frame;')
replace_once('    if (g_rt_range_pending) { PD("j rt_level_range pass=%llu vc=%u", g_stat_pass, (unsigned)(dw ? dw->count : di->count)); g_rt_range_pending=0; }',
             '    if (g_pixel_history.active) rp_end(); // Development capture: one writer per readback.\n'
             '    if (g_rt_range_pending) { PD("j rt_level_range pass=%llu vc=%u", g_stat_pass, (unsigned)(dw ? dw->count : di->count)); g_rt_range_pending=0; }')
old = '            if (g_rt_range_pending) { PD("j rt_level_range pass=%llu vc=%u", g_stat_pass, (unsigned)di->count); g_rt_range_pending = 0; }\n            return;'
assert source.count(old) == 2
source = source.replace(old, '            if (g_pixel_history.active) rp_end(); // Development capture only.\n' + old)
legacy.write_text(source)

header = repo / 'dm/gfx/nvn/nvn_pixel_history.h'
source = header.read_text()
replace_once('if (!pixel_history_configured() || !geometry_diag_frame()) return;',
             'if (!pixel_history_configured() || atomic_load(&g_cur_frame) != g_visual_trace_frame) return;')
replace_once('if (g_pixel_history.passes >= 128) return;',
             'if (g_pixel_history.passes >= 512) return;')
header.write_text(source)
print('Development pixel trace enabled for one live-captured frame, at most 512 writers')
