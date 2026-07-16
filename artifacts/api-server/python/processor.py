from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Dict, Tuple, Optional

import pandas as pd
import pdfplumber
from pypdf import PdfReader, PdfWriter


def norm_text(s: str | None) -> str:
    if not s:
        return ""
    s = s.upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_name(s: str | None) -> str:
    s = norm_text(s)
    # Convert LAST FIRST-ish noise into stable tokens. Keep token order mostly intact.
    stop = {"USA", "US", "UNIT", "APT", "STE", "SUITE"}
    return " ".join(t for t in s.split() if t not in stop)


def read_pdf_text_pages(path: str | Path) -> list[str]:
    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for p in pdf.pages:
            pages.append(p.extract_text(x_tolerance=1, y_tolerance=3) or "")
    return pages


SIZE_ORDER: Dict[str, int] = {
    "XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4,
    "2XL": 5, "3XL": 6, "4XL": 7, "5XL": 8, "6XL": 9,
    "YXS": 10, "YS": 11, "YM": 12, "YL": 13, "YXL": 14,
    "OSFA": 15, "OSFM": 16,
}


def extract_custom_field(text: str) -> tuple[str, str]:
    """
    Extract a custom grouping field from the delivery section of a packing slip.
    The label varies by job (e.g. Department, Homeroom, Teacher Name, Team).
    Returns (label, value). Both are empty strings when no custom field is found.

    The custom field always appears immediately after "Recipient Last Name:" in the
    delivery column. pdfplumber renders it in one of two layouts:

      Split form:   "Department Pharmacy"  (then)  "Name:"   (on the next line)
      Inline form:  "Department Name: claims"       (all on one line)
    """
    lines = [ln.strip() for ln in text.splitlines()]

    # Find the "Recipient Last <value>" line so we can anchor our search to right after it.
    recipient_last_idx = None
    for i, ln in enumerate(lines):
        if ln.lower().startswith("recipient last"):
            recipient_last_idx = i
            break

    if recipient_last_idx is None:
        return ("", "")

    # Locate the "Name:" line that closes the Recipient Last field.
    name_colon_idx = None
    for i in range(recipient_last_idx + 1, min(recipient_last_idx + 4, len(lines))):
        if lines[i] == "Name:":
            name_colon_idx = i
            break

    if name_colon_idx is None:
        return ("", "")

    # The very next line after "Name:" is either the custom field or the product table header.
    after_idx = name_colon_idx + 1
    if after_idx >= len(lines):
        return ("", "")

    next_line = lines[after_idx]

    # Inline form: "Department Name: claims" or "Teacher Name: Smith"
    m = re.match(r"^(.+?)\s+Name:\s+(.+)$", next_line)
    if m:
        return (m.group(1).strip(), m.group(2).strip())

    # Split form: "Department Pharmacy" followed by "Name:" on the next line.
    if after_idx + 1 < len(lines) and lines[after_idx + 1] == "Name:":
        words = next_line.split()
        if len(words) >= 2:
            return (words[0], " ".join(words[1:]))

    # Bare label form: "Homeroom: 5A" or "Team: Blue" (no trailing "Name:")
    m = re.match(r"^([A-Za-z][A-Za-z ]{1,30}):\s+(\S.*)$", next_line)
    if m:
        return (m.group(1).strip(), m.group(2).strip())

    return ("", "")


@dataclass
class SlipPage:
    page_index: int
    order_number: str
    customer_name: str
    shipping_name: str
    style: str
    color: str
    size: str
    raw_text: str
    custom_field_label: str = ""
    custom_field_value: str = ""

    @property
    def sort_key(self):
        size_rank = SIZE_ORDER.get(self.size.upper(), 99)
        return (self.style, self.color, size_rank, int(self.order_number or 0), self.page_index)

    @property
    def sort_key_name(self):
        # shipping_name is "Last, First" — sort by last name token
        last = self.shipping_name.split(",")[0].strip().upper() if self.shipping_name else ""
        size_rank = SIZE_ORDER.get(self.size.upper(), 99)
        return (self.style, self.color, size_rank, last, self.page_index)

    @property
    def sort_key_custom(self):
        # Style → Color → Size → Last Name → Custom Field value
        last = self.shipping_name.split(",")[0].strip().upper() if self.shipping_name else ""
        size_rank = SIZE_ORDER.get(self.size.upper(), 99)
        custom = norm_text(self.custom_field_value)
        return (self.style, self.color, size_rank, last, custom, self.page_index)

    @property
    def sort_key_custom_first(self):
        # Custom Field → Last Name
        custom = norm_text(self.custom_field_value)
        last = self.shipping_name.split(",")[0].strip().upper() if self.shipping_name else ""
        return (custom, last, self.page_index)


