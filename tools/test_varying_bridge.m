// Synthetic GPU check of ordinary values, non-finite values and varying limits.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <math.h>

int main(int argc, const char **argv) { @autoreleasepool {
    if (argc != 2) return 2;
    NSString *root = @(argv[1]);
    NSData *json = [NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:@"cases.json"]];
    NSArray *cases = [NSJSONSerialization JSONObjectWithData:json options:0 error:nil];
    id<MTLDevice> d = MTLCreateSystemDefaultDevice();
    if (!d) return 3;
    printf("Device: %s\n", d.name.UTF8String);
    id<MTLCommandQueue> q = [d newCommandQueue];
    MTLCompileOptions *options = [MTLCompileOptions new];
    options.languageVersion = MTLLanguageVersion3_0;
    options.mathMode = MTLMathModeRelaxed;
    unsigned failed = 0;
    for (NSDictionary *test in cases) {
        NSString *name = test[@"name"];
        unsigned count = [test[@"count"] unsignedIntValue];
        NSString *path = [root stringByAppendingPathComponent:test[@"source"]];
        NSString *src = [NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:nil];
        NSError *error = nil;
        id<MTLLibrary> lib = [d newLibraryWithSource:src options:options error:&error];
        if (!lib) { printf("%s COMPILE-FAIL %s\n", name.UTF8String, error.localizedDescription.UTF8String); failed++; continue; }
        MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
        pd.vertexFunction = [lib newFunctionWithName:@"main0"];
        pd.fragmentFunction = [lib newFunctionWithName:@"pixel"];
        pd.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA32Float;
        id<MTLRenderPipelineState> ps = [d newRenderPipelineStateWithDescriptor:pd error:&error];
        if (!ps) { printf("%s LINK-FAIL %s\n", name.UTF8String, error.localizedDescription.UTF8String); failed++; continue; }
        printf("%s LINK-PASS\n", name.UTF8String);
        if (count != 1) continue;
        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:8 height:8 mipmapped:NO];
        td.storageMode = MTLStorageModeShared; td.usage = MTLTextureUsageRenderTarget;
        id<MTLTexture> target = [d newTextureWithDescriptor:td];
        float values[][4] = {{.5,.25,1,.75}, {NAN,NAN,NAN,NAN}, {INFINITY,INFINITY,INFINITY,INFINITY},
                            {-INFINITY,-INFINITY,-INFINITY,-INFINITY}, {.5,NAN,INFINITY,1}};
        for (unsigned k = 0; k < 5; k++) {
            float data[3][4]; for (unsigned v=0;v<3;v++) memcpy(data[v],values[k],16);
            id<MTLBuffer> input = [d newBufferWithBytes:data length:sizeof data options:MTLResourceStorageModeShared];
            MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
            rp.colorAttachments[0].texture=target; rp.colorAttachments[0].loadAction=MTLLoadActionClear;
            rp.colorAttachments[0].storeAction=MTLStoreActionStore;
            id<MTLCommandBuffer> cb = [q commandBuffer];
            id<MTLRenderCommandEncoder> e = [cb renderCommandEncoderWithDescriptor:rp];
            [e setRenderPipelineState:ps]; [e setVertexBuffer:input offset:0 atIndex:0];
            [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            [e endEncoding]; [cb commit]; [cb waitUntilCompleted];
            float pixels[64][4]; [target getBytes:pixels bytesPerRow:128 fromRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0];
            unsigned wrong=0;
            for (unsigned p=0;p<64;p++) for (unsigned c=0;c<4;c++) {
                float want=values[k][c], got=pixels[p][c];
                if (![name isEqualToString:@"flat"] && !isfinite(want)) want=NAN;
                BOOL equal=isnan(want)?isnan(got):isinf(want)?got==want:fabsf(want-got)<1e-6f;
                if (!equal) wrong++;
            }
            if (cb.error || wrong) failed++;
            printf("%s case=%u wrong=%u sample=%g,%g,%g,%g gpu_error=%d\n",name.UTF8String,k,wrong,
                   pixels[20][0],pixels[20][1],pixels[20][2],pixels[20][3],cb.error!=nil);
        }
    }
    printf("Failed checks (including budget diagnostics): %u\n",failed);
    return 0;
} }
