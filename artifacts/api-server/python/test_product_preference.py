import csv
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfWriter, PdfReader
from processor import SlipPage, process_batch
from product_preference import apply_product_preference
from slip_consolidation import text_overlay


def slip(index, rows):
    return SlipPage(index, "123", "", "", "HAT", "Black", "OSFA", "", product_rows=rows)


class ProductPreferenceTests(unittest.TestCase):
    def test_matches_across_pages_first_match_and_exact_case_insensitive_values(self):
        rows = [dict(style="5000", color="Red", size="M"),
                dict(style="5000", color="Royal", size="L"),
                dict(style="5000", color="Royal", size="XL")]
        groups = [[slip(0, [dict(style="HAT", color="Black", size="OSFA")]), slip(1, rows)]]
        report = apply_product_preference(groups, " 5000 ", " royal ")
        self.assertEqual((groups[0][0].style, groups[0][0].color, groups[0][0].size), ("5000", "Royal", "L"))
        self.assertEqual((report[0]["source_page"], report[0]["product_row"]), (2, 2))
        # Style alone selects the first style match, not the later Royal row.
        group = [[slip(0, rows)]]
        apply_product_preference(group, "5000")
        self.assertEqual(group[0][0].color, "Red")
        group = [[slip(0, rows)]]
        report = apply_product_preference(group, "500", "Royal")
        self.assertEqual(group[0][0].style, "HAT")
        self.assertEqual(report[0]["selection"], "first product (no match)")

    def test_full_process_uses_selected_row_without_changing_pdf_items(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pdf"
            writer = PdfWriter()
            for order, rows in [
                ("101", [("HAT", "Black", "OSFA"), ("5000", "Royal", "L")]),
                ("102", [("5000", "Royal", "S")]),
                ("103", [("5000", "Red", "M")]),
            ]:
                texts = [(18, 20, 9, "Recipient, First"),
                         (410, 100, 8, "Delivery Method:"), (410, 115, 8, "Shipping"),
                         (270, 756, 8, f"Page 1 of 1 Order #{order}")]
                texts += [(x, 200, 8, value) for x, value in [
                    (110, "Style #"), (200, "Product Name"), (350, "Size"),
                    (410, "Color"), (470, "Qty"), (510, "Price")]]
                for n, (style, color, size) in enumerate(rows):
                    texts += [(x, 250 + n * 70, 8, value) for x, value in [
                        (110, style), (200, "Test Product"), (350, size),
                        (410, color), (470, "5"), (510, "$10.00")]]
                writer.add_page(text_overlay(612, 792, texts))
            writer.write(source)
            before = [p.extract_text() for p in PdfReader(source).pages]
            for preset in ("custom_sort", "sort_slips", "sort_slips_name", "sort_slips_custom"):
                out = process_batch(source, [], root / preset, preset,
                                    sort_fields=["delivery_method", "style", "color", "size"],
                                    preferred_style="5000", preferred_color="Royal")
                actual = [p.extract_text() for p in PdfReader(out["sorted_packing_slips"]).pages]
                self.assertEqual(actual, [before[2], before[1], before[0]])
                with out["preferred_product_report"].open() as f:
                    report = list(csv.DictReader(f))
                self.assertEqual([r["selection"] for r in report],
                                 ["preferred match", "preferred match", "first product (no match)"])
            prioritized = process_batch(source, [], root / "priority", "custom_sort",
                                        sort_fields=["style", "color", "size"], single_line_item_first=True,
                                        preferred_style="5000", preferred_color="Royal")
            self.assertEqual([p.extract_text() for p in PdfReader(prioritized["sorted_packing_slips"]).pages],
                             [before[2], before[1], before[0]])
            self.assertEqual([p.extract_text() for p in PdfReader(source).pages], before)


if __name__ == "__main__":
    unittest.main()