@dataclass
class LabelPage:
    page_index: int
    name: str
    address: str
    tracking: str
    source_file: str
    source_page_index: int
    raw_text: str


def _first_match(pattern: str, text: str, flags=re.I | re.S) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else ""


def parse_slip_text(text: str, page_index: int) -> SlipPage:
    order = _first_match(r"Order\s*(?:Number|#)\s*:?\s*#?\s*(\d+)", text)
    if not order:
        order = _first_match(r"Order\s*#\s*(\d+)", text)

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # The very first line of each packing slip is reliably the customer name
    # (e.g. "Su, Xizhen" or "Beauchesne, Ava") — use it as the primary fallback.
    first_line_name = lines[0] if lines else ""

    # Header often looks like "Page 1 of 1 Order #1234567\nLast, First"
    header_name = ""
    for i, ln in enumerate(lines):
        if re.search(r"Order\s*#?\s*\d+", ln, re.I) and i + 1 < len(lines):
            header_name = lines[i + 1].strip()
            break

    shipping_block = _first_match(r"Customer Shipping:\s*(.*?)(?:Delivery\s*Method:|Sort\s*#|$)", text)
    shipping_lines = [ln.strip() for ln in shipping_block.splitlines() if ln.strip()]
    shipping_name_raw = shipping_lines[0] if shipping_lines else ""

    # pdfplumber column layout often puts "Delivery" (from "Delivery Method:") as the
    # first token after "Customer Shipping:" — detect and discard that artefact.
    bad_slip_tokens = {"DELIVERY", "SHIPPING", "METHOD"}
    if not shipping_name_raw or norm_text(shipping_name_raw) in bad_slip_tokens:
        shipping_name = first_line_name or header_name
    else:
        shipping_name = shipping_name_raw

    billing_block = _first_match(r"Customer Billing:\s*(.*?)(?:Customer Shipping:|Delivery\s*Method:|$)", text)
    billing_lines = [ln.strip() for ln in billing_block.splitlines() if ln.strip()]
    billing_name_raw = billing_lines[0] if billing_lines else ""
    if not billing_name_raw or norm_text(billing_name_raw) in bad_slip_tokens:
        customer_name = first_line_name or header_name
    else:
        customer_name = billing_name_raw

    # Extract product table row. These slips have: Sort # Style # Vendor Product ... Size Color Qty Price
    style = ""
    size = ""
    color = ""
    table_lines = [ln.strip() for ln in lines if ln.strip()]
    joined = "\n".join(table_lines)

    # Style is usually after Sort # in product row, e.g. "11 B5000 SanMar"
    m = re.search(r"(?:^|\n)\s*\d+\s+([A-Z0-9-]{2,})\s+(?:SanMar|SS Activewear|S&S|AlphaBroder|.+?)", joined, re.I)
    if m:
        style = m.group(1).strip().upper()

    # Size/color usually appear before qty/price/extended. Try table-specific extraction.
    # Examples: "OSFA Black/ Black 1 $22.00" or "OSFM Navy/ White/ Heather Grey 1 $20.00"
    candidates = re.findall(r"\b(OSFA|OSFM|XS|S|M|L|XL|2XL|3XL|4XL|5XL|6XL|YXS|YS|YM|YL|YXL)\b\s+(.+?)\s+\d+\s+\$", joined, re.I)
    if candidates:
        size, color = candidates[-1][0].upper(), re.sub(r"\s+", " ", candidates[-1][1]).strip()

    cf_label, cf_value = extract_custom_field(text)
    return SlipPage(page_index, order, customer_name, shipping_name, style, color, size, text,
                    custom_field_label=cf_label, custom_field_value=cf_value)


