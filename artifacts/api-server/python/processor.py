from __future__ import annotations

import io
import csv
import json
import re
import zipfile
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable, List, Dict, Tuple, Optional
from xml.etree import ElementTree

import pandas as pd
import pdfplumber
from pypdf import PdfReader, PdfWriter
from line_items import count_product_rows, prioritize_single_line_items
from product_preference import product_rows, apply_product_preference, SUPPORTED_PRESETS


SHEET_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
STORE_EXPORT_DEFAULT_DROP_COLUMNS = {
    "Dealer Name",
    "Organization County",
    "Catalog Sales Id",
    "Sales Id",
    "Status",
    "Ship Country",
    "Ship Country Code",
    "Product Status",
    "Event Product ID",
    "Sub Category",
    "Product Image URL",
    "Product UPC",
    "Tax Total",
    "Salesperson Id",
    "Salesperson External Id",
    "BatchID",
    "External Organization ID",
    "External Organization Branch ID",
    "Batch Standalone",
}


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


def _column_index(cell_reference: str) -> int:
    letters = re.match(r"[A-Z]+", cell_reference.upper())
    if not letters:
        return 0
    value = 0
    for letter in letters.group(0):
        value = value * 26 + ord(letter) - ord("A") + 1
    return value - 1


def _read_xlsx_sheets(path: str | Path) -> dict[str, list[list[str]]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", SHEET_NS):
                shared_strings.append("".join(node.text or "" for node in item.iter(f"{{{SHEET_NS['a']}}}t")))

        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            relationship.attrib["Id"]: relationship.attrib["Target"].lstrip("/")
            for relationship in relationships.findall("r:Relationship", REL_NS)
        }
        sheets: dict[str, list[list[str]]] = {}
        for sheet in workbook.findall(".//a:sheets/a:sheet", SHEET_NS):
            name = sheet.attrib.get("name", "Sheet")
            relationship_id = sheet.attrib.get(f"{{{OFFICE_REL_NS}}}id", "")
            target = targets.get(relationship_id, "")
            if target.startswith("xl/"):
                sheet_path = target
            else:
                sheet_path = f"xl/{target}"
            sheet_root = ElementTree.fromstring(archive.read(sheet_path))
            rows: list[list[str]] = []
            for row in sheet_root.findall(".//a:sheetData/a:row", SHEET_NS):
                values: dict[int, str] = {}
                for cell in row.findall("a:c", SHEET_NS):
                    reference = cell.attrib.get("r", "A1")
                    cell_type = cell.attrib.get("t", "")
                    value_node = cell.find("a:v", SHEET_NS)
                    value = value_node.text or "" if value_node is not None else ""
                    if cell_type == "s" and value:
                        value = shared_strings[int(value)]
                    elif cell_type == "inlineStr":
                        value = "".join(
                            node.text or ""
                            for node in cell.iter(f"{{{SHEET_NS['a']}}}t")
                        )
                    values[_column_index(reference)] = value
                width = max(values, default=-1) + 1
                rows.append([values.get(index, "") for index in range(width)])
            sheets[name] = rows
        return sheets


def read_spreadsheet_sheets(path: str | Path, original_name: str = "") -> dict[str, list[list[str]]]:
    suffix = Path(original_name or path).suffix.lower()
    if suffix == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as file:
            return {"CSV": [[str(value) for value in row] for row in csv.reader(file)]}
    if suffix == ".xlsx":
        return _read_xlsx_sheets(path)
    raise ValueError("Spreadsheet must be a CSV or XLSX file")


def inspect_spreadsheet(path: str | Path, original_name: str = "") -> dict:
    sheets = read_spreadsheet_sheets(path, original_name)
    return {
        "sheets": [
            {
                "name": name,
                "rows": rows[:20],
            }
            for name, rows in sheets.items()
        ]
    }


def parse_store_export(
    input_csv: str | Path,
    out_dir: Path,
    additional_drop_indexes: list[int] | None = None,
) -> Path:
    """Remove the standard and user-selected columns without coercing cell values."""
    input_path = Path(input_csv)
    with open(input_path, "rb") as source:
        prefix = source.read(4)
        source.seek(0)
        has_bom = prefix.startswith(b"\xef\xbb\xbf")
        sample = source.read(8192)
        source.seek(0)
        text_sample = sample.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text_sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        newline = "\r\n" if b"\r\n" in sample else "\n"
        with open(input_path, "r", encoding="utf-8-sig", newline="") as csv_source:
            reader = csv.reader(csv_source, dialect)
            try:
                headers = next(reader)
            except StopIteration as exc:
                raise ValueError("The uploaded CSV is empty") from exc
            if not headers:
                raise ValueError("The uploaded CSV has no header row")

            requested_indexes = additional_drop_indexes or []
            if any(
                isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(headers)
                for index in requested_indexes
            ):
                raise ValueError("A selected column index is outside the CSV header range")

            drop_indexes = {
                index for index, header in enumerate(headers)
                if header in STORE_EXPORT_DEFAULT_DROP_COLUMNS
            }
            drop_indexes.update(requested_indexes)
            keep_indexes = [index for index in range(len(headers)) if index not in drop_indexes]
            if not keep_indexes:
                raise ValueError("At least one CSV column must remain")

            output_path = out_dir / "parsed_store_export.csv"
            output_encoding = "utf-8-sig" if has_bom else "utf-8"
            with open(output_path, "w", encoding=output_encoding, newline="") as csv_target:
                writer = csv.writer(csv_target, dialect, lineterminator=newline)
                writer.writerow([headers[index] for index in keep_indexes])
                for row in reader:
                    writer.writerow([
                        row[index] if index < len(row) else ""
                        for index in keep_indexes
                    ])
    return output_path


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


