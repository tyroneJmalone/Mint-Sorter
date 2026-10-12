"""CLI wrapper for the processor module.

Usage:
    python3 processor_cli.py <preset> <packing_slips_path> <out_dir> [--sort-fields '[...]'] [label_pdf ...]

<packing_slips_path> may be an empty string when not required by the preset.
--sort-fields accepts a JSON array of field names used by the custom_sort preset.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from processor import process_batch  # type: ignore

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mint Sorter & Parser CLI")
    parser.add_argument("preset", help="Processing preset name")
    parser.add_argument("packing_path", help="Path to packing slips PDF (empty string if not needed)")
    parser.add_argument("out_dir", help="Output directory")
    parser.add_argument("--sort-fields", default="[]", help="JSON array of sort field names for custom_sort preset")
    parser.add_argument("--single-line-item-first", action="store_true")
    parser.add_argument("--spreadsheet-path", default="", help="Path to CSV/XLSX sequence file")
    parser.add_argument("--spreadsheet-name", default="", help="Original spreadsheet filename")
    parser.add_argument("--spreadsheet-mapping", default="{}", help="JSON spreadsheet column mapping")
    parser.add_argument("--store-export-path", default="", help="Path to store export CSV")
    parser.add_argument("--remove-column-indexes", default="[]", help="JSON array of extra CSV column indexes to remove")
    parser.add_argument("labels", nargs="*", help="Paths to shipping label PDFs")
    args = parser.parse_intermixed_args()

    sort_fields: list[str] = json.loads(args.sort_fields) if args.sort_fields else []
    spreadsheet_mapping: dict = json.loads(args.spreadsheet_mapping) if args.spreadsheet_mapping else {}
    remove_column_indexes: list[int] = json.loads(args.remove_column_indexes) if args.remove_column_indexes else []
    packing = Path(args.packing_path) if args.packing_path else Path("")
    label_paths = [Path(p) for p in args.labels]

    process_batch(packing, label_paths, Path(args.out_dir), args.preset,
                  sort_fields=sort_fields if sort_fields else None,
                  single_line_item_first=args.single_line_item_first,
                  spreadsheet_path=Path(args.spreadsheet_path) if args.spreadsheet_path else None,
                  spreadsheet_name=args.spreadsheet_name,
                  spreadsheet_mapping=spreadsheet_mapping if spreadsheet_mapping else None,
                  store_export_path=Path(args.store_export_path) if args.store_export_path else None,
                  remove_column_indexes=remove_column_indexes)