def parse_packing_slips(path: str | Path) -> list[SlipPage]:
    return [parse_slip_text(txt, i) for i, txt in enumerate(read_pdf_text_pages(path))]


def parse_label_text(text: str, page_index: int, source_file: str, source_page_index: int) -> LabelPage:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    tracking = _first_match(r"(?:USPS TRACKING #\s*)?((?:9\d{3}|94\d{2})\s+(?:\d{4}\s+){4}\d{4}\s*\d{2})", text)
    if not tracking:
        tracking = _first_match(r"(9\d{21,25})", re.sub(r"\s+", "", text))

    name = ""
    address = ""

    # Pattern 1: "SHIP <NAME>\nTO:\n<address>" — common USPS label format.
    for i, ln in enumerate(lines):
        if ln.startswith("SHIP ") and i + 1 < len(lines) and lines[i + 1].strip().rstrip(":").upper() in ("TO", "SHIP TO"):
            candidate = ln[5:].strip()
            if candidate:
                name = candidate
                # Address starts after the "TO:" line
                address = " | ".join(lines[i + 2: i + 5])
                break

    # Pattern 2: all-caps name line followed by a line with a digit (street address).
    if not name:
        bad = {"MINT PRINTWORKS", "USPS GROUND ADVANTAGE", "US POSTAGE FEES PAID IMI", "COMMERCIAL"}
        for i, ln in enumerate(lines):
            if re.match(r"^[A-Z][A-Z .,'-]+$", ln) and i + 1 < len(lines):
                if norm_text(ln) not in bad and not ln.startswith("USPS"):
                    nxt = lines[i + 1]
                    if re.search(r"\d", nxt):
                        name = ln
                        address = " | ".join(lines[i + 1:i + 4])
                        break

    return LabelPage(page_index, name, address, tracking, source_file, source_page_index, text)


def parse_label_pdfs(paths: Iterable[str | Path]) -> tuple[list[LabelPage], list[tuple[str, int]]]:
    labels: list[LabelPage] = []
    sources: list[tuple[str, int]] = []
    global_index = 0
    for path in paths:
        texts = read_pdf_text_pages(path)
        for i, txt in enumerate(texts):
            labels.append(parse_label_text(txt, global_index, Path(path).name, i))
            sources.append((str(path), i))
            global_index += 1
    return labels, sources


def write_selected_pages(source_pdf: str | Path, output_pdf: str | Path, page_indices: list[int]) -> None:
    reader = PdfReader(str(source_pdf))
    writer = PdfWriter()
    for idx in page_indices:
        writer.add_page(reader.pages[idx])
    with open(output_pdf, "wb") as f:
        writer.write(f)


def combine_label_pdfs(paths: Iterable[str | Path], output_pdf: str | Path) -> None:
    writer = PdfWriter()
    for path in paths:
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
    with open(output_pdf, "wb") as f:
        writer.write(f)


def write_sorted_labels(label_sources: list[tuple[str, int]], output_pdf: str | Path, selected_global_indices: list[int]) -> None:
    cache: Dict[str, PdfReader] = {}
    writer = PdfWriter()
    for global_idx in selected_global_indices:
        src, page_idx = label_sources[global_idx]
        if src not in cache:
            cache[src] = PdfReader(src)
        writer.add_page(cache[src].pages[page_idx])
    with open(output_pdf, "wb") as f:
        writer.write(f)


def group_slip_pages(slips: list[SlipPage]) -> list[list[SlipPage]]:
    """
    Group consecutive PDF pages into logical slips.

    A multi-page order (e.g. "Page 1 of 2 / Page 2 of 2") produces one page per PDF page,
    but the continuation pages have no customer name or order number — they are just totals
    overflow. Attach any page that has no order number (or the same order number as the
    preceding group) to the preceding group so they sort and output together as one unit.
    """
    if not slips:
        return []
    groups: list[list[SlipPage]] = []
    current: list[SlipPage] = [slips[0]]
    for slip in slips[1:]:
        if not slip.order_number or slip.order_number == current[0].order_number:
            current.append(slip)
        else:
            groups.append(current)
            current = [slip]
    groups.append(current)
    return groups


