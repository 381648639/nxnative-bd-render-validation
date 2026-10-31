"""Development probe for NVIDIA non-finite floating varying interpolation.

NVIDIA's linear interpolation produces NaN for non-finite inputs. The tested
Metal interpolator instead produces FLT_MAX. Carry finite flags separately so
the original non-finite result can be reconstructed after interpolation.
Flat and integer varyings do not use this path.
"""
import re

MEMBER = re.compile(r'^\s*(float|half)([234]?)\s+(\w+)\s+\[\[user\(locn(\d+)\)([^\]]*)\]\];', re.M)

def bridge(source, stage):
    name = 'main0_out' if stage == 'vs' else 'main0_in'
    body = re.search(r'\bstruct ' + name + r'\s*\{(.*?)\n\};', source, re.S)
    if not body:
        return source, []
    members = [m for m in MEMBER.finditer(body[1]) if 'flat' not in m[5]]
    if not members:
        return source, []
    declarations, statements, locations = [], [], []
    for m in members:
        kind, width, field, location, qualifiers = m.groups()
        ty, mask = kind + width, 'float' + width
        marker = 'dm_nonfinite_' + location
        declarations.append(f'    {mask} {marker} [[user(dm_nonfinite_locn{location}){qualifiers}]];')
        locations.append(int(location))
        if stage == 'vs':
            statements.append(f'    out.{marker} = select({mask}(0.0), {mask}(1.0), !isfinite(out.{field}));')
            statements.append(f'    out.{field} = select(out.{field}, {ty}(0.0), out.{marker} != {mask}(0.0));')
        else:
            statements.append(f'    in.{field} = select(in.{field}, {ty}(as_type<float>(0x7fc00000u)), in.{marker} != {mask}(0.0));')
    source = source[:body.end()-3] + '\n' + '\n'.join(declarations) + source[body.end()-3:]
    # Insert only in raster entry points returning this exact interface type.
    if stage == 'vs':
        entries = list(re.finditer(r'\bvertex\s+main0_out\s+\w+\s*\(', source))
    else:
        entries = list(re.finditer(r'\bfragment\s+\w+\s+\w+\(main0_in\s+in\s+\[\[stage_in\]\]', source))
    for entry in reversed(entries):
        start = source.index('{', entry.end())
        if stage == 'ps':
            source = source[:start+1] + '\n' + '\n'.join(statements) + source[start+1:]
            continue
        depth, end = 1, start + 1
        while depth:
            depth += (source[end] == '{') - (source[end] == '}')
            end += 1
        block = source[start:end]
        block, count = re.subn(r'\breturn out;', '\n'.join(statements) + '\n    return out;', block)
        if count != 1:
            raise ValueError('Raster entry must return its output once')
        source = source[:start] + block + source[end:]
    return source, locations
