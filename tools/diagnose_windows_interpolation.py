"""Synthetic D3D11 interpolation diagnostic; no window or game files required."""
import ctypes as c
import math
import struct
from ctypes import wintypes as w

P = c.c_void_p
U = c.c_uint32
HRESULT = c.c_int32

def check(hr):
    if hr < 0:
        raise RuntimeError(f'D3D call failed: 0x{hr & 0xffffffff:08x}')

def method(obj, index, result, *args):
    table = c.cast(obj, c.POINTER(c.POINTER(P))).contents
    fn = c.WINFUNCTYPE(result, P, *args)(table[index])
    return lambda *values: fn(obj, *values)

def release(obj):
    if obj:
        method(obj, 2, U)()

class Sample(c.Structure):
    _fields_ = [('count', U), ('quality', U)]

class Texture(c.Structure):
    _fields_ = [('width', U), ('height', U), ('mips', U), ('array', U), ('format', U),
                ('sample', Sample), ('usage', U), ('bind', U), ('cpu', U), ('misc', U)]

class Buffer(c.Structure):
    _fields_ = [('size', U), ('usage', U), ('bind', U), ('cpu', U), ('misc', U), ('stride', U)]

class Initial(c.Structure):
    _fields_ = [('data', P), ('row', U), ('slice', U)]

class Mapped(c.Structure):
    _fields_ = [('data', P), ('row', U), ('depth', U)]

class Viewport(c.Structure):
    _fields_ = [(name, c.c_float) for name in ('x', 'y', 'width', 'height', 'near', 'far')]

dll = c.WinDLL('d3d11.dll')
compiler = c.WinDLL('d3dcompiler_47.dll')
create = dll.D3D11CreateDevice
create.argtypes = [P,U,P,U,c.POINTER(U),U,U,c.POINTER(P),c.POINTER(U),c.POINTER(P)]
create.restype = HRESULT
compile = compiler.D3DCompile
compile.argtypes = [P,c.c_size_t,c.c_char_p,P,P,c.c_char_p,c.c_char_p,U,U,c.POINTER(P),c.POINTER(P)]
compile.restype = HRESULT

def shader(text, entry, target):
    blob, error = P(), P()
    raw = text.encode()
    hr = compile(raw,len(raw),b'synthetic',None,None,entry.encode(),target.encode(),0x2004,0,c.byref(blob),c.byref(error))
    if error:
        ptr = method(error,3,P)()
        length = method(error,4,c.c_size_t)()
        message = c.string_at(ptr,length).decode(errors='replace')
        release(error)
        if hr < 0:
            raise RuntimeError(message)
    check(hr)
    return blob

device, context, level = P(), P(), U()
check(create(None,1,None,0,None,0,7,c.byref(device),c.byref(level),c.byref(context)))
print(f'Hardware D3D11 feature level: 0x{level.value:x}')
desc = Texture(8,8,1,1,2,Sample(1,0),0,0x20,0,0)
target, staging, rtv = P(), P(), P()
check(method(device,5,HRESULT,c.POINTER(Texture),P,c.POINTER(P))(c.byref(desc),None,c.byref(target)))
desc.usage, desc.bind, desc.cpu = 3,0,0x20000
check(method(device,5,HRESULT,c.POINTER(Texture),P,c.POINTER(P))(c.byref(desc),None,c.byref(staging)))
check(method(device,9,HRESULT,P,P,c.POINTER(P))(target,None,c.byref(rtv)))
method(context,33,None,U,c.POINTER(P),P)(1,c.byref(rtv),None)
method(context,24,None,U)(4)
viewport = Viewport(0,0,8,8,0,1)
method(context,44,None,U,c.POINTER(Viewport))(1,c.byref(viewport))

cases = [('finite',0x3f000000),('nan',0x7fc00000),('negative-nan',0xffc00000),
         ('positive-inf',0x7f800000),('negative-inf',0xff800000),('large',0x7effffff)]
try:
    for qualifier in ('linear','noperspective','nointerpolation'):
        text = '''cbuffer C : register(b0) { uint value; };
struct V { float4 p:SV_Position; QUAL float4 color:COLOR0; };
V vs(uint id:SV_VertexID) { float2 p[3]={float2(-1,-1),float2(-1,3),float2(3,-1)};
 V v; v.p=float4(p[id],0,1); v.color=asfloat(value); return v; }
float4 ps(V v):SV_Target { return float4(v.color.xyz,1); }
'''.replace('QUAL',qualifier)
        vs, ps = P(), P()
        for entry, target_name, index, output in [('vs','vs_5_0',12,vs),('ps','ps_5_0',15,ps)]:
            blob = shader(text,entry,target_name)
            ptr = method(blob,3,P)(); length = method(blob,4,c.c_size_t)()
            check(method(device,index,HRESULT,P,c.c_size_t,P,c.POINTER(P))(ptr,length,None,c.byref(output)))
            release(blob)
        method(context,11,None,P,P,U)(vs,None,0)
        method(context,9,None,P,P,U)(ps,None,0)
        for name,bits in cases:
            words = (U*4)(bits,0,0,0)
            initial = Initial(c.cast(words,P),0,0)
            constant = P()
            bd = Buffer(16,1,4,0,0,0)
            check(method(device,3,HRESULT,c.POINTER(Buffer),c.POINTER(Initial),c.POINTER(P))(c.byref(bd),c.byref(initial),c.byref(constant)))
            method(context,7,None,U,U,c.POINTER(P))(0,1,c.byref(constant))
            clear = (c.c_float*4)(.125,.25,.5,0)
            method(context,50,None,P,c.POINTER(c.c_float))(rtv,clear)
            method(context,13,None,U,U)(3,0)
            method(context,47,None,P,P)(staging,target)
            mapped = Mapped()
            check(method(context,14,HRESULT,P,U,U,U,c.POINTER(Mapped))(staging,0,1,0,c.byref(mapped)))
            result = struct.unpack('<4f',c.string_at(mapped.data,16))
            raw = c.string_at(mapped.data,16).hex()
            method(context,15,None,P,U)(staging,0)
            print(qualifier,name,'raw='+raw,'read='+repr(result),'finite='+str(math.isfinite(result[0])))
            release(constant)
        release(vs); release(ps)
finally:
    for obj in (rtv,staging,target,context,device): release(obj)
