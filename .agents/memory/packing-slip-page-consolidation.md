---
name: Packing-slip page consolidation
description: Safe rules for optionally converting multi-page packing slips into fewer output pages.
---

Only remove a continuation page when it contains totals/payment information but no product rows. Move a compact Shipping, Handling, Tax, Order Total, and non-zero Payment Method summary onto the preceding page, then update visible and underlying page numbering.

**Why:** Packing-slip exports can look visually empty while still containing continued product rows. Text-line matching can miss those rows because PDF columns may be exposed as separate text blocks. Removing pages based only on sparse text or a page number risks deleting ordered items.

**How to apply:** Detect product rows using their positioned Sort # and Style # blocks beneath the Product Name table header. Preserve any page with a real product row. Consolidate only totals-only pages, verify the final order count and page count, and visually inspect collapsed, two-page, and three-page examples before delivery.