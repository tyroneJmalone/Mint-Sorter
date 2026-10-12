import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from processor import SlipPage, group_slip_pages, missing_sort_field_warnings, process_batch


def slip(index=0, order="123", **fields):
    values = dict(page_index=index, order_number=order, customer_name="",
                  shipping_name="Abbott, Ashley", style="BP36", color="Black",
                  size="OSFA", raw_text="", custom_field_value="Team A",
                  required_field_value="2016")
    values.update(fields)
    return SlipPage(**values)


class SortWarningTests(unittest.TestCase):
    def test_selected_fields_only(self):
        groups = [[slip(style="", color="", size="", shipping_name="")]]
        for preset in ("sort_slips", "sort_labels", "sort_both"):
            self.assertEqual(missing_sort_field_warnings(groups, preset)[0]["missingFields"],
                             ["style", "color", "size"])
        for preset in ("sort_slips_name", "sort_slips_custom"):
            self.assertEqual(missing_sort_field_warnings(groups, preset)[0]["missingFields"],
                             ["style", "color", "size", "recipient last name"])
        self.assertEqual(missing_sort_field_warnings(groups, "sort_slips_custom_first")[0]["missingFields"],
                         ["recipient last name"])
        self.assertEqual(missing_sort_field_warnings(groups, "custom_sort", ["color"])[0]["missingFields"],
                         ["color"])
        for preset in ("combine_labels", "match_labels", "spreadsheet_sequence",
                       "split_required_field", "parse_store_export"):
            self.assertEqual(missing_sort_field_warnings(groups, preset), [])

    def test_complete_fields_and_unselected_missing_values(self):
        self.assertEqual(missing_sort_field_warnings([[slip()]], "sort_slips_name"), [])
        self.assertEqual(missing_sort_field_warnings([[slip(style="")]], "custom_sort", ["last_name"]), [])
        self.assertEqual(missing_sort_field_warnings([[slip(size="Unusual Size")]], "sort_slips"), [])

    def test_recipient_fallback_and_partial_names(self):
        for name, missing in [("Store Title", ["recipient first name", "recipient last name"]),
                              ("Abbott, ", ["recipient first name"]),
                              (", Ashley", ["recipient last name"])]:
            result = missing_sort_field_warnings([[slip(shipping_name=name)]], "custom_sort",
                                                ["first_name", "last_name"])
            self.assertEqual(result[0]["missingFields"], missing)

    def test_continuations_do_not_generate_false_warnings(self):
        continuation = slip(1, "", style="", color="", size="", shipping_name="", raw_text="Page 2 of 2")
        groups = group_slip_pages([slip(), continuation, slip(2, "456", color=" ")])
        result = missing_sort_field_warnings(groups, "sort_slips_name")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sourcePages"], [3])
        groups[0][0].style = ""
        self.assertEqual(missing_sort_field_warnings(groups, "sort_slips")[0]["sourcePages"], [1, 2])

    def test_warning_does_not_drop_or_split_orders(self):
        pages = [slip(style="Z"), slip(1, "", style="", color="", size="", shipping_name="", raw_text="Page 2 of 2"),
                 slip(2, "456", style="")]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input.pdf"
            writer = PdfWriter()
            for width in (100, 110, 120):
                writer.add_blank_page(width=width, height=200)
            with source.open("wb") as output:
                writer.write(output)
            for preset in ("sort_slips", "sort_slips_name", "sort_slips_custom",
                           "sort_slips_custom_first", "custom_sort"):
                with self.subTest(preset=preset), patch("processor.parse_packing_slips", return_value=pages):
                    warnings = []
                    outputs = process_batch(source, [], root / preset, preset,
                                            sort_fields=["style"], warnings=warnings)
                    widths = [int(page.mediabox.width) for page in PdfReader(outputs["sorted_packing_slips"]).pages]
                    self.assertEqual(sorted(widths), [100, 110, 120])
                    self.assertEqual(widths.index(110), widths.index(100) + 1)
                    if preset != "sort_slips_custom_first":
                        self.assertEqual(warnings[0]["sourcePages"], [3])

    def test_other_builtin_keys_and_ambiguous_grouping(self):
        for preset, field, expected in (
            ("sort_slips", "order_number", "order number"),
            ("sort_labels", "order_number", "order number"),
            ("sort_both", "order_number", "order number"),
            ("sort_slips_custom", "custom_field_value", "custom field"),
            ("sort_slips_custom_first", "custom_field_value", "custom field"),
            ("required_field", "required_field_value", "recognizable birth year"),
        ):
            page = slip()
            setattr(page, field, "")
            result = missing_sort_field_warnings([[page]], preset)
            self.assertEqual(result[0]["missingFields"], [expected])
            self.assertEqual(result[0]["sourcePages"], [1])
        self.assertEqual(missing_sort_field_warnings(
            [[slip(required_field_value="not a date")]], "required_field"
        )[0]["missingFields"], ["recognizable birth year"])
        groups = group_slip_pages([slip(), slip(1, "")])
        result = missing_sort_field_warnings(groups, "sort_slips")
        self.assertEqual(result[0]["sourcePages"], [2])
        self.assertIn("may be a separate order", result[0]["message"])

    def test_missing_builtin_keys_preserve_pages(self):
        pages = [slip(), slip(1, "", custom_field_value="", required_field_value="invalid")]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input.pdf"
            writer = PdfWriter()
            for _ in pages:
                writer.add_blank_page(width=100, height=200)
            with source.open("wb") as output:
                writer.write(output)
            for preset in ("sort_slips", "sort_slips_custom", "sort_slips_custom_first", "required_field"):
                with self.subTest(preset=preset), patch("processor.parse_packing_slips", return_value=pages):
                    warnings = []
                    outputs = process_batch(source, [], root / preset, preset, warnings=warnings)
                    self.assertEqual(len(PdfReader(outputs["sorted_packing_slips"]).pages), 2)
                    self.assertTrue(any(w["sourcePages"] == [2] for w in warnings))


if __name__ == "__main__":
    unittest.main()