def _is_red_color(color: object) -> bool:
    """Return whether a pdfplumber color value is visibly red."""
    if not isinstance(color, (tuple, list)) or len(color) < 3:
        return False
    try:
        red, green, blue = (float(channel) for channel in color[:3])
    except (TypeError, ValueError):
        return False
    return red > 0.35 and red > green * 1.4 and red > blue * 1.4


def extract_required_field_from_page(page) -> str:
    """
    Read the red text in the Product Name column.

    Printavo marks required product fields with red text. The normal text
    extractor intentionally ignores color, so this uses page characters and
    the table header coordinates to isolate that red value.
    """
    words = page.extract_words(x_tolerance=1, y_tolerance=3)
    product_word = next(
        (word for word in words if word["text"].strip().lower() == "product"),
        None,
    )
    size_word = next(
        (
            word for word in words
            if word["text"].strip().lower() == "size"
            and product_word is not None
            and abs(word["top"] - product_word["top"]) < 3
            and word["x0"] > product_word["x0"]
        ),
        None,
    )
    if product_word is None or size_word is None:
        return ""

    left = float(product_word["x0"]) - 2
    right = float(size_word["x0"]) - 2
    table_top = float(product_word["bottom"]) + 2
    red_chars = [
        char
        for char in page.chars
        if float(char.get("top", 0)) >= table_top
        and left <= float(char.get("x0", 0)) < right
        and (
            _is_red_color(char.get("non_stroking_color"))
            or _is_red_color(char.get("stroking_color"))
        )
    ]
    if not red_chars:
        return ""

    # Keep line breaks and word gaps while only retaining the red characters.
    lines: list[list[dict]] = []
    for char in sorted(red_chars, key=lambda item: (float(item["top"]), float(item["x0"]))):
        if not lines or abs(float(char["top"]) - float(lines[-1][0]["top"])) > 2:
            lines.append([char])
        else:
            lines[-1].append(char)

    rendered_lines: list[str] = []
    for line in lines:
        line = sorted(line, key=lambda item: float(item["x0"]))
        rendered = line[0]["text"]
        for previous, char in zip(line, line[1:]):
            gap = float(char["x0"]) - float(previous["x1"])
            if gap > max(1.5, float(previous.get("size", 8)) * 0.25):
                rendered += " "
            rendered += char["text"]
        if rendered.strip():
            rendered_lines.append(rendered.strip())
    return " ".join(rendered_lines)


