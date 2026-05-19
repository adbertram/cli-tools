import unittest

from cli_tools_shared.filters import apply_filters


class FilterTests(unittest.TestCase):
    def test_gt_filter_compares_numeric_strings_as_numbers(self):
        items = [
            {"inventory_id": "low", "unit_price": "75.00"},
            {"inventory_id": "exact", "unit_price": "500.00"},
            {"inventory_id": "higher", "unit_price": "500.01"},
            {"inventory_id": "thousand", "unit_price": "1000.00"},
        ]

        filtered = apply_filters(items, ["unit_price:gt:500"])

        self.assertEqual(
            [item["inventory_id"] for item in filtered],
            ["higher", "thousand"],
        )


if __name__ == "__main__":
    unittest.main()
