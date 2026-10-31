#!/usr/bin/env python3
"""Join deterministic binary parts and verify their size and SHA-256."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("output", type=Path)
    ap.add_argument("pattern", type=Path, help="glob relative to the current directory")
    ap.add_argument("expected_size", type=int)
    ap.add_argument("expected_sha256")
    args = ap.parse_args()
    parts = sorted(args.pattern.parent.glob(args.pattern.name))
    if not parts:
        raise SystemExit(f"no parts matched {args.pattern}")
    expected_names = [f"{args.pattern.stem}{i:02d}{args.pattern.suffix}" for i in range(len(parts))]
    # The release naming convention is <stem>-00, <stem>-01, ...; reject gaps and extras.
    indexed = []
    for p in parts:
        try:
            index = int(p.name.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            raise SystemExit(f"part name must end in -NN: {p.name}")
        indexed.append((index, p))
    indexed.sort()
    if [i for i, _ in indexed] != list(range(len(indexed))):
        raise SystemExit(f"part indexes have a gap: {[i for i, _ in indexed]}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    with args.output.open("wb") as out:
        for _, part in indexed:
            with part.open("rb") as src:
                while chunk := src.read(16 * 1024 * 1024):
                    out.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
    actual = digest.hexdigest()
    if total != args.expected_size or actual.lower() != args.expected_sha256.lower():
        args.output.unlink(missing_ok=True)
        raise SystemExit(f"{args.output}: expected {args.expected_size} bytes/{args.expected_sha256}, got {total} bytes/{actual}")
    print(f"verified {args.output}: {total} bytes, {actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