def _extract_birth_year(value: str) -> str:
    """Extract a plausible birth year from a year or common full-date value."""
    standalone_year = re.search(r"(?<!\d)((?:18|19|20)\d{2})(?!\d)", value)
    if standalone_year:
        return standalone_year.group(1)

    digits = re.sub(r"\D", "", value)
    # Compact MMDDYYYY or MDDYYYY values, such as 04062016.
    if 7 <= len(digits) <= 8:
        candidate = digits[-4:]
        if re.fullmatch(r"(?:18|19|20)\d{2}", candidate):
            return candidate

    date_match = re.search(
        r"(?<!\d)\d{1,2}[/-]\d{1,2}[/-](\d{2})(?!\d)",
        value,
    )
    if date_match:
        return str(2000 + int(date_match.group(1)))
    return ""


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
    delivery_method: str = ""
    location: str = ""
    sort_number: str = ""
    order_date: str = ""
    required_field_value: str = ""
    line_item_count: int | None = None
    product_rows: list[dict] = field(default_factory=list)

    @property
    def sort_key(self):
        size_rank = SIZE_ORDER.get(self.size.upper(), 99)
        return (self.style, self.color, size_rank, int(self.order_number or 0), self.page_index)

    @property
    def sort_key_name(self):
        return self.build_sort_key(["style", "color", "size", "last_name"])

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

    @property
    def sort_key_required_field(self):
        # Birth years sort chronologically, oldest first. Slips without a
        # recognizable year are kept after slips with a valid year.
        birth_year = _extract_birth_year(self.required_field_value)
        if birth_year:
            return (0, int(birth_year), self.page_index)
        return (1, 9999, norm_text(self.required_field_value), self.page_index)

    def sort_value_for_field(self, field: str):
        if field == "last_name":
            return norm_text(self.shipping_name.split(",")[0]) if "," in self.shipping_name else norm_text(self.shipping_name)
        if field == "first_name":
            parts = self.shipping_name.split(",", 1)
            return norm_text(parts[1].strip()) if len(parts) > 1 else ""
        if field == "style":
            return norm_text(self.style)
        if field == "color":
            return norm_text(self.color)
        if field == "size":
            key = norm_text(self.size).replace(" ", "")
            return (SIZE_ORDER.get(key, 99), norm_text(self.size))
        if field == "custom_field":
            return norm_text(self.custom_field_value)
        if field == "delivery_method":
            return norm_text(self.delivery_method)
        if field == "location":
            return norm_text(self.location)
        if field == "sort_number":
            try:
                return (0, int(self.sort_number))
            except (ValueError, TypeError):
                return (1, norm_text(self.sort_number))
        if field == "order_number":
            try:
                return (0, int(self.order_number))
            except (ValueError, TypeError):
                return (1, norm_text(self.order_number))
        if field == "order_date":
            return self.order_date or ""
        if field == "required_field":
            return self.sort_key_required_field
        return ""

    def build_sort_key(self, fields: list[str]) -> tuple:
        return tuple(self.sort_value_for_field(f) for f in fields) + (self.page_index,)


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


def parse_slip_text(text: str, page_index: int, required_field_value: str = "") -> SlipPage:
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
    sort_number = ""
    table_lines = [ln.strip() for ln in lines if ln.strip()]
    joined = "\n".join(table_lines)

    # Style is usually after Sort # in product row, e.g. "11 B5000 SanMar"
    m = re.search(r"(?:^|\n)\s*(\d+)\s+([A-Z0-9-]{2,})\s+(?:SanMar|SS Activewear|S&S|AlphaBroder|.+?)", joined, re.I)
    if m:
        sort_number = m.group(1).strip()
        style = m.group(2).strip().upper()

    # Size/color usually appear before qty/price/extended. Try table-specific extraction.
    # Examples: "OSFA Black/ Black 1 $22.00" or "OSFM Navy/ White/ Heather Grey 1 $20.00"
    candidates = re.findall(r"\b(OSFA|OSFM|XS|S|M|L|XL|2XL|3XL|4XL|5XL|6XL|YXS|YS|YM|YL|YXL)\b\s+(.+?)\s+\d+\s+\$", joined, re.I)
    if candidates:
        size, color = candidates[-1][0].upper(), re.sub(r"\s+", " ", candidates[-1][1]).strip()

    cf_label, cf_value = extract_custom_field(text)
    delivery_method = _first_match(r"Delivery\s*Method:\s*([^\n]+)", text)
    location = _first_match(r"Location(?:\s*Name)?:\s*([^\n]+)", text)
    order_date = _first_match(r"Order\s*Date:\s*([^\n]+)", text)
    return SlipPage(page_index, order, customer_name, shipping_name, style, color, size, text,
                    custom_field_label=cf_label, custom_field_value=cf_value,
                    delivery_method=delivery_method, location=location,
                    sort_number=sort_number, order_date=order_date,
                    required_field_value=required_field_value)


def extract_positioned_delivery_method(words):
    """Read the delivery column without adjacent dates, names, or addresses."""
    for delivery in words:
        if delivery["text"] != "Delivery":
            continue
        method = next((w for w in words if w["text"] == "Method:"
                       and w["x0"] >= delivery["x0"] - 2
                       and abs(w["top"] - delivery["top"]) < 15), None)
        if not method:
            continue
        right = min((w["x0"] for w in words
                     if w["x0"] > method["x1"] + 2 and w["text"].endswith(":")
                     and abs(w["top"] - method["top"]) < 2), default=float("inf"))
        inline = sorted([w for w in words
                         if method["x1"] + 2 < w["x0"] < right
                         and abs(w["top"] - method["top"]) < 2], key=lambda w: w["x0"])
        if inline:
            return " ".join(w["text"] for w in inline)
        candidates = sorted([w for w in words
                             if delivery["x0"] - 2 <= w["x0"] < right
                             and method["bottom"] < w["top"] < method["bottom"] + 65],
                            key=lambda w: (w["top"], w["x0"]))
        lines = []
        for word in candidates:
            if not lines or abs(word["top"] - lines[-1][0]["top"]) > 2:
                lines.append([])
            lines[-1].append(word)
        value = []
        previous_bottom = method["bottom"]
        for line in lines:
            line.sort(key=lambda w: w["x0"])
            if (line[0]["top"] - previous_bottom > 18
                    or any(":" in w["text"] for w in line)
                    or line[0]["text"] in {"Recipient", "Sort", "Style", "Product"}):
                break
            value.extend(w["text"] for w in line)
            previous_bottom = max(w["bottom"] for w in line)
        return " ".join(value)
    return None