def sort_packing_slips(input_pdf: str | Path, output_pdf: str | Path) -> list[SlipPage]:
    slips = parse_packing_slips(input_pdf)
    groups = group_slip_pages(slips)
    sorted_groups = sorted(groups, key=lambda g: g[0].sort_key)
    all_pages = [s.page_index for g in sorted_groups for s in g]
    write_selected_pages(input_pdf, output_pdf, all_pages)
    return [g[0] for g in sorted_groups]


def match_labels_to_slips(sorted_slips: list[SlipPage], labels: list[LabelPage]) -> tuple[list[int], pd.DataFrame]:
    by_name: Dict[str, list[LabelPage]] = {}
    for lab in labels:
        by_name.setdefault(norm_name(lab.name), []).append(lab)

    used: set[int] = set()
    selected: list[int] = []
    rows = []
    for seq, slip in enumerate(sorted_slips, start=1):
        target_names = [norm_name(slip.shipping_name), norm_name(slip.customer_name)]
        match: Optional[LabelPage] = None
        method = ""
        for target in target_names:
            if not target:
                continue
            candidates = [c for c in by_name.get(target, []) if c.page_index not in used]
            if candidates:
                match = candidates[0]
                method = "exact name"
                break
        if not match:
            # Fallback: all tokens in either direction, excluding short tokens.
            for lab in labels:
                if lab.page_index in used:
                    continue
                lname = norm_name(lab.name)
                for tname in target_names:
                    ta = {t for t in tname.split() if len(t) > 1}
                    la = {t for t in lname.split() if len(t) > 1}
                    if ta and la and (ta <= la or la <= ta):
                        match = lab
                        method = "token name"
                        break
                if match:
                    break
        if match:
            used.add(match.page_index)
            selected.append(match.page_index)
            rows.append({
                "sequence": seq,
                "status": "matched",
                "method": method,
                "order_number": slip.order_number,
                "style": slip.style,
                "color": slip.color,
                "size": slip.size,
                "slip_name": slip.shipping_name,
                "label_name": match.name,
                "tracking": match.tracking,
                "label_source_file": match.source_file,
                "label_source_page": match.source_page_index + 1,
                "slip_page": slip.page_index + 1,
            })
        else:
            rows.append({
                "sequence": seq,
                "status": "missing_label",
                "method": "",
                "order_number": slip.order_number,
                "style": slip.style,
                "color": slip.color,
                "size": slip.size,
                "slip_name": slip.shipping_name,
                "label_name": "",
                "tracking": "",
                "label_source_file": "",
                "label_source_page": "",
                "slip_page": slip.page_index + 1,
            })

    for lab in labels:
        if lab.page_index not in used:
            rows.append({
                "sequence": "",
                "status": "unused_label",
                "method": "",
                "order_number": "",
                "style": "",
                "color": "",
                "size": "",
                "slip_name": "",
                "label_name": lab.name,
                "tracking": lab.tracking,
                "label_source_file": lab.source_file,
                "label_source_page": lab.source_page_index + 1,
                "slip_page": "",
            })
    return selected, pd.DataFrame(rows)


def _write_custom_field_report(sorted_groups: list[list[SlipPage]], report_csv: Path) -> None:
    rows = []
    for seq, group in enumerate(sorted_groups, start=1):
        s = group[0]
        rows.append({
            "sequence": seq,
            "order_number": s.order_number,
            "slip_name": s.shipping_name,
            "style": s.style,
            "color": s.color,
            "size": s.size,
            "custom_field_label": s.custom_field_label,
            "custom_field_value": s.custom_field_value,
            "extracted": "yes" if s.custom_field_value else "NO - not found",
        })
    pd.DataFrame(rows).to_csv(report_csv, index=False)


