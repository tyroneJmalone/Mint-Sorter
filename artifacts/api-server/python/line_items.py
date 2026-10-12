"""Count product rows by table columns, never by quantity or PDF page count."""
import re

from slip_consolidation import footer_info, summary_lines, TOTAL, PAYMENT


def count_product_rows(page, words):
    for header in (w for w in words if w["text"] == "Style"):
        columns = {w["text"]: w for w in words if abs(w["top"] - header["top"]) < 3}
        if not all(k in columns for k in ("Product", "Size", "Color", "Qty", "Price")):
            continue
        right = columns.get("Vendor", columns["Product"])["x0"]
        quantities = [
            w for w in words if columns["Qty"]["x0"] - 2 <= w["x0"] < columns["Price"]["x0"] - 2
            and w["top"] > header["bottom"] + 2 and w["bottom"] < page.height - 40
            and re.fullmatch(r"\d+", w["text"])
        ]
        rows = set()
        for quantity in quantities:
            # Style and quantity share a baseline even when descriptions,
            # sizes or colors wrap. Separate rows with identical styles count.
            styles = [w for w in words if header["x0"] - 2 <= w["x0"] < right - 2
                      and abs(w["top"] - quantity["top"]) < 4]
            if not styles:
                return None
            rows.add(round(quantity["top"], 1))
        if rows:
            return len(rows)
    footer = footer_info(page)
    if footer and summary_lines(page, footer):
        return 0
    if footer and not page.images:
        lines = (page.crop((0, 0, page.width, footer["rect"][1] - 1)).extract_text() or "").splitlines()
        # Promotional credits are financial entries, not product rows. They
        # need not be consolidated in order to count this continuation as zero.
        if (any(line.startswith("Order Total:") for line in lines)
                and all(TOTAL.fullmatch(line) or PAYMENT.fullmatch(line)
                        or line == "Payment Method"
                        or re.fullmatch(r"Promo [A-Za-z0-9_-]+:\s*\$[\d,]+\.\d{2}", line)
                        for line in lines)):
            return 0
    return None


def prioritize_single_line_items(groups, enabled=False):
    if not enabled:
        return groups
    totals = []
    for group in groups:
        counts = [page.line_item_count for page in group]
        if any(count is None for count in counts) or sum(counts) < 1:
            pages = ", ".join(str(page.page_index + 1) for page in group)
            raise ValueError(
                f"Cannot reliably count product lines for order {group[0].order_number or 'unknown'} "
                f"(source pages {pages}). Uncheck 'Single-line-item orders first' to use the normal sort."
            )
        totals.append(sum(counts))
    return ([group for group, total in zip(groups, totals) if total == 1]
            + [group for group, total in zip(groups, totals) if total > 1])
