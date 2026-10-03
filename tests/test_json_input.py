"""Literal JSON token regressions: already-parsed Python numbers hide data loss."""
from decimal import Decimal
import json
import unittest

from ste_promax.json_input import loads_json


class JsonInputTests(unittest.TestCase):
    def test_ordinary_values_keep_types_and_decimal_meaning(self):
        tokens = ["0.1", "1.25", "1.2345678901234567", "1e-300", "1e-320", "-0.0", "100.000", "1e2"]
        for token in tokens:
            with self.subTest(token=token):
                value = loads_json(token)
                self.assertIs(type(value), float)
                self.assertEqual(Decimal(str(value)), Decimal(token))
        self.assertEqual(loads_json('{"values":[0,true,null,"1e-400"]}'),
                         {"values": [0, True, None, "1e-400"]})
        self.assertEqual(loads_json("9007199254740993"), 9007199254740993)

    def test_underflow_overflow_and_precision_loss_have_locations(self):
        for token in ["1e-400", "-1e-400", "1e400", "9007199254740993.0",
                      "1.234567890123456789", "0.100000000000000000001"]:
            with self.subTest(token=token):
                with self.assertRaisesRegex(ValueError, r"input.series\[0\].values\[0\].*decimal value"):
                    loads_json('{"series":[{"values":[' + token + ']}]}')

    def test_nonstandard_constants_and_duplicate_keys_are_rejected(self):
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token), self.assertRaisesRegex(ValueError, "finite JSON number"):
                loads_json('{"value":' + token + '}')
        with self.assertRaisesRegex(ValueError, "Duplicate JSON field"):
            loads_json('{"claim":{"scope":"A","scope":"B"}}')

    def test_extreme_nesting_and_exponents_are_located_failures(self):
        for count in (66, 2000):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "nesting"):
                loads_json("[" * count + "0" + "]" * count)
        with self.assertRaises(ValueError):
            loads_json("1e999999999999999999999999999999999999999999")

    def test_all_fixture_numbers_are_supported_without_value_changes(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for source in (root / "examples/suite").glob("*.json"):
            with self.subTest(source=source.name):
                text = source.read_text(encoding="utf-8")
                self.assertEqual(loads_json(text), json.loads(text))


if __name__ == "__main__":
    unittest.main()
