// Exercise the actual legacy clear replay before and during diagnostic frames.
// A null clear is a CPU no-op and needs neither a GPU nor game assets.
#define DM_NVN_LEGACY_RENDERER_TEST 1
#include "../nvn/nvn_mtl.m"
#include "../../host/hle.h"

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

int main(int argc, char **argv) { @autoreleasepool {
    const char *mode = argc > 1 ? argv[1] : "periodic";
    unsetenv("DM_NVN_PASSDUMP");
    unsetenv("DM_NVN_PASSDUMP_EVERY");
    unsetenv("DM_NVN_PASSDUMP_ALL");
    unsetenv("DM_NVN_SHDUMP");
    if (!strcmp(mode, "periodic")) {
        setenv("DM_NVN_PASSDUMP_EVERY", "300", 1);
        setenv("DM_NVN_PASSDUMP_ALL", "1", 1);
    } else if (!strcmp(mode, "fixed")) {
        setenv("DM_NVN_PASSDUMP", "1", 1);
    } else if (strcmp(mode, "off")) {
        fprintf(stderr, "Unknown test mode\n"); return 2;
    }
    const unsigned long frames[] = {0, 1, 2, 299, 300, 301};
    p_clear_tex clear = {0};
    for (unsigned i = 0; i < sizeof frames / sizeof *frames; i++) {
        unsigned long frame = frames[i];
        atomic_store(&g_cur_frame, frame);
        int expected = !strcmp(mode, "periodic") ? frame % 300 == 0 : !strcmp(mode, "fixed") && frame == 1;
        CHECK(passdump() == expected, "the intended diagnostic frames are selected");
        fprintf(stderr, "ABOUT_TO_CLEAR_NULL frame=%lu mode=%s\n", frame, mode);
        clear_tex(&clear);
        CHECK(!g_dev && !g_cb && !g_enc, "null clears return without creating GPU state");
    }
    printf("legacy null diagnostics (%s): %d checks, %d failures\n", mode, checks, failures);
    return failures != 0;
} }