def apply_positioned_slip_fields(page, slip: SlipPage) -> None:
    """Read column cells rather than guessing from interleaved PDF text lines."""
    words = page.extract_words(x_tolerance=1, y_tolerance=3)
    delivery_method = extract_positioned_delivery_method(words)
    if delivery_method is not None:
        slip.delivery_method = delivery_method
    slip.line_item_count = count_product_rows(page, words)
    slip.product_rows = product_rows(page, words)
    style_header = next((w for w in words if w["text"] == "Style"), None)
    if style_header:
        headers = {
            w["text"]: w for w in words
            if abs(w["top"] - style_header["top"]) < 3
        }
        if all(key in headers for key in ("Product", "Size", "Color", "Qty")):
            style_right = headers.get("Vendor", headers["Product"])["x0"]
            # The first item supplies the order's product sort key. Keep the
            # complete order intact, including all subsequent product pages.
            candidates = [
                w for w in words
                if style_header["x0"] - 2 <= w["x0"] < style_right - 2
                and w["top"] > style_header["bottom"] + 2
                and w["top"] < page.height - 50
            ]
            if candidates:
                anchor = min(candidates, key=lambda w: (w["top"], w["x0"]))
                # Chipply draws cell rectangles around each product row.
                cells = [
                    r for r in page.rects
                    if r["x0"] <= anchor["x0"] < r["x1"]
                    and r["top"] <= anchor["top"] and r["bottom"] >= anchor["bottom"]
                    and r["height"] > 10 and r["width"] > 10
                ]
                if cells:
                    cell = min(cells, key=lambda r: r["height"])
                    top, bottom = cell["top"], cell["bottom"]
                else:
                    top, bottom = anchor["top"] - 2, anchor["bottom"] + 2

                def cell_text(left, right):
                    selected = [
                        w for w in words
                        if left - 2 <= w["x0"] < right - 2
                        and top <= (w["top"] + w["bottom"]) / 2 < bottom
                    ]
                    return " ".join(w["text"] for w in sorted(
                        selected, key=lambda w: (round(w["top"], 1), w["x0"])
                    )).strip()

                slip.style = cell_text(style_header["x0"], style_right)
                slip.size = cell_text(headers["Size"]["x0"], headers["Color"]["x0"])
                slip.color = cell_text(headers["Color"]["x0"], headers["Qty"]["x0"])
                # Export colors may append the style code; it is not a color.
                slip.color = re.sub(
                    r"\s+-\s*" + re.escape(slip.style) + r"$", "", slip.color
                ).strip()

    # Recipient fields are more reliable than a store-title/first-line fallback.
    recipient = {}
    for word in words:
        if word["text"] != "Recipient":
            continue
        line = sorted(
            [w for w in words if abs(w["top"] - word["top"]) < 2 and w["x0"] >= word["x0"]],
            key=lambda w: w["x0"],
        )
        kind = next((w for w in line if w["text"] in ("First", "Last")), None)
        if kind:
            value = " ".join(
                w["text"] for w in line
                if w["x0"] > kind["x1"] + 2 and w["text"] not in ("Name:", "Name")
            )
            if value:
                recipient[kind["text"]] = value
    if recipient.get("First") and recipient.get("Last"):
        slip.shipping_name = f"{recipient['Last']}, {recipient['First']}"


def parse_packing_slips(path: str | Path) -> list[SlipPage]:
    slips: list[SlipPage] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            required_field_value = extract_required_field_from_page(page)
            slip = parse_slip_text(text, i, required_field_value)
            apply_positioned_slip_fields(page, slip)
            slips.append(slip)
    return slips


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


def sort_packing_slips(input_pdf: str | Path, output_pdf: str | Path, single_line_item_first=False,
                       groups: list[list[SlipPage]] | None = None) -> list[SlipPage]:
    if groups is None:
        groups = group_slip_pages(parse_packing_slips(input_pdf))
    sorted_groups = sorted(groups, key=lambda g: g[0].sort_key)
    sorted_groups = prioritize_single_line_items(sorted_groups, single_line_item_first)
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


