import tempfile
import unittest
import csv
import zipfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from slip_consolidation import consolidate_packing_slips, text_overlay


class ConsolidationTests(unittest.TestCase):
    def create_pdf(self, path, product_continuation=False, crowded=False, unknown=False,
                   inconsistent=False, empty_header=False):
        writer = PdfWriter()
        count = 3 if product_continuation else 2
        for n in range(1, count + 1):
            texts = [(270, 756, 8.5, f"Page {n} of {count}  Order #{'456' if inconsistent and n == count else '123'}")]
            if n < count:
                texts.extend([
                    (18, 250, 8.5, "Sort # Style # Product Name Size Color Qty Price Extended"),
                    (18, 290, 8.5, f"{n} ABC123 Genuine product row S Blue 1"),
                    (18, 737 if crowded else 690, 8.5, "Item Total: $20.00"),
                ])
            else:
                lines = [
                    "Shipping: $2.00", "Handling: $0.00", "Tax: $1.00",
                    "Order Total: $23.00", "Payment Method",
                    "E-certificate: $0.00", "Apple Pay: $23.00",
                ]
                if unknown:
                    lines.insert(0, "Special instruction: KEEP THIS PAGE")
                if empty_header:
                    lines.insert(0, "Sort # Style # Product Name Size Color Qty Price Extended")
                texts.extend((18, 15 + i * 11, 8.5, line) for i, line in enumerate(lines))
            writer.add_page(text_overlay(612, 792, texts))
        writer.write(path)

    def test_two_to_one_preserves_products_money_and_searchable_numbering(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "slips.pdf"
            self.create_pdf(path, empty_header=True)
            report = consolidate_packing_slips(path)
            pdf = PdfReader(path)
            self.assertEqual(len(pdf.pages), 1)
            text = pdf.pages[0].extract_text()
            for expected in ["Genuine product row", "Shipping: $2.00", "Tax: $1.00",
                             "Order Total: $23.00", "Apple Pay: $23.00", "Page 1 of 1"]:
                self.assertIn(expected, text)
            self.assertNotIn("Page 1 of 2", text)
            self.assertNotIn("E-certificate", text)
            self.assertEqual(report[0]["pages_removed"], 1)
            before = path.read_bytes()
            consolidate_packing_slips(path)
            self.assertEqual(before, path.read_bytes())

    def test_three_to_two_keeps_both_product_pages_and_renumbers_both(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "slips.pdf"
            self.create_pdf(path, product_continuation=True)
            consolidate_packing_slips(path)
            pdf = PdfReader(path)
            self.assertEqual(len(pdf.pages), 2)
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                self.assertIn("Genuine product row", text)
                self.assertIn(f"Page {i+1} of 2", text)
                self.assertNotIn("of 3", text)

    def test_unsafe_or_crowded_pages_are_byte_for_byte_unchanged(self):
        for kwargs in [dict(crowded=True), dict(unknown=True), dict(inconsistent=True)]:
            with self.subTest(**kwargs), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "slips.pdf"
                self.create_pdf(path, **kwargs)
                before = path.read_bytes()
                report = consolidate_packing_slips(path)
                self.assertEqual(path.read_bytes(), before)
                self.assertTrue(all(row["pages_removed"] == 0 for row in report))

    def test_processing_presets_consolidate_before_zip_and_keep_source(self):
        from processor import process_batch
        presets = ["sort_slips", "sort_slips_name", "sort_slips_custom",
                   "sort_slips_custom_first", "custom_sort", "required_field",
                   "split_required_field", "sort_both", "spreadsheet_sequence"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pdf"
            self.create_pdf(source)
            original = source.read_bytes()
            sheet = root / "sequence.csv"
            sheet.write_text("Order Number\n123\n")
            for preset in presets:
                with self.subTest(preset=preset):
                    outputs = process_batch(
                        source, [], root / preset, preset,
                        sort_fields=["style", "color", "size", "last_name"],
                        spreadsheet_path=sheet,
                        spreadsheet_mapping={"order_number_column": "Order Number"},
                    )
                    slip_key = ("birth_year_unknown" if preset == "split_required_field"
                                else "spreadsheet_sequence_packing_slips" if preset == "spreadsheet_sequence"
                                else "sorted_packing_slips")
                    self.assertEqual(len(PdfReader(outputs[slip_key]).pages), 1)
                    with zipfile.ZipFile(outputs["zip"]) as archive:
                        self.assertEqual(archive.read(outputs[slip_key].name), outputs[slip_key].read_bytes())
                        self.assertIn("packing_slip_consolidation_report.csv", archive.namelist())
                    if preset == "split_required_field":
                        with outputs["birth_year_batch_manifest"].open() as manifest:
                            row = next(csv.DictReader(manifest))
                        self.assertEqual(row["page_count"], "2")
                        self.assertEqual(row["output_page_count"], "1")
            self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
