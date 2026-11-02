"""Check the observer against private, previously inspected final-present frames."""
import json
from pathlib import Path
import subprocess
import sys
from observe_game_frame import observe

folder = Path(sys.argv[1])
reader = folder / "reader"
subprocess.run(["clang", "-O2", "-fobjc-arc", str(Path(__file__).with_name("read_game_frame.m")),
                "-framework", "Foundation", "-framework", "AppKit", "-framework", "CoreGraphics",
                "-o", str(reader)], check=True)
cases = [
    ("power-up-punch-selected.png", "moves", 0),
    ("power-up-punch-selected-02.png", "moves", 3),
    ("chimchar-select.png", "party", 4),
    ("chimchar-field.png", "main", 0),
]
records = {}
for name, key, expected in cases:
    record = observe(reader, folder / name)
    scores = record[key]
    assert max(scores) >= 8 and max(range(len(scores)), key=scores.__getitem__) == expected, (name, key, scores)
    assert record["lines"], "OCR returned no observations"
    if name == "chimchar-field.png":
        assert record["hp_text"].replace(" ", "") == "34/34", "Active HP crop was not read accurately"
    records[name] = record
(folder / "reader-check.json").write_text(json.dumps(records, indent=2) + "\n")
print("Final-frame observer: four inspected selection fixtures passed")
