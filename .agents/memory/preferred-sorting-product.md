---
name: Preferred sorting product
description: Agreed matching and fallback behavior for multi-product order sorting.
---

The user approved an optional preferred style plus optional color. Use the first matching product anywhere in the complete order for style, color, and size sort values. If no product matches both provided values, retain the first-product rule; do not fall back to a different color of the preferred style.

**Why:** Multiple orders contained 5000 / Royal after another product, sometimes after a different color of style 5000. Style alone cannot select the intended color.

**How to apply:** Keep the selected sort-field hierarchy unchanged, including delivery method. Never split the order or rearrange its printed rows. Single-line priority, if enabled, remains an outer grouping and can therefore produce separate preferred-product blocks. Without a preference, preserve the established first-product behavior.
