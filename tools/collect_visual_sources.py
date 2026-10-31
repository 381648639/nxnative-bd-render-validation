#!/usr/bin/env python3
"""Copy shaders referenced by private diagnostic logs into private evidence."""
from pathlib import Path
import re
import shutil

def collect(runtime, evidence):
    runtime, evidence = Path(runtime), Path(evidence)
    log = evidence / 'game.log'
    if not log.is_file():
        return 0
    keys = set(re.findall(r'(?:key=|vs=|fs=)([a-f0-9]{16}_b)', log.read_text(errors='replace')))
    target = evidence / 'shader-sources'
    target.mkdir(exist_ok=True)
    count = 0
    for chain in (runtime / 'shaders').glob('b-*'):
        for key in sorted(keys):
            for suffix in ('.json', '.metal'):
                original = chain / (key + suffix)
                if original.is_file():
                    shutil.copyfile(original, target / original.name)
                    count += 1
    return count
