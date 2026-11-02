import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from decimal import Decimal, localcontext

import menu
import quietlab as q
import units


class ConversionTests(unittest.TestCase):
    def test_exact_conversions(self):
        cases = [("1", "mi", "m", "1609.344"), ("12", "in", "ft", "1"),
                 ("1", "lb", "kg", "0.45359237"), ("1", "day", "h", "24"),
                 ("36", "km/h", "m/s", "10"), ("1", "kn", "km/h", "1.852"),
                 ("1", "B", "bit", "8"), ("1", "MiB", "MB", "1.048576"),
                 ("1", "GB", "MB", "1000"), ("1", "GiB", "MiB", "1024"),
                 ("32", "F", "C", "0"), ("212", "F", "C", "100"),
                 ("0", "C", "K", "273.15"), ("-40", "C", "F", "-40"),
                 ("-459.67", "F", "K", "0"), ("1/2", "h", "min", "30")]
        for value, source, target, expected in cases:
            with self.subTest(value=value, source=source, target=target):
                self.assertEqual(units.convert(value, source, target), expected)

    def test_aliases(self):
        self.assertEqual(units.convert("1", "公里", "米"), "1000")
        self.assertEqual(units.convert("1", "µm", "毫米"), "0.001")
        self.assertEqual(units.convert("0", "℃", "℉"), "32")

    def test_invalid_units_and_dimensions(self):
        for value, source, target in [("1", "m", "kg"), ("1", "unknown", "m"),
                                      ("1", "mb", "B"), ("1", "m" * 31, "m")]:
            with self.assertRaises(q.InputError):
                units.convert(value, source, target)

    def test_physical_bounds_and_range(self):
        for value, source, target in [("-1", "K", "C"), ("-273.16", "C", "K"),
                                      ("-459.68", "F", "K"),
                                      ("-273.150000000000000000000000000000000000000000001", "C", "K"),
                                      ("1e1000", "km", "m")]:
            with self.assertRaises(q.InputError):
                units.convert(value, source, target)

    def test_all_unit_pairs_roundtrip(self):
        with localcontext() as context:
            context.prec = 60
            for source, first in units.UNITS.items():
                for target, second in units.UNITS.items():
                    if first.dimension != second.dimension:
                        continue
                    converted = units.convert("100", source, target)
                    restored = Decimal(units.convert(converted, target, source))
                    self.assertLess(abs(restored - 100), Decimal("1e-34"), (source, target))

    def test_list_and_cli(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(units.main(["--list"]), 0)
            self.assertEqual(units.main(["36", "km/h", "m/s"]), 0)
        self.assertIn("数据量", output.getvalue())
        self.assertTrue(output.getvalue().endswith("10\n"))
        error = io.StringIO()
        with redirect_stderr(error):
            self.assertEqual(units.main(["1", "m", "s"]), 2)
        self.assertIn("不同维度", error.getvalue())

    def test_menu_conversion(self):
        output = io.StringIO()
        menu.main(io.StringIO("9\n36\nkm/h\nm/s\nq\n"), output)
        self.assertIn("10 m/s", output.getvalue())


if __name__ == "__main__":
    unittest.main()
