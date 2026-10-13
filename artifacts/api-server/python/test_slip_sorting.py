import unittest
from processor import SlipPage, apply_positioned_slip_fields, group_slip_pages, extract_positioned_delivery_method


def word(text, x, y, width=25):
    return dict(text=text, x0=x, x1=x + width, top=y, bottom=y + 8)


class Page:
    height = 792
    rects = [dict(x0=100, x1=160, top=210, bottom=280, height=70, width=60)]

    def extract_words(self, **kwargs):
        return [
            word("Style", 110, 198), word("Vendor", 170, 198),
            word("Product", 230, 198),
            word("Size", 350, 198), word("Color", 410, 198), word("Qty", 470, 198),
            word("BP36", 110, 235), word("OSFA", 350, 235),
            word("Oatmeal", 410, 231), word("Heather", 410, 241),
            word("-", 441, 241, 3), word("BP36", 448, 241, 20),
            word("Recipient", 419, 108, 45), word("First", 468, 108, 22),
            word("Ashley", 510, 108),
            word("Recipient", 419, 137, 45), word("Last", 468, 137, 22),
            word("Abbott", 510, 137),
            # A later product must not replace the first item's color or size.
            word("L151", 110, 310), word("S", 350, 310), word("Black", 410, 310),
        ]


def slip(index=0, order="123", style="", color="", size="", name="Store Title"):
    return SlipPage(index, order, "", name, style, color, size, "")


class SlipSortTests(unittest.TestCase):
    def test_delivery_column_does_not_include_neighboring_date_or_billing_name(self):
        words = [
            word("Delivery", 410, 130, 35), word("Method:", 448, 130, 35),
            word("Order", 18, 145), word("Date:", 50, 145),
            word("9/4/2026", 110, 145), word("BillingSurname,", 220, 145),
            word("Organization", 410, 145, 58), word("Pickup", 472, 145),
            word("Recipient", 410, 163), word("First", 460, 163),
            word("Name:", 410, 175),
        ]
        self.assertEqual(extract_positioned_delivery_method(words), "Organization Pickup")
        # Customer/date changes must not separate identical delivery groups.
        words[4]["text"] = "9/21/2026"
        words[5]["text"] = "DifferentSurname,"
        self.assertEqual(extract_positioned_delivery_method(words), "Organization Pickup")

    def test_wrapped_delivery_and_inline_delivery_values(self):
        header = [word("Delivery", 410, 130, 35), word("Method:", 448, 130, 35)]
        self.assertEqual(extract_positioned_delivery_method(header + [
            word("Organization", 410, 145), word("Pickup", 410, 156),
            word("Recipient", 410, 175)]), "Organization Pickup")
        self.assertEqual(extract_positioned_delivery_method(header + [
            word("Shipping", 490, 130)]), "Shipping")
        self.assertEqual(extract_positioned_delivery_method(header + [
            word("Recipient", 410, 145)]), "")

    def test_no_sort_number_column_wrapped_color_and_recipient(self):
        parsed = slip()
        apply_positioned_slip_fields(Page(), parsed)
        self.assertEqual((parsed.style, parsed.color, parsed.size, parsed.shipping_name),
                         ("BP36", "Oatmeal Heather", "OSFA", "Abbott, Ashley"))

    def test_preset_equals_custom_and_normalizes_case(self):
        items = [
            slip(0, style="L151", color="black", size="XL", name="Adams, Amy"),
            slip(1, style="L151", color="Black", size="S", name="Zulu, Zoe"),
            slip(2, style="L151", color="BLACK", size="S", name="Abbott, Ashley"),
            slip(3, style="BP36", color="Oatmeal", size="OSFA", name="Zulu, Zoe"),
        ]
        preset = sorted(items, key=lambda s: s.sort_key_name)
        custom = sorted(items, key=lambda s: s.build_sort_key(["style", "color", "size", "last_name"]))
        self.assertEqual([s.page_index for s in preset], [3, 2, 1, 0])
        self.assertEqual(preset, custom)

    def test_continuation_pages_stay_with_order(self):
        groups = group_slip_pages([slip(0), slip(1, order=""), slip(2, order="456")])
        self.assertEqual([[s.page_index for s in group] for group in groups], [[0, 1], [2]])


if __name__ == "__main__":
    unittest.main()
