// Development-only uniform readback at the GPU position of the captured draw.
// The original CPU pool bytes can be stale when inline copies are still queued.
typedef struct {
    __strong id<MTLBuffer> source;
    NSUInteger offset, size;
    uint64_t frame, pass;
    int stage, reg;
    char key[20];
} visual_uniform_record;
static visual_uniform_record g_visual_uniforms[16];
static int g_visual_uniform_count;

static void visual_uniform_note(NvShader *shader, int stage, int reg, uint64_t gpu, uint64_t size) {
    if (atomic_load(&g_cur_frame) != g_visual_trace_frame || !size || size > 65536 || g_visual_uniform_count >= 16) return;
    const char *keys = getenv("DM_NVN_TRACE_SHADERS");
    if (!keys || !strstr(keys, shader->key)) return;
    NSUInteger offset = 0;
    id<MTLBuffer> source = legacy_buffer_at(gpu, &offset);
    if (!source || offset > source.length || size > source.length - offset) return;
    visual_uniform_record *record = &g_visual_uniforms[g_visual_uniform_count++];
    record->source = source; record->offset = offset; record->size = (NSUInteger)size;
    record->frame = atomic_load(&g_cur_frame); record->pass = g_stat_pass;
    record->stage = stage; record->reg = reg;
    strlcpy(record->key, shader->key, sizeof record->key);
}

static void visual_uniform_flush(void) {
    if (!g_visual_uniform_count) return;
    const char *folder = getenv("DM_NVN_CBDUMP");
    if (g_cb && folder && *folder) {
        id<MTLBlitCommandEncoder> encoder = enc_b_begin(g_cb);
        for (int i = 0; i < g_visual_uniform_count; i++) {
            const visual_uniform_record *record = &g_visual_uniforms[i];
            id<MTLBuffer> output = [g_dev newBufferWithLength:record->size options:MTLResourceStorageModeShared];
            if (!output) continue;
            enc_b_copy_buffer(encoder, record->source, record->offset, output, 0, record->size);
            NSString *path = [NSString stringWithFormat:@"%s/GPU_F%llu_p%llu_st%d_cb%d_%s.bin", folder,
                (unsigned long long)record->frame, (unsigned long long)record->pass, record->stage, record->reg, record->key];
            __block id<MTLBuffer> keep_source = record->source;
            [g_cb addCompletedHandler:^(id<MTLCommandBuffer> cb) {
                if (!cb.error) {
                    FILE *file = fopen(path.fileSystemRepresentation, "wb");
                    if (file) { fwrite(output.contents, 1, output.length, file); fclose(file); }
                }
                keep_source = nil;
            }];
            MLOG("[visual-uniform] frame=%llu pass=%llu stage=%d reg=%d key=%s bytes=%lu GPU-position capture queued", 
                (unsigned long long)record->frame, (unsigned long long)record->pass, record->stage, record->reg, record->key, (unsigned long)record->size);
        }
        enc_b_end(encoder);
    }
    for (int i = 0; i < g_visual_uniform_count; i++) g_visual_uniforms[i].source = nil;
    g_visual_uniform_count = 0;
}
