#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
#import <AppKit/AppKit.h>
#include <math.h>

// Development-only observation of the final presented PNG. Never linked into
// the game host, and never reads or changes guest memory.
static int red(NSBitmapImageRep *bitmap, int x, int y) {
    NSColor *c = [[bitmap colorAtX:x y:y] colorUsingColorSpace:NSColorSpace.deviceRGBColorSpace];
    return c.redComponent > .80 && c.greenComponent < .72 &&
           c.blueComponent < .65 && c.redComponent - c.greenComponent > .18;
}
static int bracket(NSBitmapImageRep *bitmap, int x, int y) {
    int score = 0;
    for (int dy = 0; dy < 20; ++dy) {
        NSColor *c = [[bitmap colorAtX:x y:y + dy] colorUsingColorSpace:NSColorSpace.deviceRGBColorSpace];
        if (c.redComponent > .85 && fabs(c.redComponent - c.greenComponent) < .025 &&
            fabs(c.redComponent - c.blueComponent) < .025 &&
            red(bitmap, x + 9, y + dy)) score++;
    }
    return score;
}
int main(int argc, const char **argv) { @autoreleasepool {
    if (argc != 2) return 2;
    NSURL *url = [NSURL fileURLWithPath:@(argv[1])];
    NSError *error = nil;
    VNRecognizeTextRequest *request = [VNRecognizeTextRequest new];
    request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
    request.recognitionLanguages = @[@"zh-Hans", @"en-US"];
    request.usesLanguageCorrection = NO;
    VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithURL:url options:@{}];
    if (![handler performRequests:@[request] error:&error]) {
        fprintf(stderr, "Frame OCR failed: %s\n", error.localizedDescription.UTF8String);
        return 1;
    }
    NSMutableArray *lines = [NSMutableArray new];
    for (VNRecognizedTextObservation *observation in request.results) {
        VNRecognizedText *candidate = [observation topCandidates:1].firstObject;
        CGRect b = observation.boundingBox;
        [lines addObject:@{@"text":candidate.string ?: @"", @"x":@(CGRectGetMidX(b)),
                          @"y":@(1 - CGRectGetMidY(b)), @"confidence":@(candidate.confidence)}];
    }
    NSBitmapImageRep *bitmap = [NSBitmapImageRep imageRepWithData:[NSData dataWithContentsOfURL:url]];
    if (bitmap.pixelsWide != 1920 || bitmap.pixelsHigh != 1080) return 3;
    NSMutableArray *moves = [NSMutableArray new], *party = [NSMutableArray new], *main = [NSMutableArray new];
    for (int i = 0; i < 4; ++i) {
        [moves addObject:@(bracket(bitmap, 1286, 615 + (int)round(i * 116.7)))];
        [main addObject:@(bracket(bitmap, 1527, 615 + (int)round(i * 116.7)))];
    }
    for (int i = 0; i < 6; ++i) {
        int score = 0;
        for (int dy = 0; dy < 30; ++dy) score += red(bitmap, 64, 110 + 146 * i + dy);
        [party addObject:@(score)];
    }
    NSData *data = [NSJSONSerialization dataWithJSONObject:
        @{@"lines":lines, @"moves":moves, @"party":party, @"main":main} options:0 error:&error];
    if (!data) return 4;
    fwrite(data.bytes, 1, data.length, stdout);
    putchar('\n');
    return 0;
} }
