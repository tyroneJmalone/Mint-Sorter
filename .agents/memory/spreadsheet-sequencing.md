---
name: Spreadsheet sequencing
description: Defines the authoritative matching hierarchy for spreadsheet-guided PDF sorting.
---

The spreadsheet order-number column is the only required and permitted key for arranging packing slips. Do not use spreadsheet names as a fallback. After the slips are reordered, match and arrange shipping labels to that resulting slip sequence.

**Why:** The spreadsheet is intended only as the authoritative order-number sequence; label ordering is downstream from the packing slips rather than directly driven by spreadsheet identity fields.

**How to apply:** Keep the spreadsheet UI and backend validation centered on sheet, header row, and order-number column. Report unmatched or duplicate order numbers explicitly, preserve unmatched slips according to the product’s established no-data-loss behavior, and run label matching only after slip ordering is complete.