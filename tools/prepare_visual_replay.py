"""Select matching captured uniforms, geometry and programs in private evidence."""
import json
from pathlib import Path
import re
import sys
import zipfile

archive, output = map(Path, sys.argv[1:])
output.mkdir(parents=True, exist_ok=True)
vs, fs = 'b8b1925cc16f8247_b', 'bf70b833d622277c_b'
with zipfile.ZipFile(archive) as z:
    names = z.namelist()
    vcb = sorted(n for n in names if n.startswith('uniforms/GPU_') and vs in n)[0]
    prefix = re.search(r'GPU_(F\d+_p\d+)_', vcb).group(1)
    fcb = next(n for n in names if n.startswith('uniforms/GPU_' + prefix + '_') and fs in n)
    vb = next(n for n in names if n.startswith('uniforms/' + prefix + '_vb0_'))
    ib = next(n for n in names if re.match('uniforms/' + prefix + r'_ib\d*_', n))
    chosen = dict(vs='shader-sources/' + vs + '.metal', fs='shader-sources/' + fs + '.metal',
                  vcb=vcb, fcb=fcb, vb=vb, ib=ib)
    for name in chosen.values():
        target = output / name
        assert target.resolve().is_relative_to(output.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(z.read(name))
    (output / 'replay.json').write_text(json.dumps(chosen))
print('Prepared private captured program inputs')
