"""CLI wrapper for the processor module.

Usage:
    python3 processor_cli.py <preset> <packing_slips_path> <out_dir> [label_pdf ...]

<packing_slips_path> may be an empty string when not required by the preset.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow importing sibling module
sys.path.insert(0, str(Path(__file__).parent))
from processor import process_batch  # type: ignore

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: processor_cli.py <preset> <packing_path> <out_dir> [labels...]", file=sys.stderr)
        sys.exit(1)

    preset = sys.argv[1]
    packing_path = sys.argv[2]
    out_dir = Path(sys.argv[3])
    label_paths = [Path(p) for p in sys.argv[4:]]

    packing = Path(packing_path) if packing_path else Path("")

    process_batch(packing, label_paths, out_dir, preset)
