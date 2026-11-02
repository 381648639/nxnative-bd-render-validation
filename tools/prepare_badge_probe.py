"""Trace traditional pipeline operations in the private development runtime."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
cache = root / 'dm/gfx/nvn/nvn_pipeline_cache.m'
text = cache.read_text(encoding='utf-8')
marker = '// Bump only when descriptor generation'
assert text.count(marker) == 1
text = text.replace(marker, '''static void cache_trace(const char *operation) {
    if (getenv("DM_PIPELINE_TRACE"))
        PCLOG("trace thread=%p time=%.3f %s", (void *)pthread_self(), CFAbsoluteTimeGetCurrent(), operation);
}
''' + marker)
for name in ('lock', 'unlock'):
    old = 'pthread_mutex_' + name + '(&cache_mu);'
    text = text.replace(old, 'cache_trace("mutex ' + name + ' begin"); ' + old + ' cache_trace("mutex ' + name + ' end");')
operations = {
    'render-lookup': 'result = [device newRenderPipelineStateWithDescriptor:d options:MTLPipelineOptionFailOnBinaryArchiveMiss reflection:nil error:&miss];',
    'render-compile': 'result = [device newRenderPipelineStateWithDescriptor:desc error:error];',
    'compute-lookup': 'result = [device newComputePipelineStateWithDescriptor:d options:MTLPipelineOptionFailOnBinaryArchiveMiss reflection:nil error:&miss];',
    'compute-compile': 'result = [device newComputePipelineStateWithFunction:function error:error];',
}
for name, old in operations.items():
    assert text.count(old) == 1, name
    text = text.replace(old, 'cache_trace("' + name + ' begin"); ' + old + ' cache_trace("' + name + ' end");')
for name in ('Render', 'Compute'):
    old = 'if ([archive add' + name + 'PipelineFunctionsWithDescriptor:d error:&add_error])'
    if old in text:  # The candidate records on its private writer queue instead.
        assert text.count(old) == 1
        text = text.replace(old, 'cache_trace("' + name.lower() + '-add begin"); BOOL added_ok = [archive add' + name + 'PipelineFunctionsWithDescriptor:d error:&add_error]; cache_trace("' + name.lower() + '-add end");\n        if (added_ok)')
old = 'if (ok) ok = [archive serializeToURL:[NSURL fileURLWithPath:temp] error:&error];'
assert text.count(old) == 1
text = text.replace(old, 'if (ok) { cache_trace("serialize begin"); ok = [archive serializeToURL:[NSURL fileURLWithPath:temp] error:&error]; cache_trace("serialize end"); }')
cache.write_text(text, encoding='utf-8')

legacy = root / 'dm/gfx/nvn/nvn_mtl_legacy.inc'
text = legacy.read_text(encoding='utf-8')
old = 'id<MTLRenderPipelineState> ps = nvn_cached_render_specialized(g_dev, d, specialized, error);'
assert text.count(old) == 1
text = text.replace(old, '''if (getenv("DM_PIPELINE_TRACE")) MLOG("Pipeline begin thread=%p vs=%s fs=%s formats=%lu/%lu/%lu topology=%lu specialized=%d", (void *)pthread_self(), vs->key, fs ? fs->key : "-", (unsigned long)d.colorAttachments[0].pixelFormat, (unsigned long)d.depthAttachmentPixelFormat, (unsigned long)d.stencilAttachmentPixelFormat, (unsigned long)d.inputPrimitiveTopology, specialized);
    ''' + old + '''
    if (getenv("DM_PIPELINE_TRACE")) MLOG("Pipeline end thread=%p vs=%s fs=%s ok=%d", (void *)pthread_self(), vs->key, fs ? fs->key : "-", ps != nil);''')
legacy.write_text(text, encoding='utf-8')

# Exercise the existing scripted background sequence at an observed scene. This
# uses the same guest clock and graphics gate as DM_OE_SCRIPT, without relaunching
# or changing the game save. It does not emulate UIKit or the iOS watchdog.
oe = root / 'dm/host/hle_oe.c'
text = oe.read_text(encoding='utf-8')
old = 'static void *oe_script(void *arg) {'
assert text.count(old) == 1
text = text.replace(old, 'void dm_badge_background(int on) { LOG("badge probe: background=%d begin", on); script_bg(on); LOG("badge probe: background=%d end", on); }\n' + old)
oe.write_text(text, encoding='utf-8')
hid = root / 'dm/host/hle_hid.c'
text = hid.read_text(encoding='utf-8')
old = '                if (!strncmp(line, "shot ", 5))'
assert text.count(old) == 1
text = text.replace(old, '                if (!strncmp(line, "background ", 11)) { void dm_badge_background(int on); dm_badge_background(atoi(line + 11)); continue; }\n' + old)
hid.write_text(text, encoding='utf-8')
print('Development-only traditional pipeline operation trace enabled')
