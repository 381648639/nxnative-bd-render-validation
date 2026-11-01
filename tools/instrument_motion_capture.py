#!/usr/bin/env python3
"""Add bounded screenshot bursts to the development host only."""
from pathlib import Path
import sys

repo = Path(sys.argv[1])
legacy = repo / 'dm/gfx/nvn/nvn_mtl_legacy.inc'
source = legacy.read_text()
old = '#define SHOTQ_MAX 8'
assert source.count(old) == 1
source = source.replace(old, '#define SHOTQ_MAX 64  // Development capture queue only')
old = '    dm_shot_written(path, ok);'
assert source.count(old) == 1
source = source.replace(old, '''    if (screen) MLOG("[motion-capture] present=%llu time_ns=%llu path=%s ok=%d",
                     (unsigned long long)g_present_n,
                     (unsigned long long)clock_gettime_nsec_np(CLOCK_UPTIME_RAW), path, ok);
''' + old)
legacy.write_text(source)

hid = repo / 'dm/host/hle_hid.c'
source = hid.read_text()
old = '                if (!strncmp(line, "shot ", 5))'
assert source.count(old) == 1
source = source.replace(old, '''                // Queue before a held key: DM_CTL key holds block this thread.
                if (!strncmp(line, "shotburst ", 10)) {
                    int count, stride, lead, used = 0;
                    if (sscanf(line + 10, "%d %d %d %n", &count, &stride, &lead, &used) != 3 ||
                        count < 1 || count > 48 || stride < 1 || stride > 60 ||
                        lead < 1 || lead > 600 || !used || !line[10 + used]) {
                        LOG("[RED] DM_CTL shotburst wants count(1..48) stride(1..60) lead(1..600) path-prefix");
                        continue;
                    }
                    for (int i = 0; i < count; i++) {
                        char path[1024];
                        snprintf(path, sizeof path, "%s-%03d.png", line + 10 + used, i);
                        dm_gfx_shot_at(lead + (long)i * stride, path);
                    }
                    LOG("DM_CTL: queued %d development captures, stride %d, lead %d", count, stride, lead);
                    continue;
                }
''' + old)
hid.write_text(source)
print('Development-only screenshot bursts enabled; capture readbacks affect timing')
