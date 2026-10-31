// Synthetic diagnostic: keep non-finite shader output separate from target conversion.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <math.h>
#include <stdint.h>

static NSString *source = @
"#include <metal_stdlib>\nusing namespace metal;\n"
"struct V { float4 p [[position]]; };\n"
"vertex V vs(uint i [[vertex_id]]) { float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)}; return V{float4(p[i],0,1)}; }\n"
"fragment float4 color(V v [[stage_in]], constant float4 *data [[buffer(0)]]) { return data[uint(v.p.x)]; }\n"
"fragment float4 sampled(V v [[stage_in]], texture2d<float> t [[texture(0)]]) { return t.read(uint2(v.p.xy)); }\n";

static id<MTLRenderPipelineState> pipeline(id<MTLDevice> device, id<MTLLibrary> library,
                                         MTLPixelFormat format, BOOL blend, NSString *fragment) {
    MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
    pd.vertexFunction = [library newFunctionWithName:@"vs"];
    pd.fragmentFunction = [library newFunctionWithName:fragment];
    MTLRenderPipelineColorAttachmentDescriptor *a = pd.colorAttachments[0];
    a.pixelFormat = format; a.blendingEnabled = blend;
    a.sourceRGBBlendFactor = a.sourceAlphaBlendFactor = MTLBlendFactorSourceAlpha;
    a.destinationRGBBlendFactor = a.destinationAlphaBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    NSError *error = nil;
    id<MTLRenderPipelineState> result = [device newRenderPipelineStateWithDescriptor:pd error:&error];
    if (!result) fprintf(stderr, "Pipeline format=%lu blend=%d: %s\n", (unsigned long)format, blend, error.localizedDescription.UTF8String);
    return result;
}

static id<MTLTexture> texture(id<MTLDevice> device, MTLPixelFormat format) {
    MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:format width:8 height:1 mipmapped:NO];
    d.storageMode = MTLStorageModeShared;
    d.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
    return [device newTextureWithDescriptor:d];
}

static id<MTLRenderCommandEncoder> render(id<MTLCommandBuffer> cb, id<MTLTexture> target,
                                         id<MTLRenderPipelineState> ps) {
    MTLRenderPassDescriptor *pd = [MTLRenderPassDescriptor renderPassDescriptor];
    pd.colorAttachments[0].texture = target;
    pd.colorAttachments[0].loadAction = MTLLoadActionClear;
    pd.colorAttachments[0].storeAction = MTLStoreActionStore;
    pd.colorAttachments[0].clearColor = MTLClearColorMake(.125,.25,.5,1);
    id<MTLRenderCommandEncoder> e = [cb renderCommandEncoderWithDescriptor:pd];
    [e setRenderPipelineState:ps];
    return e;
}

int main(void) { @autoreleasepool {
    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    if (!device) return 2;
    printf("Device: %s\n", device.name.UTF8String);
    MTLCompileOptions *options = [MTLCompileOptions new];
    options.languageVersion = MTLLanguageVersion3_0;
    options.fastMathEnabled = NO;
    NSError *error = nil;
    id<MTLLibrary> library = [device newLibraryWithSource:source options:options error:&error];
    if (!library) { fprintf(stderr,"%s\n",error.localizedDescription.UTF8String); return 3; }
    id<MTLCommandQueue> queue = [device newCommandQueue];
    float data[8][4] = {{.25,.5,1,1},{NAN,NAN,NAN,1},{-NAN,-NAN,-NAN,1},
        {INFINITY,INFINITY,INFINITY,1},{-INFINITY,-INFINITY,-INFINITY,1},
        {70000,70000,70000,1},{0,-0.0,.75,1},{0,0,0,NAN}};
    const char *names[] = {"finite","nan","negative-nan","positive-inf","negative-inf","overflow","zeros","nan-alpha"};
    id<MTLBuffer> input = [device newBufferWithBytes:data length:sizeof data options:MTLResourceStorageModeShared];
    MTLPixelFormat formats[] = {MTLPixelFormatRG11B10Float,MTLPixelFormatRGBA16Float,MTLPixelFormatRGBA32Float};
    const char *formatNames[] = {"RG11B10Float","RGBA16Float","RGBA32Float"};
    for (unsigned fi=0;fi<3;fi++) for (unsigned blend=0;blend<2;blend++) {
        id<MTLRenderPipelineState> ps = pipeline(device,library,formats[fi],blend,@"color");
        id<MTLRenderPipelineState> readPs = pipeline(device,library,MTLPixelFormatRGBA32Float,NO,@"sampled");
        if (!ps || !readPs) return 4;
        id<MTLTexture> target = texture(device,formats[fi]), sampled = texture(device,MTLPixelFormatRGBA32Float);
        if (!target || !sampled) return 5;
        id<MTLCommandBuffer> cb = [queue commandBuffer];
        id<MTLRenderCommandEncoder> e = render(cb,target,ps);
        [e setFragmentBuffer:input offset:0 atIndex:0];
        [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        [e endEncoding];
        e = render(cb,sampled,readPs);
        [e setFragmentTexture:target atIndex:0];
        [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        [e endEncoding]; [cb commit]; [cb waitUntilCompleted];
        if (cb.error) { fprintf(stderr,"%s\n",cb.error.localizedDescription.UTF8String); return 6; }
        uint8_t raw[128]={0}; float result[8][4];
        NSUInteger bpp=fi==0?4:fi==1?8:16;
        [target getBytes:raw bytesPerRow:8*bpp fromRegion:MTLRegionMake2D(0,0,8,1) mipmapLevel:0];
        [sampled getBytes:result bytesPerRow:sizeof result fromRegion:MTLRegionMake2D(0,0,8,1) mipmapLevel:0];
        for (unsigned i=0;i<8;i++) {
            printf("format=%s blend=%u input=%s raw=",formatNames[fi],blend,names[i]);
            for (unsigned j=0;j<bpp;j++) printf("%02x",raw[i*bpp+j]);
            printf(" read=%g,%g,%g,%g finite=%d\n",result[i][0],result[i][1],result[i][2],result[i][3],isfinite(result[i][0])!=0);
        }
    }
    return 0;
} }
