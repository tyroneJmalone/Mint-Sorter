import csv
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from processor import process_batch, parse_packing_slips, group_slip_pages
from line_items import prioritize_single_line_items
from slip_consolidation import text_overlay


def make_fixture(path):
    writer = PdfWriter()
    # Product quantities are deliberately high on single-line orders.
    for order, style, pages in [("101", "AA", [2]), ("103", "CC", [1, 0]),
                                ("102", "BB", [1, 1]), ("104", "DD", [1])]:
        for number, rows in enumerate(pages, 1):
            text = [(270, 756, 8.5, f"Page {number} of {len(pages)}  Order #{order}")]
            if rows:
                text.append((18, 18, 9, f"Name{order}, First"))
                text.extend((x, 200, 8, value) for x, value in [
                    (110, "Style #"), (200, "Product Name"), (350, "Size"),
                    (410, "Color"), (470, "Qty"), (510, "Price"), (550, "Extended")])
                for row in range(rows):
                    text.extend((x, 250 + row * 70, 8, value) for x, value in [
                        (110, style), (200, "Product"), (350, "S"), (410, "Blue"),
                        (470, "5"), (510, "$10.00"), (550, "$50.00")])
                    text.append((200, 263 + row * 70, 8, "Wrapped product description"))
            else:
                text.extend((18, 80 + i * 12, 8, value) for i, value in enumerate([
                    "Shipping: $0.00", "Handling: $0.00", "Tax: $0.00", "Order Total: $50.00",
                    "Payment Method", "Credit Card: $50.00"]))
            writer.add_page(text_overlay(612, 792, text))
    writer.write(path)


def order_sequence(path):
    return [g[0].order_number for g in group_slip_pages(parse_packing_slips(path))]


class SingleLinePriorityTests(unittest.TestCase):
    def test_counts_and_every_reordering_preset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pdf"
            make_fixture(source)
            groups = group_slip_pages(parse_packing_slips(source))
            self.assertEqual([[p.line_item_count for p in g] for g in groups],
                             [[2], [1, 0], [1, 1], [1]])
            sheet = root / "sequence.csv"
            sheet.write_text("Order Number\n102\n104\n101\n103\n")
            label_writer = PdfWriter()
            for order in ["101", "102", "103", "104"]:
                label_writer.add_page(text_overlay(612, 792, [
                    (18, 30, 10, f"SHIP NAME{order} FIRST"), (18, 45, 10, "TO:"),
                    (18, 60, 10, "123 Main St")]))
            labels = root / "labels.pdf"
            label_writer.write(labels)
            for preset in ["sort_slips", "sort_slips_name", "sort_slips_custom",
                           "sort_slips_custom_first", "custom_sort", "required_field",
                           "split_required_field", "sort_both", "sort_labels", "spreadsheet_sequence"]:
                with self.subTest(preset=preset):
                    kwargs = dict(sort_fields=["style", "color", "size", "last_name"],
                                  spreadsheet_path=sheet,
                                  spreadsheet_mapping={"order_number_column": "Order Number"})
                    key = ("birth_year_unknown" if preset == "split_required_field" else
                           "spreadsheet_sequence_packing_slips" if preset == "spreadsheet_sequence"
                           else "sorted_packing_slips")
                    off = process_batch(source, [labels], root / (preset + "-off"), preset, **kwargs)
                    on = process_batch(source, [labels], root / (preset + "-on"), preset,
                                       single_line_item_first=True, **kwargs)
                    baseline = order_sequence(off[key])
                    expected = [o for o in baseline if o in ("103", "104")] + [
                        o for o in baseline if o not in ("103", "104")]
                    self.assertEqual(order_sequence(on[key]), expected)
                    self.assertEqual(len(PdfReader(on[key]).pages), 5)
                    if preset in ("sort_both", "sort_labels", "spreadsheet_sequence"):
                        label_key = ("spreadsheet_sequence_shipping_labels" if preset == "spreadsheet_sequence"
                                     else "sorted_shipping_labels")
                        actual = [page.extract_text().splitlines()[0] for page in PdfReader(on[label_key]).pages]
                        self.assertEqual(actual, [f"SHIP NAME{o} FIRST" for o in expected])
                    if preset == "spreadsheet_sequence":
                        with on["spreadsheet_sequence_match_report"].open() as f:
                            rows = list(csv.DictReader(f))
                        self.assertEqual([r["slip_order_number"] for r in sorted(rows, key=lambda r: int(r["output_sequence"]))], expected)

    def test_unknown_counts_fail_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.pdf"
            make_fixture(source)
            groups = group_slip_pages(parse_packing_slips(source))
            groups[0][0].line_item_count = None
            self.assertEqual(prioritize_single_line_items(groups), groups)
            with self.assertRaisesRegex(ValueError, "Cannot reliably count"):
                prioritize_single_line_items(groups, True)


if __name__ == "__main__":
    unittest.main()