def _write_custom_sort_report(sorted_groups: list[list[SlipPage]], report_csv: Path) -> None:
    rows = []
    for seq, group in enumerate(sorted_groups, start=1):
        s = group[0]
        last = s.shipping_name.split(",")[0].strip() if "," in s.shipping_name else s.shipping_name
        first = s.shipping_name.split(",", 1)[1].strip() if "," in s.shipping_name else ""
        rows.append({
            "sequence": seq,
            "order_number": s.order_number,
            "source_pages": ", ".join(str(page.page_index + 1) for page in group),
            "last_name": last,
            "first_name": first,
            "style": s.style,
            "color": s.color,
            "size": s.size,
            "custom_field_label": s.custom_field_label,
            "custom_field_value": s.custom_field_value,
            "delivery_method": s.delivery_method,
            "location": s.location,
            "sort_number": s.sort_number,
            "order_date": s.order_date,
            "required_field_value": s.required_field_value,
        })
    pd.DataFrame(rows).to_csv(report_csv, index=False)


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


def split_packing_slips_by_required_field(
    input_pdf: str | Path,
    out_dir: Path,
    single_line_item_first=False,
) -> dict[str, Path]:
    """
    Split a packing-slip PDF into one PDF per birth year without re-sorting it.

    Orders remain whole, and their relative sequence within each generated batch
    is identical to their sequence in the source PDF.
    """
    slips = parse_packing_slips(input_pdf)
    groups = group_slip_pages(slips)
    batches: dict[str, list[list[SlipPage]]] = {}
    manifest_rows = []

    for source_sequence, group in enumerate(groups, start=1):
        first = group[0]
        birth_year = _extract_birth_year(first.required_field_value)
        batch_value = birth_year or "unknown"
        batches.setdefault(batch_value, []).append(group)
        manifest_rows.append({
            "source_sequence": source_sequence,
            "order_number": first.order_number,
            "birth_year": birth_year,
            "required_field_value": first.required_field_value,
            "batch": batch_value,
            "source_pages": ", ".join(str(page.page_index + 1) for page in group),
            "page_count": len(group),
        })

    outputs: dict[str, Path] = {}
    for batch_value in sorted(batches, key=lambda value: (value == "unknown", value)):
        batch_groups = prioritize_single_line_items(batches[batch_value], single_line_item_first)
        filename = f"packing_slips_birth_year_{batch_value}.pdf"
        output_pdf = out_dir / filename
        page_indices = [page.page_index for group in batch_groups for page in group]
        write_selected_pages(input_pdf, output_pdf, page_indices)
        outputs[f"birth_year_{batch_value}"] = output_pdf

    manifest_path = out_dir / "birth_year_batch_manifest.csv"
    pd.DataFrame(manifest_rows).to_csv(manifest_path, index=False)
    outputs["birth_year_batch_manifest"] = manifest_path
    return outputs