def process_batch(packing_slips_pdf: str | Path, label_pdfs: list[str | Path], out_dir: str | Path, preset: str) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    if preset in {"combine_labels", "sort_labels", "sort_both"}:
        combined = out_dir / "combined_labels.pdf"
        combine_label_pdfs(label_pdfs, combined)
        outputs["combined_labels"] = combined

    if preset == "sort_slips_name":
        slips = parse_packing_slips(packing_slips_pdf)
        groups = group_slip_pages(slips)
        sorted_groups = sorted(groups, key=lambda g: g[0].sort_key_name)
        sorted_slips_pdf = out_dir / "sorted_packing_slips.pdf"
        write_selected_pages(packing_slips_pdf, sorted_slips_pdf,
                             [s.page_index for g in sorted_groups for s in g])
        outputs["sorted_packing_slips"] = sorted_slips_pdf

    if preset == "sort_slips_custom":
        slips = parse_packing_slips(packing_slips_pdf)
        groups = group_slip_pages(slips)
        sorted_groups = sorted(groups, key=lambda g: g[0].sort_key_custom)
        sorted_slips_pdf = out_dir / "sorted_packing_slips.pdf"
        write_selected_pages(packing_slips_pdf, sorted_slips_pdf,
                             [s.page_index for g in sorted_groups for s in g])
        outputs["sorted_packing_slips"] = sorted_slips_pdf
        report_csv = out_dir / "custom_field_report.csv"
        _write_custom_field_report(sorted_groups, report_csv)
        outputs["custom_field_report"] = report_csv

    if preset == "sort_slips_custom_first":
        slips = parse_packing_slips(packing_slips_pdf)
        groups = group_slip_pages(slips)
        sorted_groups = sorted(groups, key=lambda g: g[0].sort_key_custom_first)
        sorted_slips_pdf = out_dir / "sorted_packing_slips.pdf"
        write_selected_pages(packing_slips_pdf, sorted_slips_pdf,
                             [s.page_index for g in sorted_groups for s in g])
        outputs["sorted_packing_slips"] = sorted_slips_pdf
        report_csv = out_dir / "custom_field_report.csv"
        _write_custom_field_report(sorted_groups, report_csv)
        outputs["custom_field_report"] = report_csv

    sorted_slips: list[SlipPage] | None = None
    if preset in {"sort_slips", "sort_labels", "sort_both"}:
        sorted_slips_pdf = out_dir / "sorted_packing_slips.pdf"
        sorted_slips = sort_packing_slips(packing_slips_pdf, sorted_slips_pdf)
        outputs["sorted_packing_slips"] = sorted_slips_pdf

    if preset in {"sort_labels", "sort_both"}:
        assert sorted_slips is not None
        labels, label_sources = parse_label_pdfs(label_pdfs)
        selected, report = match_labels_to_slips(sorted_slips, labels)
        sorted_labels_pdf = out_dir / "sorted_shipping_labels.pdf"
        write_sorted_labels(label_sources, sorted_labels_pdf, selected)
        outputs["sorted_shipping_labels"] = sorted_labels_pdf
        report_csv = out_dir / "match_report.csv"
        report.to_csv(report_csv, index=False)
        outputs["match_report"] = report_csv

    if preset == "match_labels":
        # Sort labels to match packing slips in their EXISTING order — no slip rewriting.
        slips = parse_packing_slips(packing_slips_pdf)
        labels, label_sources = parse_label_pdfs(label_pdfs)
        selected, report = match_labels_to_slips(slips, labels)
        sorted_labels_pdf = out_dir / "sorted_shipping_labels.pdf"
        write_sorted_labels(label_sources, sorted_labels_pdf, selected)
        outputs["sorted_shipping_labels"] = sorted_labels_pdf
        report_csv = out_dir / "match_report.csv"
        report.to_csv(report_csv, index=False)
        outputs["match_report"] = report_csv

    zip_path = out_dir / "mint_pdf_sorter_outputs.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, path in outputs.items():
            z.write(path, arcname=path.name)
    outputs["zip"] = zip_path
    return outputs
