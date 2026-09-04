from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from processor import inspect_spreadsheet  # type: ignore


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: spreadsheet_inspect_cli.py <path> <original_filename>")
    print(json.dumps(inspect_spreadsheet(sys.argv[1], sys.argv[2])))