def sort_to_spreadsheet_sequence(
    packing_slips_pdf: str | Path,
    label_pdfs: list[str | Path],
    spreadsheet_path: str | Path,
    spreadsheet_name: str,
    mapping: dict,
    out_dir: Path,
    single_line_item_first=False,
) -> dict[str, Path]:
    sheets = read_spreadsheet_sheets(spreadsheet_path, spreadsheet_name)
    sheet_name = str(mapping.get("sheet_name") or next(iter(sheets), ""))
    if sheet_name not in sheets:
        raise ValueError(f"Spreadsheet sheet not found: {sheet_name}")
    rows = sheets[sheet_name]
    header_row = int(mapping.get("header_row", 1))
    if header_row < 1 or header_row > len(rows):
        raise ValueError("Spreadsheet header row is out of range")
    headers = rows[header_row - 1]
    header_lookup = {str(value).strip(): index for index, value in enumerate(headers) if str(value).strip()}

    def mapped_value(row: list[str], key: str) -> str:
        column = str(mapping.get(key) or "").strip()
        index = header_lookup.get(column)
        if index is None or index >= len(row):
            return ""
        return str(row[index]).strip()

    if not mapping.get("order_number_column"):
        raise ValueError("Map the spreadsheet order number column")

    slips = parse_packing_slips(packing_slips_pdf)
    groups = group_slip_pages(slips)
    unused = set(range(len(groups)))
    ordered_group_indices: list[int] = []
    matched_order_sequences: dict[str, int] = {}
    report_rows = []

    for spreadsheet_row, row in enumerate(rows[header_row:], start=header_row + 1):
        spreadsheet_order = re.sub(r"\D", "", mapped_value(row, "order_number_column"))
        match_index: int | None = None
        method = ""

        if spreadsheet_order and spreadsheet_order in matched_order_sequences:
            report_rows.append({
                "spreadsheet_row": spreadsheet_row,
                "status": "duplicate_spreadsheet_order",
                "match_method": "order_number",
                "spreadsheet_order_number": spreadsheet_order,
                "slip_name": "",
                "slip_order_number": spreadsheet_order,
                "output_sequence": matched_order_sequences[spreadsheet_order],
            })
            continue

        if spreadsheet_order:
            match_index = next(
                (
                    index
                    for index in unused
                    if groups[index][0].order_number == spreadsheet_order
                ),
                None,
            )
            if match_index is not None:
                method = "order_number"

        if match_index is None:
            report_rows.append({
                "spreadsheet_row": spreadsheet_row,
                "status": "spreadsheet_row_unmatched",
                "match_method": "",
                "spreadsheet_order_number": spreadsheet_order,
                "slip_name": "",
                "slip_order_number": "",
                "output_sequence": "",
            })
            continue

        unused.remove(match_index)
        ordered_group_indices.append(match_index)
        slip = groups[match_index][0]
        if slip.order_number:
            matched_order_sequences[slip.order_number] = len(ordered_group_indices)
        report_rows.append({
            "spreadsheet_row": spreadsheet_row,
            "status": "matched",
            "match_method": method,
            "spreadsheet_order_number": spreadsheet_order,
            "slip_name": slip.shipping_name or slip.customer_name,
            "slip_order_number": slip.order_number,
            "output_sequence": len(ordered_group_indices),
        })

    unmatched_group_indices = sorted(unused)
    ordered_group_indices.extend(unmatched_group_indices)
    for index in unmatched_group_indices:
        slip = groups[index][0]
        report_rows.append({
            "spreadsheet_row": "",
            "status": "slip_not_in_spreadsheet",
            "match_method": "",
            "spreadsheet_order_number": "",
            "slip_name": slip.shipping_name or slip.customer_name,
            "slip_order_number": slip.order_number,
            "output_sequence": ordered_group_indices.index(index) + 1,
        })

    ordered_groups = [groups[index] for index in ordered_group_indices]
    ordered_groups = prioritize_single_line_items(ordered_groups, single_line_item_first)
    final_sequences = {g[0].order_number: n for n, g in enumerate(ordered_groups, 1)}
    for row in report_rows:
        if row["output_sequence"] != "":
            row["output_sequence"] = final_sequences[row["slip_order_number"]]
    sorted_slips_pdf = out_dir / "spreadsheet_sequence_packing_slips.pdf"
    write_selected_pages(
        packing_slips_pdf,
        sorted_slips_pdf,
        [page.page_index for group in ordered_groups for page in group],
    )
    outputs = {"spreadsheet_sequence_packing_slips": sorted_slips_pdf}

    labels, label_sources = parse_label_pdfs(label_pdfs)
    selected, label_report = match_labels_to_slips([group[0] for group in ordered_groups], labels)
    sorted_labels_pdf = out_dir / "spreadsheet_sequence_shipping_labels.pdf"
    write_sorted_labels(label_sources, sorted_labels_pdf, selected)
    outputs["spreadsheet_sequence_shipping_labels"] = sorted_labels_pdf

    match_report = out_dir / "spreadsheet_sequence_match_report.csv"
    pd.DataFrame(report_rows).to_csv(match_report, index=False)
    outputs["spreadsheet_sequence_match_report"] = match_report
    label_report_path = out_dir / "spreadsheet_sequence_label_report.csv"
    label_report.to_csv(label_report_path, index=False)
    outputs["spreadsheet_sequence_label_report"] = label_report_path
    return outputs


def missing_sort_field_warnings(
    groups: list[list[SlipPage]], preset: str, sort_fields: list[str] | None = None,
) -> list[dict]:
    """Check the same first-page keys used for sorting, not continuation pages."""
    product_fields = ["style", "color", "size"]
    fields = {
        "sort_slips": [*product_fields, "order_number"],
        "sort_labels": [*product_fields, "order_number"],
        "sort_both": [*product_fields, "order_number"],
        "sort_slips_name": [*product_fields, "last_name"],
        "sort_slips_custom": [*product_fields, "last_name", "custom_field"],
        "sort_slips_custom_first": ["custom_field", "last_name"],
        "required_field": ["required_field"],
        "custom_sort": sort_fields or ["last_name"],
    }.get(preset, [])
    labels = {"style": "style", "color": "color", "size": "size",
              "first_name": "recipient first name", "last_name": "recipient last name",
              "order_number": "order number", "custom_field": "custom field",
              "required_field": "recognizable birth year", "location": "location",
              "delivery_method": "delivery method", "sort_number": "sort number",
              "order_date": "order date"}
    warnings = []
    for group in groups:
        slip = group[0]
        missing = []
        for field in dict.fromkeys(fields):
            if field not in labels:
                continue
            if field == "required_field":
                value = _extract_birth_year(slip.required_field_value)
            elif field in {"first_name", "last_name"}:
                value = slip.sort_value_for_field(field)
            else:
                value = getattr(slip, "custom_field_value" if field == "custom_field" else field, "")
            # Unstructured header/store text is not a reliable recipient name.
            if not norm_text(value) or (
                field in {"first_name", "last_name"} and "," not in slip.shipping_name
            ):
                missing.append(labels[field])
        if missing:
            pages = [page.page_index + 1 for page in group]
            warnings.append({
                "sourcePages": pages,
                "orderNumber": slip.order_number,
                "missingFields": missing,
                "message": (
                    f"Could not reliably read {', '.join(missing)} on source page "
                    f"{pages[0]}. This order was kept, but its sort position may be incorrect. "
                    "Check these fields in the original packing-slip PDF and verify the output "
                    "before printing, or choose a sort that does not use them."
                ),
            })
        # Grouping itself depends on order numbers. A missing number may hide
        # a separate order inside an otherwise complete group.
        if fields:
            for page in group[1:]:
                if page.order_number:
                    continue
                page_marker = re.search(r"Page\s+(\d+)\s+of\s+\d+", page.raw_text, re.I)
                known_continuation = page_marker and int(page_marker.group(1)) > 1
                totals_only = (
                    re.search(r"\btotal\b", page.raw_text, re.I)
                    and not any((page.style, page.color, page.size))
                )
                if known_continuation or totals_only:
                    continue
                warnings.append({
                    "sourcePages": [page.page_index + 1],
                    "orderNumber": "",
                    "missingFields": ["order number"],
                    "message": (
                        f"Could not read an order number on source page {page.page_index + 1}. "
                        "This page was kept with the preceding order, but may be a separate order. "
                        "Check the original PDF and verify both grouping and sort position before printing."
                    ),
                })
    return warnings


