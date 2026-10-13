---
name: Packing-slip layout variation
description: Lessons from incorrect sorting of a pickup-store export.
---

Do not assume the first text line is a recipient or that every packing-slip table has Sort #, Vendor, or prices. Read positioned product cells and explicit recipient fields where available.

**Why:** A pickup-store PDF began with the store title, omitted Sort #, and wrapped color values. Flat-text regexes assigned the store title to every recipient, matched addresses as styles, and missed most sizes and colors. Both the named and custom sorts consequently appeared to sort unpredictably.

**How to apply:** Verify actual extracted keys against the visual table when investigating sorting. Test both vendor-present and vendor-absent layouts. Keep each order whole, consistently use its first item's product fields, and compare equivalent preset/custom sorts plus page preservation. Expose the extracted fields in the downloadable report rather than treating a successful PDF write as proof of correct sorting.

Delivery Method is also a positioned column, not the text after its label in flattened reading order. Adjacent dates and billing names can be interleaved into that value.

**Why:** A custom delivery→style→color→size sort appeared to ignore style/color because the first key actually included a different date and customer name for almost every order. Non-empty fields are not proof of valid extraction.

**How to apply:** Check the distinct values of the leading sort key when later keys seem ineffective. A preferred style alone also cannot select a particular color when an order contains several rows of that same style; keep those two decisions separate.

Treat an unstructured recipient fallback as uncertain, even when it contains text.

**Why:** A nonempty store title can masquerade as a recipient; absence-only checks would falsely reassure users. Conservative warnings are preferable to declaring an unreliable name sort successful.

**How to apply:** Preserve the existing order and pages while asking users to verify uncertain recipient-based sorting. If adding support for non-comma name formats, establish reliable recipient provenance rather than accepting arbitrary header text.
