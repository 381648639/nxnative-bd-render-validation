// Private diagnostic: replay a captured vertex program and inspect its varyings.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <math.h>
#include <float.h>

static NSData *readFile(NSString *root, NSString *name) {
    return [NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:name]];
}
static id<MTLBuffer> buffer(id<MTLDevice> d, NSData *data) {
    return [d newBufferWithBytes:data.bytes length:data.length options:MTLResourceStorageModeShared];
}
static id<MTLLibrary> compile(id<MTLDevice> d, NSString *src, BOOL fast, FILE *log) {
    MTLCompileOptions *o=[MTLCompileOptions new]; o.languageVersion=MTLLanguageVersion3_0;
    o.fastMathEnabled=fast; o.preserveInvariance=YES;
    NSError *error=nil;
    id<MTLLibrary> lib=[d newLibraryWithSource:src options:o error:&error];
    if (!lib) fprintf(log,"Compile fast=%d: %s\n",fast,error.localizedDescription.UTF8String);
    return lib;
}

int main(int argc, const char **argv) { @autoreleasepool {
    if (argc!=3) return 2;
    NSString *root=@(argv[1]); FILE *log=fopen(argv[2],"w"); if (!log) return 3;
    NSDictionary *m=[NSJSONSerialization JSONObjectWithData:readFile(root,@"replay.json") options:0 error:nil];
    id<MTLDevice> d=MTLCreateSystemDefaultDevice(); id<MTLCommandQueue> q=[d newCommandQueue];
    fprintf(log,"Device: %s\n",d.name.UTF8String);
    NSString *vsrc=[[NSString alloc] initWithData:readFile(root,m[@"vs"]) encoding:NSUTF8StringEncoding];
    vsrc=[vsrc stringByReplacingOccurrencesOfString:@"[[point_size]]" withString:@"[[user(dm_unused_point_size)]]"];
    vsrc=[vsrc stringByAppendingString:@"\nstruct VisualInput { float4 uv [[user(locn0)]]; float4 color [[user(locn1)]]; };\nfragment float4 visual_color(VisualInput i [[stage_in]]) { return float4(i.color.xyz,1); }\nfragment float4 visual_uv(VisualInput i [[stage_in]]) { return float4(i.uv.xyz,1); }\n"];
    NSString *fsrc=[[NSString alloc] initWithData:readFile(root,m[@"fs"]) encoding:NSUTF8StringEncoding];
    id<MTLBuffer> vb=buffer(d,readFile(root,m[@"vb"])), ib=buffer(d,readFile(root,m[@"ib"]));
    id<MTLBuffer> vcb=buffer(d,readFile(root,m[@"vcb"])), fcb=buffer(d,readFile(root,m[@"fcb"]));
    uint32_t c1[64]={0x80000000}; id<MTLBuffer> bank=[d newBufferWithBytes:c1 length:sizeof c1 options:MTLResourceStorageModeShared];
    MTLSamplerDescriptor *sd=[MTLSamplerDescriptor new]; sd.minFilter=sd.magFilter=MTLSamplerMinMagFilterLinear;
    id<MTLSamplerState> sampler=[d newSamplerStateWithDescriptor:sd];
    MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:1 height:1 mipmapped:NO];
    td.storageMode=MTLStorageModeShared; td.usage=MTLTextureUsageShaderRead;
    id<MTLTexture> tex=[d newTextureWithDescriptor:td]; uint8_t pixel[4]={128,128,128,255};
    [tex replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:pixel bytesPerRow:4];
    for (unsigned vf=0;vf<3;vf++) {
        NSString *current=vf==2?[vsrc stringByReplacingOccurrencesOfString:@"= cos(" withString:@"= precise::cos("]:vsrc;
        id<MTLLibrary> vl=compile(d,current,vf==1,log); if (!vl) continue;
        id<MTLFunction> vs=[vl newFunctionWithName:@"main0_z"];
        id<MTLArgumentEncoder> va=[vs newArgumentEncoderWithBufferIndex:0];
        id<MTLBuffer> varg=[d newBufferWithLength:va.encodedLength options:MTLResourceStorageModeShared];
        [va setArgumentBuffer:varg offset:0]; [va setBuffer:vcb offset:0 atIndex:0]; [va setBuffer:bank offset:0 atIndex:1];
        for (unsigned mode=0;mode<4;mode++) {
            id<MTLLibrary> fl=mode<2?vl:compile(d,fsrc,mode==3,log); if (!fl) continue;
            NSString *fn=mode==0?@"visual_color":mode==1?@"visual_uv":@"main0";
            id<MTLFunction> fs=[fl newFunctionWithName:fn];
            id<MTLBuffer> farg=nil;
            if (mode>=2) {
                id<MTLArgumentEncoder> fa=[fs newArgumentEncoderWithBufferIndex:0];
                farg=[d newBufferWithLength:fa.encodedLength options:MTLResourceStorageModeShared];
                [fa setArgumentBuffer:farg offset:0]; [fa setBuffer:fcb offset:0 atIndex:0];
                [fa setTexture:tex atIndex:1]; [fa setSamplerState:sampler atIndex:2];
            }
            MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new]; pd.vertexFunction=vs; pd.fragmentFunction=fs;
            pd.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA32Float;
            MTLVertexDescriptor *vd=[MTLVertexDescriptor vertexDescriptor];
            MTLVertexFormat fmt[3]={MTLVertexFormatFloat3,MTLVertexFormatUChar4Normalized,MTLVertexFormatHalf2};
            NSUInteger off[3]={0,28,32};
            for (unsigned i=0;i<3;i++) { vd.attributes[i].format=fmt[i]; vd.attributes[i].offset=off[i]; vd.attributes[i].bufferIndex=1; }
            vd.layouts[1].stride=44; pd.vertexDescriptor=vd;
            NSError *error=nil; id<MTLRenderPipelineState> ps=[d newRenderPipelineStateWithDescriptor:pd error:&error];
            if (!ps) { fprintf(log,"Pipeline vf=%u mode=%u: %s\n",vf,mode,error.localizedDescription.UTF8String); continue; }
            td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:1280 height:720 mipmapped:NO];
            td.storageMode=MTLStorageModeShared; td.usage=MTLTextureUsageRenderTarget;
            id<MTLTexture> target=[d newTextureWithDescriptor:td];
            MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor renderPassDescriptor]; rp.colorAttachments[0].texture=target;
            rp.colorAttachments[0].loadAction=MTLLoadActionClear; rp.colorAttachments[0].storeAction=MTLStoreActionStore;
            id<MTLCommandBuffer> cb=[q commandBuffer]; id<MTLRenderCommandEncoder> e=[cb renderCommandEncoderWithDescriptor:rp];
            [e setRenderPipelineState:ps]; [e setCullMode:MTLCullModeNone];
            [e setVertexBuffer:varg offset:0 atIndex:0]; [e setVertexBuffer:vb offset:0 atIndex:1];
            [e useResource:vcb usage:MTLResourceUsageRead]; [e useResource:bank usage:MTLResourceUsageRead];
            if (farg) { [e setFragmentBuffer:farg offset:0 atIndex:0]; [e useResource:fcb usage:MTLResourceUsageRead]; [e useResource:tex usage:MTLResourceUsageRead]; }
            [e drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:54 indexType:MTLIndexTypeUInt16 indexBuffer:ib indexBufferOffset:0];
            [e endEncoding]; [cb commit]; [cb waitUntilCompleted];
            if (cb.error) { fprintf(log,"GPU vf=%u mode=%u: %s\n",vf,mode,cb.error.localizedDescription.UTF8String); continue; }
            float *pixels=malloc(1280*720*16); [target getBytes:pixels bytesPerRow:1280*16 fromRegion:MTLRegionMake2D(0,0,1280,720) mipmapLevel:0];
            unsigned drawn=0,nan=0,inf=0; float min=FLT_MAX,max=-FLT_MAX;
            for (unsigned i=0;i<1280*720;i++) if (pixels[4*i+3]!=0) {
                drawn++; for (unsigned c=0;c<3;c++) { float x=pixels[4*i+c]; if (isnan(x)) nan++; else if (isinf(x)) inf++; else { min=fminf(min,x); max=fmaxf(max,x); } }
            }
            float *p=pixels+4*(450*1280+640);
            fprintf(log,"vf=%u mode=%u drawn=%u nan_channels=%u inf_channels=%u finite_min=%g finite_max=%g at640450=%g,%g,%g,%g\n",vf,mode,drawn,nan,inf,min,max,p[0],p[1],p[2],p[3]);
            free(pixels); fflush(log);
        }
    }
    fclose(log); return 0;
} }
