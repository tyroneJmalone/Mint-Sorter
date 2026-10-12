---
name: Packing-slip page consolidation
description: Safety rules for converting multi-page packing slips into fewer output pages.
---

Only remove a continuation page when it contains totals/payment information but no product rows. Move a compact Shipping, Handling, Tax, Order Total, and non-zero Payment Method summary onto the preceding page, then update visible and underlying page numbering.

**Why:** Packing-slip exports can look visually empty while still containing continued product rows. Text-line matching can miss those rows because PDF columns may be exposed as separate text blocks. Removing pages based only on sparse text or a page number risks deleting ordered items.

**How to apply:** Preserve any page with a real product row. Do not assume Sort # exists on every export. Require positive identification of all continuation-page content as totals/payment data, enough measured space on the preceding page, and consistent order/page numbering. Keep unfamiliar layouts unchanged rather than guessing. Verify order counts, product content, and page counts, and visually inspect collapsed, two-page, and three-page examples before delivery.