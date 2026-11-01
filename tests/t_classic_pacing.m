// Full NVN acquire/present loop without a Metal display link. Rendering is an
// immediate-completion sink: the fastest possible GPU cannot hide a missing
// host cap. The production swapchain availability and pacer run unchanged.
// Controlled runs replace only clock/wait APIs. Wall builds use real Mach
// time and waits. This does not emulate drawable presentation or game physics.
#import <Foundation/Foundation.h>
#include <mach/mach_time.h>
#include <time.h>
#include <math.h>

#ifndef CLASSIC_WALL_CLOCK
#define CLASSIC_WALL_CLOCK 0
#endif
static uint64_t classic_now = 10000000000ull;
static uint64_t classic_sleeps;
#if !CLASSIC_WALL_CLOCK
static int classic_clock_gettime(clockid_t c, struct timespec *t) {
    (void)c;
    *t = (struct timespec){classic_now / 1000000000ull, classic_now % 1000000000ull};
    return 0;
}
static uint64_t classic_absolute_time(void) { return classic_now * 3 / 125; }
static kern_return_t classic_timebase_info(mach_timebase_info_t t) {
    t->numer = 125; t->denom = 3; return KERN_SUCCESS;
}
static kern_return_t classic_wait_until(uint64_t deadline) {
    classic_sleeps++;
    uint64_t ns = (deadline * 125 + 2) / 3;
    if (ns > classic_now) classic_now = ns;
    return KERN_SUCCESS;
}
#define clock_gettime classic_clock_gettime
#endif
#define nvn_game_fps nvn_game_fps_mtl_default
#define mtl_present classic_unused_renderer_present
#include "../nvn/nvn_mtl.m"
#undef mtl_present
#undef nvn_game_fps
#undef clock_gettime

uint64_t mtl_present(const tex_t *, double, const int[4]);
#if !CLASSIC_WALL_CLOCK
#define mach_absolute_time classic_absolute_time
#define mach_timebase_info classic_timebase_info
#define mach_wait_until classic_wait_until
#endif
#define g_ft g_ft_hle
#include "../nvn/hle_nvn.c"
#undef g_ft
#undef mach_absolute_time
#undef mach_timebase_info
#undef mach_wait_until

void *front_metal_layer(void) { return NULL; }
module_t *module_of(const void *p) { (void)p; return NULL; }
module_t *g_mod; int g_nmod;
void svc_thread_dump(void) {}
uint64_t now_ns(void) {
#if CLASSIC_WALL_CLOCK
    static mach_timebase_info_data_t tb;
    if (!tb.denom) mach_timebase_info(&tb);
    return mach_absolute_time() * tb.numer / tb.denom;
#else
    return classic_now;
#endif
}
static double classic_duration;
static uint64_t classic_enqueues;
uint64_t mtl_present(const tex_t *t, double period, const int crop[4]) {
    (void)t; (void)crop;
    classic_duration = period; classic_enqueues++;
    return 0; // Already completed; texture reuse still waits for its NVN slot.
}
static int checks, failed;
#define CHECK(c, label) do { checks++; if (!(c)) { failed++; fprintf(stderr, "FAIL: %s\n", label); } } while (0)
static void work(uint64_t ns) {
#if CLASSIC_WALL_CLOCK
    struct timespec ts = {ns / 1000000000ull, ns % 1000000000ull};
    nanosleep(&ts, NULL);
#else
    classic_now += ns;
#endif
}
static void frame(win_t *w, int workload, unsigned f) {
    int idx = -1;
    CHECK(h_nvnWindowAcquireTexture((NVNwindow *)w, NULL, &idx) == NVN_WINDOW_ACQUIRE_TEXTURE_RESULT_SUCCESS, "classic acquire succeeds");
    CHECK(idx >= 0 && idx < w->ntex, "classic acquire returns a valid swapchain index");
    const uint64_t costs[] = {100000ull, 10000000ull, 20000000ull, 45000000ull};
    work(workload == 4 ? costs[f % 4] : costs[workload]);
    h_nvnQueuePresentTexture(NULL, (NVNwindow *)w, idx);
}
static void run_case(int textures, int workload, int target, int hz) {
    char value[16]; snprintf(value, sizeof value, "%d", target);
    setenv("DM_FPS_TARGET", value, 1);
    nvn_present_config(hz, 1);
    NVNtexture tex[4] = {0};
    win_t w = {.ntex = textures, .interval = 2};
    for (int i = 0; i < textures; i++) w.tex[i] = &tex[i];
    for (unsigned f = 0; f < 16; f++) frame(&w, workload, f);
    uint64_t start = now_ns(), enqueues = classic_enqueues;
    int frames = CLASSIC_WALL_CLOCK ? 60 : 180;
    for (unsigned f = 0; f < (unsigned)frames; f++) frame(&w, workload, f);
    double seconds = (now_ns() - start) / 1e9, fps = frames / seconds;
    double limit = target == 30 ? 30 : hz;
    printf("classic textures=%d work=%d target=%d hz=%d wall=%d: %.4f fps, drawable=%.6f s\n", textures, workload, target, hz, CLASSIC_WALL_CLOCK, fps, classic_duration);
    CHECK(classic_enqueues - enqueues == (uint64_t)frames, "one renderer enqueue per present");
    CHECK(!mtl_link_active(), "the full loop uses no display link");
    CHECK(fps <= limit * 1.01, "the full classic loop respects its target after warmup");
    CHECK(fabs(classic_duration - 1.0 / limit) < 1e-8, "the real present passes the target duration to the renderer");
    // A shared virtual runner can oversleep under load. Only the controlled
    // clock establishes throughput; real OS waits check that the cap is not
    // exceeded and are not a performance benchmark for an iPhone.
    if (!CLASSIC_WALL_CLOCK && workload <= 2) CHECK(fps > limit * 0.85, "fast frames reach the configured cadence");
}
int main(void) { @autoreleasepool {
    setenv("DM_RT", "0", 1); setenv("DM_PRESENT_SNAP", "0", 1);
    setenv("DM_NVN_FRAMES", "0", 1); setenv("DM_FPS_HOLD", "off", 1);
    g_dm_present_link = 0; g_link = nil;
    CHECK(dm_fps_state == NULL, "no game frame-step controller is installed");
    CHECK(!dm_detclock_enabled(), "deterministic guest clock is disabled");
    for (int n = 2; n <= 4; n++) {
        for (int w = 0; w < (CLASSIC_WALL_CLOCK ? 1 : 5); w++) run_case(n, w, 30, 60);
        if (!CLASSIC_WALL_CLOCK) {
            run_case(n, 0, 30, 120);
            run_case(n, 0, 60, 60);
            run_case(n, 0, 0, 60);
        }
    }
    printf("classic result: %d checks, %d failed, %llu simulated OS sleeps\n", checks, failed, (unsigned long long)classic_sleeps);
    return failed != 0;
} }
