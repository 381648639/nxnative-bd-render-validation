#!/usr/bin/env python3
"""Instrument the development build only; shipped iOS sources are unaffected."""
from pathlib import Path
import sys

repo = Path(sys.argv[1])
script = repo / "scripts/build_ipa_from_nsp.py"
source = script.read_text()
old = "cmd = shlex.split(line); cmd[cmd.index('-o') + 1] = out"
assert source.count(old) == 1
source = source.replace(old, "cmd = shlex.split(line); cmd.insert(1, '-DDM_NVN_LEGACY_RENDERER_TEST=1'); cmd[cmd.index('-o') + 1] = out")
old = "    run(cmd, logs / 'mac_host_build.log', env=env, cwd=host)"
assert source.count(old) == 1
source = source.replace(old, "    (logs / 'mac_host_command.json').write_text(json.dumps([str(c) for c in cmd], indent=2) + '\\n')\n" + old)
start = source.index("def mac_run(")
end = source.index("\n\nMTL_ARCH_M", start)
section = source[start:end]
old = "if gfx == 'nvn' and g.table('shader_pairs.tsv').is_file():"
assert section.count(old) == 1
# The modern Metal 4 pipeline tool cannot prebuild a legacy host's pipelines.
# Legacy replay creates its own Metal 2/3 pipelines while running the game.
section = section.replace(old, "if False:  # Visual harness: legacy replay has no modern pipeline prebuild")
old = "    q = lambda v: shlex.quote(str(v))"
assert section.count(old) == 1
section = section.replace(old, """    (work / 'visual-runtime.json').write_text(json.dumps({
        'host': str(host), 'patched': str(patched), 'cwd': str(rd),
        'env': {k: str(v) for k, v in renv.items()},
        'renderer': 'legacy', 'compile_define': 'DM_NVN_LEGACY_RENDERER_TEST=1',
        'upstream': '1942eaa5e2a767809868994c27dfc5d692439fdc',
        'scope': 'Real guest game on macOS Metal; not an A15 device test'
    }, indent=2) + '\\n')
    q = lambda v: shlex.quote(str(v))""")
source = source[:start] + section + source[end:]
compile(source, str(script), "exec")
script.write_text(source)
print("Development host will compile legacy replay and export its real game runtime paths")
