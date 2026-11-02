"""Read final-present UI using CPU OCR and independently sampled menu borders."""
import csv
import io
import json
import os
from pathlib import Path
import subprocess


def observe(reader, path):
    data = json.loads(subprocess.check_output([str(reader), str(path)], timeout=30))
    model = Path(os.environ["BD_OCR_DATA"])
    raw = subprocess.check_output(["tesseract", str(path), "stdout", "--tessdata-dir", str(model),
                                   "-l", "chi_sim+eng", "--psm", "11", "tsv"],
                                  stderr=subprocess.DEVNULL, timeout=45).decode()
    groups = {}
    words = []
    for row in csv.DictReader(io.StringIO(raw), delimiter="\t"):
        if row["level"] != "5" or not row["text"].strip():
            continue
        left, top, width, height = (int(row[k]) for k in ("left", "top", "width", "height"))
        word = {"text": row["text"], "x": (left + width / 2) / 1920,
                "y": (top + height / 2) / 1080, "confidence": float(row["conf"]) / 100}
        words.append(word)
        key = tuple(row[k] for k in ("page_num", "block_num", "par_num", "line_num"))
        groups.setdefault(key, []).append(word)
    lines = []
    for group in groups.values():
        lines.append({"text": " ".join(v["text"] for v in group),
                      "x": sum(v["x"] for v in group) / len(group),
                      "y": sum(v["y"] for v in group) / len(group)})
    data.update(lines=lines, words=words)
    data["hp_text"] = subprocess.check_output(
        ["tesseract", str(path) + ".hp.png", "stdout", "--tessdata-dir", str(model),
         "-l", "eng", "--psm", "7", "-c", "tessedit_char_whitelist=0123456789/"],
        stderr=subprocess.DEVNULL, timeout=30).decode().strip()
    return data
