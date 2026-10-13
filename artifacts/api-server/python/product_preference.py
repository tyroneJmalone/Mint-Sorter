"""Select a representative product without moving or splitting printed items."""
import re

SUPPORTED_PRESETS = {"sort_slips", "sort_slips_name", "sort_slips_custom",
                     "sort_both", "sort_labels", "custom_sort"}


def product_rows(page, words):
    header = next((w for w in words if w["text"] == "Style"), None)
    if not header:
        return []
    columns = {w["text"]: w for w in words if abs(w["top"] - header["top"]) < 3}
    if not all(k in columns for k in ("Product", "Size", "Color", "Qty", "Price")):
        return []
    style_right = columns.get("Vendor", columns["Product"])["x0"]
    quantities = sorted([w for w in words
                         if columns["Qty"]["x0"] - 2 <= w["x0"] < columns["Price"]["x0"] - 2
                         and header["bottom"] + 2 < w["top"] < page.height - 40
                         and re.fullmatch(r"\d+", w["text"])], key=lambda w: w["top"])
    result = []
    for quantity in quantities:
        anchors = [w for w in words if header["x0"] - 2 <= w["x0"] < style_right - 2
                   and abs(w["top"] - quantity["top"]) < 4]
        if not anchors:
            continue
        anchor = min(anchors, key=lambda w: w["x0"])
        cells = [r for r in page.rects if r["x0"] <= anchor["x0"] < r["x1"]
                 and r["top"] <= anchor["top"] and r["bottom"] >= anchor["bottom"]
                 and r["height"] > 10 and r["width"] > 10]
        cell = min(cells, key=lambda r: r["height"]) if cells else None
        top, bottom = ((cell["top"], cell["bottom"]) if cell else
                       (anchor["top"] - 2, anchor["bottom"] + 2))

        def text(left, right):
            selected = [w for w in words if left - 2 <= w["x0"] < right - 2
                        and top <= (w["top"] + w["bottom"]) / 2 < bottom]
            return " ".join(w["text"] for w in sorted(selected, key=lambda w: (round(w["top"], 1), w["x0"])))

        style = text(header["x0"], style_right)
        color = text(columns["Color"]["x0"], columns["Qty"]["x0"])
        color = re.sub(r"\s+-\s*" + re.escape(style) + r"$", "", color).strip()
        result.append(dict(style=style, color=color,
                           size=text(columns["Size"]["x0"], columns["Color"]["x0"])))
    return result


def normalized(value):
    return " ".join(value.split()).casefold()


def apply_product_preference(groups, style, color=""):
    report = []
    for group in groups:
        first = group[0]
        match = next(((page, i, row) for page in group
                      for i, row in enumerate(page.product_rows, 1)
                      if normalized(row["style"]) == normalized(style)
                      and (not color or normalized(row["color"]) == normalized(color))), None)
        if match:
            page, index, row = match
            first.style, first.color, first.size = row["style"], row["color"], row["size"]
        report.append(dict(
            order_number=first.order_number, preferred_style=style, preferred_color=color,
            selection="preferred match" if match else "first product (no match)",
            source_page=match[0].page_index + 1 if match else first.page_index + 1,
            product_row=match[1] if match else 1,
            style=first.style, color=first.color, size=first.size,
        ))
    return report