def process_batch(
    packing_slips_pdf: str | Path,
    label_pdfs: list[str | Path],
    out_dir: str | Path,
    preset: str,
    sort_fields: list[str] | None = None,
    spreadsheet_path: str | Path | None = None,
    spreadsheet_name: str = "",
    spreadsheet_mapping: dict | None = None,
    store_export_path: str | Path | None = None,
    remove_column_indexes: list[int] | None = None,
    single_line_item_first: bool = False,
    preferred_style: str = "",
    preferred_color: str = "",
    warnings: list[dict] | None = None,
) -> dict[str, Path]:
    preferred_style, preferred_color = preferred_style.strip(), preferred_color.strip()
    if preferred_color and not preferred_style:
        raise ValueError("A preferred style is required when specifying a preferred color")
    if preferred_style and preset not in SUPPORTED_PRESETS:
        raise ValueError("Preferred products apply only to product-sorting presets")
    if single_line_item_first and preset in {"combine_labels", "match_labels", "parse_store_export"}:
        raise ValueError("Single-line-item priority is not available for this preset")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    sorting_presets = {
        "sort_slips", "sort_labels", "sort_both", "sort_slips_name",
        "sort_slips_custom", "sort_slips_custom_first", "custom_sort", "required_field",
    }
    groups = []
    if preset in sorting_presets:
        groups = group_slip_pages(parse_packing_slips(packing_slips_pdf))
        if preferred_style:
            selection_report = out_dir / "preferred_product_report.csv"
            pd.DataFrame(apply_product_preference(groups, preferred_style, preferred_color)).to_csv(selection_report, index=False)
            outputs["preferred_product_report"] = selection_report
        detected = missing_sort_field_warnings(groups, preset, sort_fields)
        if warnings is not None:
            warnings.extend(detected)

    if preset in {"combine_labels", "sort_labels", "sort_both"}:
        combined = out_dir / "combined_labels.pdf"
        combine_label_pdfs(label_pdfs, combined)
        outputs["combined_labels"] = combined

    if preset == "sort_slips_name":
        sorted_groups = sorted(groups, key=lambda g: g[0].sort_key_name)
        sorted_groups = prioritize_single_line_items(sorted_groups, single_line_item_first)
        sorted_slips_pdf = out_dir / "sorted_packing_slips.pdf"
        write_selected_pages(packing_slips_pdf, sorted_slips_pdf,
                             [s.page_index for g in sorted_groups for s in g])
        outputs["sorted_packing_slips"] = sorted_slips_pdf
        report_csv = out_dir / "custom_sort_report.csv"
        _write_custom_sort_report(sorted_groups, report_csv)
        outputs["custom_sort_report"] = report_csv

    if preset == "sort_slips_custom":
        sorted_groups = sorted(groups, key=lambda g: g[0].sort_key_custom)
        sorted_groups = prioritize_single_line_items(sorted_groups, single_line_item_first)
        sorted_slips_pdf = out_dir / "sorted_packing_slips.pdf"
        write_selected_pages(packing_slips_pdf, sorted_slips_pdf,
                             [s.page_index for g in sorted_groups for s in g])
        outputs["sorted_packing_slips"] = sorted_slips_pdf
        report_csv = out_dir / "custom_field_report.csv"
        _write_custom_field_report(sorted_groups, report_csv)
        outputs["custom_field_report"] = report_csv

    if preset == "sort_slips_custom_first":
        sorted_groups = sorted(groups, key=lambda g: g[0].sort_key_custom_first)
        sorted_groups = prioritize_single_line_items(sorted_groups, single_line_item_first)
        sorted_slips_pdf = out_dir / "sorted_packing_slips.pdf"
        write_selected_pages(packing_slips_pdf, sorted_slips_pdf,
                             [s.page_index for g in sorted_groups for s in g])
        outputs["sorted_packing_slips"] = sorted_slips_pdf
        report_csv = out_dir / "custom_field_report.csv"
        _write_custom_field_report(sorted_groups, report_csv)
        outputs["custom_field_report"] = report_csv

    if preset == "custom_sort":
        fields = sort_fields or ["last_name"]
        sorted_groups = sorted(groups, key=lambda g: g[0].build_sort_key(fields))
        sorted_groups = prioritize_single_line_items(sorted_groups, single_line_item_first)
        sorted_slips_pdf = out_dir / "sorted_packing_slips.pdf"
        write_selected_pages(packing_slips_pdf, sorted_slips_pdf,
                             [s.page_index for g in sorted_groups for s in g])
        outputs["sorted_packing_slips"] = sorted_slips_pdf
        report_csv = out_dir / "custom_sort_report.csv"
        _write_custom_sort_report(sorted_groups, report_csv)
        outputs["custom_sort_report"] = report_csv

    if preset == "required_field":
        sorted_groups = sorted(groups, key=lambda g: g[0].sort_key_required_field)
        sorted_groups = prioritize_single_line_items(sorted_groups, single_line_item_first)
        sorted_slips_pdf = out_dir / "sorted_packing_slips.pdf"
        write_selected_pages(packing_slips_pdf, sorted_slips_pdf,
                             [s.page_index for g in sorted_groups for s in g])
        outputs["sorted_packing_slips"] = sorted_slips_pdf
        report_csv = out_dir / "required_field_report.csv"
        _write_custom_sort_report(sorted_groups, report_csv)
        outputs["required_field_report"] = report_csv

    if preset == "split_required_field":
        outputs.update(split_packing_slips_by_required_field(packing_slips_pdf, out_dir, single_line_item_first))

    if preset == "spreadsheet_sequence":
        if not spreadsheet_path or not spreadsheet_mapping:
            raise ValueError("Spreadsheet and column mapping are required")
        outputs.update(
            sort_to_spreadsheet_sequence(
                packing_slips_pdf,
                label_pdfs,
                spreadsheet_path,
                spreadsheet_name,
                spreadsheet_mapping,
                out_dir,
                single_line_item_first,
            )
        )

    if preset == "parse_store_export":
        if not store_export_path:
            raise ValueError("A store export CSV is required")
        outputs["parsed_store_export"] = parse_store_export(
            store_export_path,
            out_dir,
            remove_column_indexes,
        )

    sorted_slips: list[SlipPage] | None = None
    if preset in {"sort_slips", "sort_labels", "sort_both"}:
        sorted_slips_pdf = out_dir / "sorted_packing_slips.pdf"
        sorted_slips = sort_packing_slips(packing_slips_pdf, sorted_slips_pdf, single_line_item_first, groups=groups)
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

    # Consolidation is a final formatting step, after sequencing and matching.
    # It never changes order grouping, label order, or the uploaded source PDF.
    from slip_consolidation import consolidate_packing_slips
    consolidation_rows = []
    for key, output_path in outputs.items():
        if output_path.suffix.lower() == ".pdf" and (
            key in ("sorted_packing_slips", "spreadsheet_sequence_packing_slips")
            or key.startswith("birth_year_")
        ):
            consolidation_rows.extend(consolidate_packing_slips(output_path))
    if consolidation_rows:
        consolidation_report = out_dir / "packing_slip_consolidation_report.csv"
        pd.DataFrame(consolidation_rows).to_csv(consolidation_report, index=False)
        outputs["packing_slip_consolidation_report"] = consolidation_report
        if "birth_year_batch_manifest" in outputs:
            manifest_path = outputs["birth_year_batch_manifest"]
            with manifest_path.open(newline="") as source:
                manifest_rows = list(csv.DictReader(source))
            output_counts = {}
            for row in consolidation_rows:
                key = (row["pdf"], row["order_number"])
                output_counts[key] = output_counts.get(key, 0) + row["output_pages"]
            for row in manifest_rows:
                row["output_page_count"] = output_counts.get(
                    (f"packing_slips_birth_year_{row['batch']}.pdf", row["order_number"]), ""
                )
            pd.DataFrame(manifest_rows).to_csv(manifest_path, index=False)

    zip_path = out_dir / "mint_sorter_parser_outputs.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, path in outputs.items():
            z.write(path, arcname=path.name)
    outputs["zip"] = zip_path
    return outputs
