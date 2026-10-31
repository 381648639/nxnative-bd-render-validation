"""Generate synthetic programs for interpolation and interface-budget checks."""
import json
import os
from pathlib import Path
import sys
if os.environ.get('DM_NONFINITE_TOOLS'):
    sys.path.insert(0, os.environ['DM_NONFINITE_TOOLS'])
    from dmsh_nonfinite import bridge
else:
    from visual_nonfinite_varyings import bridge

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
cases = []
for name, count, qualifier in [('smooth', 1, ''), ('noperspective', 1, ', center_no_perspective'),
                               ('flat', 1, ', flat'), ('budget60', 15, ''), ('budget64', 16, '')]:
    fields = '\n'.join(f'    float4 v{i} [[user(locn{i}){qualifier}]];' for i in range(count))
    writes = '\n'.join(f'    out.v{i} = data[id * {count} + {i}];' for i in range(count))
    total = ' + '.join(f'in.v{i}' for i in range(count))
    source = f'''#include <metal_stdlib>
using namespace metal;
struct main0_out
{{
    float4 position [[position]];
{fields}
}};
struct main0_in
{{
{fields}
}};
vertex main0_out main0(uint id [[vertex_id]], constant float4 *data [[buffer(0)]])
{{
    float2 p[3] = {{float2(-1,-1), float2(3,-1), float2(-1,3)}};
    main0_out out = {{}};
    out.position = float4(p[id], 0, 1);
{writes}
    return out;
}}
fragment float4 pixel(main0_in in [[stage_in]])
{{
    return {total};
}}
'''
    source, _ = bridge(source, 'vs')
    source, _ = bridge(source, 'ps')
    path = root / (name + '.metal')
    path.write_text(source)
    cases.append(dict(name=name, count=count, source=path.name))
(root / 'cases.json').write_text(json.dumps(cases))
