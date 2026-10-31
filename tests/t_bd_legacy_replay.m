// Exercise the production NVN recorder and legacy Metal replay, including GPU
// reads after queued copies. No game assets, keys or device installation needed.
#define DM_NVN_LEGACY_RENDERER_TEST 1
#include "../nvn/nvn_mtl.m"
#include "../nvn/nvn_protos.h"
#include "../../host/hle.h"
#include <mach-o/getsect.h>
#include <mach-o/ldsyms.h>

uint64_t g_t0_ns;
int dm_guest_as_contains(uintptr_t p) { (void)p; return 0; }
int front_screen_max_fps(void) { return 60; }
void *front_metal_layer(void) { return NULL; }
module_t *module_of(const void *p) { (void)p; return NULL; }
module_t *g_mod; int g_nmod;
void svc_thread_dump(void) {}
uint64_t now_ns(void) { return bp_now(); }
static int checks, failures;
#define CHECK(c, label) do { checks++; if (!(c)) { failures++; fprintf(stderr, "FAIL: %s\n", label); } } while (0)
static PFNNVNDEVICEGETPROCADDRESSPROC gpa;
#define API(name) ((NVNT_##name)gpa(NULL, #name))
static NVNcommandBuffer command;
static NVNmemoryPool pool;
static NVNdevice device;
static NVNqueue queues[2];
static uint8_t *memory;
static prog_t graphics = {.magic=MAGIC('P','R','O','G'),.serial=980001};
static prog_t compute = {.magic=MAGIC('P','R','O','G'),.serial=980002};
static tex_t target;
static void begin(int queue) {
    mtl_queue_activate(((queue_t *)&queues[queue])->serial);
    state_reset(); memset(&R, 0, sizeof R);
    API(nvnCommandBufferBeginRecording)(&command);
}
static void submit(int queue) {
    NVNcommandHandle handle = API(nvnCommandBufferEndRecording)(&command);
    API(nvnQueueSubmitCommands)(&queues[queue], 1, &handle);
    API(nvnQueueFinish)(&queues[queue]);
    CHECK(!mtl_last_commit_error(), "recorded work completes without a Metal error");
}
static void prediction(NvShader *vs, NvShader *fs) {
    // Even a scan that finds no pipelines must leave both forms of scissor
    // state intact. Exercise the production scanner with real command records.
    struct { op_hdr h; p_scissor sc; op_hdr end; } lookahead = {
        .h={OP_SCISSOR, sizeof(op_hdr)+sizeof(p_scissor)},
        .sc={0,0,1,1}, .end={OP_END,sizeof(op_hdr)}
    };
    for (int enabled=0;enabled<2;enabled++) {
        state_reset(); memset(&R,0,sizeof R);
        const p_scissor original={1,2,5,4}; R.sc=original; R.has_sc=enabled;
        g_exec_next=(const uint8_t *)&lookahead;
        pso_predict_rest(); g_exec_next=NULL;
        CHECK(!memcmp(&R.sc,&original,sizeof original),"prediction preserves the current scissor rectangle");
        CHECK(R.has_sc==enabled,"prediction preserves whether the scissor was set");
    }
    id<MTLBuffer> pixels=[g_dev newBufferWithLength:2048 options:MTLResourceStorageModeShared];
    for (int mode=0;mode<3;mode++) {
        // A distinct vertex shader object forces a first-use pipeline miss in
        // each case, without clearing caches or replacing the production replay.
        NvShader *pv=[NvShader new]; pv->fn=vs->fn; pv->rf=vs->rf;
        NvProg *pg=[NvProg new]; pg->sh[0]=pv; pg->sh[1]=fs;
        prog_t pred={.magic=MAGIC('P','R','O','G'),.serial=981000+mode}; serial_put(pred.serial,pg);
        API(nvnDeviceSetWindowOriginMode)(&device,NVN_WINDOW_ORIGIN_MODE_UPPER_LEFT);
        float p[3][4]={{-1,-1,.5,1},{3,-1,.5,1},{-1,3,.5,1}}; memcpy(memory,p,sizeof p);
        begin(0);
        const NVNtexture *color=(NVNtexture *)&target;
        API(nvnCommandBufferSetRenderTargets)(&command,1,&color,NULL,NULL,NULL);
        const float blue[4]={0,0,1,1}; API(nvnCommandBufferClearColor)(&command,0,blue,15);
        API(nvnCommandBufferBindProgram)(&command,(NVNprogram *)&pred,3);
        ds_st depth={.df=NVN_DEPTH_FUNC_ALWAYS}; API(nvnCommandBufferBindDepthStencilState)(&command,(NVNdepthStencilState *)&depth);
        va_st attribute={.fmt=NVN_FORMAT_RGBA32F}; vs_st stream={.stride=16};
        API(nvnCommandBufferBindVertexAttribState)(&command,1,(NVNvertexAttribState *)&attribute);
        API(nvnCommandBufferBindVertexStreamState)(&command,1,(NVNvertexStreamState *)&stream);
        API(nvnCommandBufferBindVertexBuffer)(&command,0,(uint64_t)memory,sizeof p);
        if (mode==1) API(nvnCommandBufferSetScissor)(&command,0,0,8,8);
        if (mode==2) API(nvnCommandBufferSetScissor)(&command,1,2,5,4);
        API(nvnCommandBufferDrawArrays)(&command,NVN_DRAW_PRIMITIVE_TRIANGLES,0,3);
        // This state belongs after the draw. The predictor sees it while the
        // cold pipeline compiles, but must not apply it to that earlier draw.
        API(nvnCommandBufferSetScissor)(&command,0,0,1,1);
        submit(0);
        CHECK(g_pp_submit_mark==g_sub_serial,"a cold draw invokes the production pipeline predictor");
        id<MTLCommandBuffer> cb=[g_q commandBuffer]; id<MTLBlitCommandEncoder> blit=[cb blitCommandEncoder];
        [blit copyFromTexture:tex_mtl(&target) sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
                  sourceSize:MTLSizeMake(8,8,1) toBuffer:pixels destinationOffset:0 destinationBytesPerRow:256 destinationBytesPerImage:2048];
        [blit endEncoding]; [cb commit]; [cb waitUntilCompleted];
        CHECK(cb.status==MTLCommandBufferStatusCompleted,"prediction pixel readback completes");
        int good=1;
        for(int y=0;y<8;y++) for(int x=0;x<8;x++) {
            const uint8_t *v=(const uint8_t *)pixels.contents+y*256+x*4;
            int inside=mode!=2 || (x>=1 && x<6 && y>=2 && y<6);
            good &= v[3]==255 && (inside ? v[2]==0 && v[0]+v[1]==255 : v[0]==0 && v[1]==0 && v[2]==255);
        }
        if(!good) fprintf(stderr,"prediction pixel mismatch: scissor mode=%d\n",mode);
        CHECK(good,"a later predicted scissor does not clip the current GPU draw");
    }
}
static void raster(void) {
    static const int front_in_clip[2][2][2] = {{{0,1},{1,0}},{{1,0},{0,1}}};
    id<MTLBuffer> pixels = [g_dev newBufferWithLength:2048 options:MTLResourceStorageModeShared];
    for (int current=0;current<2;current++) for (int winding=0;winding<2;winding++)
    for (int cull=0;cull<4;cull++) for (int ccw=0;ccw<2;ccw++) for (int flip=0;flip<2;flip++) for (int queue=0;queue<2;queue++) {
        API(nvnDeviceSetWindowOriginMode)(&device, (NVNwindowOriginMode)current);
        float p[3][4] = {{-1,-1,.5,1},{3,-1,.5,1},{-1,3,.5,1}};
        if (!ccw) { float t[4]; memcpy(t,p[1],16); memcpy(p[1],p[2],16); memcpy(p[2],t,16); }
        memcpy(memory, p, sizeof p);
        begin(queue);
        const NVNtexture *color = (NVNtexture *)&target;
        API(nvnCommandBufferSetRenderTargets)(&command, 1, &color, NULL, NULL, NULL);
        const float blue[4] = {0,0,1,1}; API(nvnCommandBufferClearColor)(&command,0,blue,15);
        API(nvnCommandBufferBindProgram)(&command,(NVNprogram *)&graphics,3);
        ds_st depth = {.df=NVN_DEPTH_FUNC_ALWAYS};
        API(nvnCommandBufferBindDepthStencilState)(&command,(NVNdepthStencilState *)&depth);
        poly_st poly = {.cull=cull,.front=winding,.mode=NVN_POLYGON_MODE_FILL};
        API(nvnCommandBufferBindPolygonState)(&command,(NVNpolygonState *)&poly);
        va_st attribute = {.fmt=NVN_FORMAT_RGBA32F}; vs_st stream = {.stride=16};
        API(nvnCommandBufferBindVertexAttribState)(&command,1,(NVNvertexAttribState *)&attribute);
        API(nvnCommandBufferBindVertexStreamState)(&command,1,(NVNvertexStreamState *)&stream);
        API(nvnCommandBufferBindVertexBuffer)(&command,0,(uint64_t)memory,sizeof p);
        NVNviewportSwizzle sw[4] = {0,flip ? 3 : 2,4,6};
        API(nvnCommandBufferSetViewportSwizzles)(&command,0,1,sw);
        API(nvnCommandBufferDrawArrays)(&command,NVN_DRAW_PRIMITIVE_TRIANGLES,0,3);
        submit(queue);
        int front = ccw == (front_in_clip[queue][current][winding] ^ flip);
        int visible = cull == NVN_FACE_NONE || (cull == NVN_FACE_FRONT && !front) || (cull == NVN_FACE_BACK && front);
        p_draw draw = {.prim=NVN_DRAW_PRIMITIVE_TRIANGLES,.count=3,.instances=1}; g_fd_dw=&draw;
        CHECK(first_draw_covers(0,tex_mtl(&target),0)==visible,"coverage proof agrees with raster origin and swizzle"); g_fd_dw=NULL;
        id<MTLCommandBuffer> cb = [g_q commandBuffer]; id<MTLBlitCommandEncoder> blit = [cb blitCommandEncoder];
        [blit copyFromTexture:tex_mtl(&target) sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
                  sourceSize:MTLSizeMake(8,8,1) toBuffer:pixels destinationOffset:0 destinationBytesPerRow:256 destinationBytesPerImage:2048];
        [blit endEncoding]; [cb commit]; [cb waitUntilCompleted];
        uint8_t expected[4] = {visible && !front ? 255:0,visible && front ? 255:0,visible ? 0:255,255};
        int good=1; for(int y=0;y<8;y++) for(int x=0;x<8;x++) good &= !memcmp((uint8_t *)pixels.contents+y*256+x*4,expected,4);
        if(!good) fprintf(stderr,"raster mismatch: queue=%d device=%d winding=%d cull=%d CCW=%d flip=%d\n",queue,current,winding,cull,ccw,flip);
        CHECK(good,"actual culling and front_facing preserve queue origin and NEGATIVE_Y");
    }
}
static void dispatch_case(int indirect,int interleave,int unbind_graphics) {
    API(nvnDeviceSetWindowOriginMode)(&device,NVN_WINDOW_ORIGIN_MODE_UPPER_LEFT);
    uint32_t *out=(uint32_t *)(memory+4096), *counts=(uint32_t *)(memory+8192), *desired=(uint32_t *)(memory+8448);
    memset(out,0,512); memset(counts,0,12); desired[0]=3;desired[1]=2;desired[2]=2;
    *(uint32_t *)(memory+12288)=0; *(uint32_t *)(memory+12544)=0x12345678;
    begin(0);
    // The CPU still sees zero at the argument and uniform destinations. Only
    // ordered GPU work can make the following dispatch read their new values.
    API(nvnCommandBufferCopyBufferToBuffer)(&command,(uint64_t)desired,(uint64_t)counts,12,0);
    API(nvnCommandBufferCopyBufferToBuffer)(&command,(uint64_t)(memory+12544),(uint64_t)(memory+12288),4,0);
    API(nvnCommandBufferBindUniformBuffer)(&command,5,0,(uint64_t)(memory+12288),256);
    API(nvnCommandBufferBindStorageBuffer)(&command,5,0,(uint64_t)out,512);
    API(nvnCommandBufferBindProgram)(&command,(NVNprogram *)&graphics,3);
    API(nvnCommandBufferBindProgram)(&command,(NVNprogram *)&compute,0x20);
    if (interleave || unbind_graphics) API(nvnCommandBufferBindProgram)(&command,unbind_graphics ? NULL : (NVNprogram *)&graphics,3);
    if (indirect) API(nvnCommandBufferDispatchComputeIndirect)(&command,(uint64_t)counts);
    else API(nvnCommandBufferDispatchCompute)(&command,3,2,2);
    submit(0);
    for(int i=0;i<12;i++) CHECK(out[i]==0xab030202,"all groups execute with GPU-ordered c0 dispatch dimensions");
    CHECK(out[12]==0 && out[64]==0x12345678,"dispatch is bounded and reads the GPU-updated uniform");
    CHECK(S.prog==(unbind_graphics ? NULL : &graphics),"compute binding preserves the independent graphics program");
}
int main(int argc, char **argv) { @autoreleasepool {
    if (!MTLCreateSystemDefaultDevice()) { fprintf(stderr,"SKIP: runner exposes no Metal device; GPU execution is unavailable\n"); return 77; }
    mtl_init();
    unsigned long length=0; const hle_force_ent *entries=(const hle_force_ent *)getsectiondata(&_mh_execute_header,"__DATA","swforce",&length);
    void *(*bootstrap)(const char *)=NULL;
    for(size_t i=0;i<length/sizeof *entries;i++) if(!strcmp(entries[i].name,"nvnBootstrapLoader")) bootstrap=entries[i].fn;
    CHECK(bootstrap!=NULL,"production NVN bootstrap is registered"); if(!bootstrap)return 1;
    gpa=(PFNNVNDEVICEGETPROCADDRESSPROC)bootstrap("nvnDeviceGetProcAddress");
    CHECK(!posix_memalign((void **)&memory,getpagesize(),65536),"guest pool allocation"); if(!memory)return 1; memset(memory,0,65536);
    NVNmemoryPoolBuilder pb; API(nvnMemoryPoolBuilderSetDefaults)(&pb); API(nvnMemoryPoolBuilderSetStorage)(&pb,memory,65536);
    API(nvnMemoryPoolBuilderSetFlags)(&pb,NVN_MEMORY_POOL_FLAGS_CPU_UNCACHED|NVN_MEMORY_POOL_FLAGS_GPU_CACHED);
    CHECK(API(nvnMemoryPoolInitialize)(&pool,&pb),"guest pool initializes");
    CHECK(API(nvnCommandBufferInitialize)(&command,NULL),"recorder initializes");
    API(nvnCommandBufferAddCommandMemory)(&command,&pool,32768,32768);
    NVNdeviceBuilder db; API(nvnDeviceBuilderSetDefaults)(&db); CHECK(API(nvnDeviceInitialize)(&device,&db),"device initializes");
    for(int origin=0;origin<2;origin++) {
        API(nvnDeviceSetWindowOriginMode)(&device,(NVNwindowOriginMode)origin);
        NVNqueueBuilder qb; API(nvnQueueBuilderSetDefaults)(&qb); API(nvnQueueBuilderSetDevice)(&qb,&device);
        CHECK(API(nvnQueueInitialize)(&queues[origin],&qb),"queue captures its own raster origin");
    }
    NSError *error=nil;
    id<MTLLibrary> library=[g_dev newLibraryWithSource:@"#include <metal_stdlib>\nusing namespace metal;\n"
        "struct I {float4 p [[attribute(0)]];}; vertex float4 v(I i [[stage_in]]) {return i.p;}\n"
        "fragment float4 f(bool front [[front_facing]]) {return front?float4(0,1,0,1):float4(1,0,0,1);}\n"
        "struct A {device uint *out [[id(0)]]; constant uint *c0 [[id(1)]]; constant uint *u [[id(2)]];};\n"
        "kernel void k(constant A&a [[buffer(0)]],uint3 g [[threadgroup_position_in_grid]],uint3 n [[threadgroups_per_grid]]) {"
        "uint i=g.x+n.x*(g.y+n.y*g.z); a.out[i]=0xab000000|(a.c0[128]<<16)|(a.c0[129]<<8)|a.c0[130];"
        "if(all(g==uint3(0)))a.out[64]=a.u[0];}\n" options:nil error:&error];
    CHECK(library!=nil,"reference shaders compile"); if(!library){fprintf(stderr,"%s\n",error.localizedDescription.UTF8String);return 1;}
    NvShader *vs=[NvShader new],*fs=[NvShader new],*cs=[NvShader new]; NvProg *gp=[NvProg new],*cp=[NvProg new];
    vs->fn=[library newFunctionWithName:@"v"]; vs->rf.nv=1;vs->rf.v[0].ct=NVN_CT_FLOAT;
    memset(vs->rf.v[0].sh,0xff,sizeof vs->rf.v[0].sh);vs->rf.pos_attr=0;vs->rf.pos_w1=1;
    fs->fn=[library newFunctionWithName:@"f"];fs->stage=1;fs->rf.color_known=1;fs->rf.color_mask=1;
    gp->sh[0]=vs;gp->sh[1]=fs;serial_put(graphics.serial,gp);
    cs->fn=[library newFunctionWithName:@"k"];cs->stage=5;cs->rf.tg[0]=cs->rf.tg[1]=cs->rf.tg[2]=1;
    cs->ae=[cs->fn newArgumentEncoderWithBufferIndex:0];cs->arg_len=cs->ae.encodedLength;cs->rf.nb=3;cs->rf.drv_read[0]=1;
    cs->rf.b[0]=(nvn_rbind){.kind=NVN_RB_SBUFP,.rw=1,.aid=0,.reg=0};
    cs->rf.b[1]=(nvn_rbind){.kind=NVN_RB_DRV0,.aid=1};
    cs->rf.b[2]=(nvn_rbind){.kind=NVN_RB_CBUF,.aid=2,.reg=0};
    cp->sh[5]=cs;serial_put(compute.serial,cp);
    target.magic=MAGIC('T','E','X',0);target.serial=980003;
    target.d=(nvn_texdesc){.target=NVN_TEXTURE_TARGET_2D,.format=NVN_FORMAT_RGBA8,.width=8,.height=8,.depth=1,.levels=1,.samples=1};
    prediction(vs,fs);
    if(argc>1 && !strcmp(argv[1],"--prediction-only")) {
        printf("legacy prediction: %d checks, %d failures\n",checks,failures); return failures!=0;
    }
    raster();
    for(int indirect=0;indirect<2;indirect++) for(int interleave=0;interleave<2;interleave++) dispatch_case(indirect,interleave,0);
    dispatch_case(0,0,1);dispatch_case(1,0,1);
    printf("legacy NVN replay: %d checks, %d failures\n",checks,failures);
    return failures!=0;
} }
