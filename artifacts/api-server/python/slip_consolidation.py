"""Conservative, lossless-product consolidation of totals-only trailing pages."""
from __future__ import annotations

import io
import json
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


FOOTER = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)\s+Order\s*#\s*(\d+)")
AMOUNT = r"\$[\d,]+\.\d{2}"
TOTAL = re.compile(rf"(Item Total|Shipping|Handling|Tax|Order Total):\s*({AMOUNT})")
PAYMENT = re.compile(
    rf"(E-certificate|Credit Card|Link|Cash|Check|PayPal|Gift Card|ACH|Apple Pay|Google Pay):\s*({AMOUNT})",
    re.IGNORECASE,
)


def footer_info(page):
    words = [w for w in page.extract_words() if w["top"] > page.height * .9]
    start = next((w for w in words if w["text"] == "Page"), None)
    if not start:
        return None
    words = [w for w in words if abs(w["top"] - start["top"]) < 2]
    match = FOOTER.fullmatch(" ".join(w["text"] for w in words))
    if not match or page.rotation or tuple(page.mediabox[:2]) != (0, 0):
        return None
    return {
        "number": int(match[1]), "count": int(match[2]), "order": match[3],
        "rect": [min(w["x0"] for w in words) - 1, min(w["top"] for w in words) - 1,
                 max(w["x1"] for w in words) + 1, max(w["bottom"] for w in words) + 1],
    }


def summary_lines(page, footer):
    """Every body line must be a recognized total/payment, not just 'sparse'."""
    if page.images or page.annots:
        return None
    body = page.crop((0, 0, page.width, footer["rect"][1] - 1))
    lines = (body.extract_text(x_tolerance=1, y_tolerance=3) or "").splitlines()
    totals, payments = {}, []
    for line in lines:
        line = line.strip()
        if not line or line == "Payment Method":
            continue
        if re.fullmatch(r"(?:Sort # )?Style # (?:Vendor )?Product Name Size Color Qty Price Extended", line):
            # Empty table headers can repeat above totals; actual product
            # cells below them still fail the strict full-line checks.
            continue
        total, payment = TOTAL.fullmatch(line), PAYMENT.fullmatch(line)
        if total:
            if total[1] in totals:
                return None
            totals[total[1]] = total[2]
        elif payment:
            if float(payment[2].replace("$", "").replace(",", "")) != 0:
                payments.append(f"{payment[1]}: {payment[2]}")
        else:
            # This also rejects product headers, positioned product cells,
            # instructions, addresses, and unrecognized payment descriptions.
            return None
    if not all(k in totals for k in ("Shipping", "Handling", "Tax", "Order Total")):
        return None
    result = []
    if "Item Total" in totals:
        result.append("Item Total: " + totals["Item Total"])
    result.append("    ".join(f"{k}: {totals[k]}" for k in ("Shipping", "Handling", "Tax")))
    result.append("Order Total: " + totals["Order Total"])
    if payments:
        result[-1] += "    Payment: " + "; ".join(payments)
    # Courier width is exactly .6em; wrapping guarantees the summary fits.
    max_chars = int((page.width - 36) / (8.5 * .6))
    return [part for line in result for part in textwrap.wrap(line, max_chars)]


def body_bottom(page, footer):
    limit = footer["rect"][1] - 2
    objects = page.chars + page.images + page.rects + page.curves + page.lines
    bottoms = []
    for obj in objects:
        if obj["top"] >= limit:
            continue
        # Page-sized backgrounds do not consume writing space.
        if obj in page.rects and obj["height"] >= page.height * .95:
            continue
        bottoms.append(obj["bottom"])
    return max(bottoms, default=page.height)


def text_overlay(width, height, texts):
    writer = PdfWriter()
    page = writer.add_blank_page(width, height)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Courier"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    })
    commands = []
    for x, top, size, text in texts:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"BT /F1 {size} Tf 0 g 1 0 0 1 {x} {height-top-size} Tm ({escaped}) Tj ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return PdfReader(output).pages[0]


def consolidate_packing_slips(path: str | Path) -> list[dict]:
    """Rewrite only fully identified orders whose trailing totals safely fit."""
    path = Path(path)
    removed, overlays, redactions, report = set(), {}, [], []
    with pdfplumber.open(path) as pdf:
        footers = [footer_info(page) for page in pdf.pages]
        index = 0
        while index < len(pdf.pages):
            footer = footers[index]
            count = footer["count"] if footer and footer["number"] == 1 else 1
            group = footers[index:index + count]
            valid = (footer and footer["number"] == 1 and len(group) == count
                     and all(f and f["order"] == footer["order"] and f["count"] == count
                             and f["number"] == n + 1 for n, f in enumerate(group)))
            if not valid:
                count = 1
            row = dict(pdf=path.name, order_number=footer["order"] if footer else "",
                       input_pages=count, output_pages=count, pages_removed=0,
                       status="preserved", reason="Single page" if valid and count == 1 else
                       "Unrecognized or inconsistent page numbering")
            if valid and count > 1:
                last = index + count - 1
                lines = summary_lines(pdf.pages[last], footers[last])
                row["reason"] = "Continuation contains products or other content"
                if lines:
                    preceding = pdf.pages[last - 1]
                    top = body_bottom(preceding, footers[last - 1]) + 4
                    row["reason"] = "Insufficient space above the preceding page footer"
                    same_size = (preceding.width == pdf.pages[last].width
                                 and preceding.height == pdf.pages[last].height)
                    if (same_size and not preceding.annots
                            and top + len(lines) * 11 <= footers[last - 1]["rect"][1] - 4):
                        removed.add(last)
                        overlays[last - 1] = [
                            (18, top + n * 11, 8.5, line) for n, line in enumerate(lines)
                        ]
                        for offset in range(count - 1):
                            page_idx = index + offset
                            current = footers[page_idx]
                            redactions.append(dict(page=page_idx, rect=current["rect"]))
                            overlays.setdefault(page_idx, []).append((
                                current["rect"][0] + 1, current["rect"][1] + 1, 8.5,
                                f"Page {offset + 1} of {count - 1}  Order #{footer['order']}",
                            ))
                        row.update(output_pages=count - 1, pages_removed=1,
                                   status="consolidated", reason="Moved totals-only final page")
            report.append(row)
            index += count

        if not removed:
            return report  # No rewrite: preserve the original file byte-for-byte.
        with tempfile.TemporaryDirectory(prefix="slip-consolidation-") as temp:
            plan = Path(temp) / "redactions.json"
            redacted = Path(temp) / "redacted.pdf"
            result = Path(temp) / "result.pdf"
            plan.write_text(json.dumps(redactions))
            subprocess.run(
                ["mutool", "run", str(Path(__file__).with_name("redact_slip_footers.js")),
                 str(path), str(plan), str(redacted)],
                check=True, capture_output=True, text=True, timeout=120,
            )
            reader, writer = PdfReader(redacted), PdfWriter()
            for i, page in enumerate(reader.pages):
                if i in removed:
                    continue
                page = writer.add_page(page)
                if i in overlays:
                    page.merge_page(text_overlay(pdf.pages[i].width, pdf.pages[i].height, overlays[i]))
            writer.write(result)
            # Only replace the generated output after the whole rewrite succeeds.
            path.write_bytes(result.read_bytes())
    return report
