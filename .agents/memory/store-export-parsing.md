---
name: Store export parsing
description: Defines the stable behavior for cleaning common Chipply store export CSV files.
---

The store-export parser removes a fixed set of standard unwanted columns and allows extra columns to be selected by the user for each job. It must preserve the remaining column order, row order, and cell strings exactly; numeric-looking values must not be parsed, normalized, or reformatted.

**Why:** Chipply exports contain unique source data alongside many unnecessary fields. Values such as ZIP codes, UPCs, IDs, currency strings, and formula-like text can be damaged by numeric coercion.

**How to apply:** Read and write CSV cells as strings, identify the fixed removals by exact header, and identify user-selected duplicate headers by zero-based column position rather than header name alone.