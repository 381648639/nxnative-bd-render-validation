#!/usr/bin/env python3
"""Export the same legacy companions as iOS packaging for macOS test libraries."""
import importlib.util
import json
from pathlib import Path
import re
import sys

source, runtime = map(Path, sys.argv[1:])
tools = source / 'dm/ios/tools'
chain = re.search(r'#define\s+DMSH_CHAIN\s+"([a-f0-9]+)"',
                  (source / 'dm/gfx/nvn/dmsh_chain.h').read_text()).group(1)
libraries = runtime / 'shaders' / ('b-' + chain)

def module(name):
    spec = importlib.util.spec_from_file_location(name, tools / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

results = {}
for name, folder in (
    ('export_nonpoint_sources', 'nonpoint-v1'),
    ('export_layered_sources', 'layered-v1'),
    ('export_sampler_limit_sources', 'sampler-limit-v1'),
    ('export_zero_image_sources', 'zero-image-v1'),
    ('export_legacy_atomics', 'atomic-v1'),
):
    records = module(name).export(libraries, libraries, libraries / folder, chain)
    results[folder] = len(records) if isinstance(records, dict) else records
    print('Prepared', folder, results[folder], flush=True)
results['guarded-index-v1'] = module('export_guarded_index_sources').export(
    libraries, libraries / 'guarded-index-v1', chain)
assert results['nonpoint-v1'] > 0
(runtime / 'legacy-resource-counts.json').write_text(json.dumps(results, indent=2) + '\n')
print('Legacy compatibility resources prepared for actual game inspection', flush=True)
