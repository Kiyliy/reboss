import json
from pathlib import Path
import unittest

from builder.security_codec import (
    MAX_ELEMENTS,
    PartialCodecInputError,
    base64_bytes_18580,
    numeric_utf8_303,
    offset_transform_10702,
    utf16_units_15983,
    xor_mix_5810,
)


class PartialSecurityCodecTests(unittest.TestCase):
    def test_utf16_is_code_units_not_code_points_or_hash(self):
        self.assertEqual(utf16_units_15983("A你😀"), [65, 0x4F60, 0xD83D, 0xDE00])

    def test_unpaired_surrogates_are_preserved(self):
        self.assertEqual(utf16_units_15983("\ud800x\udfff"), [0xD800, 120, 0xDFFF])

    def test_repeated_xor_adds_three_before_mixing(self):
        self.assertEqual(xor_mix_5810([0, 1, 2], [48, 49]), [51, 53, 53])

    def test_intermediate_values_are_not_truncated_to_bytes(self):
        self.assertEqual(xor_mix_5810([255], [48]), [306])
        self.assertEqual(offset_transform_10702([306]), [316])
        self.assertEqual(numeric_utf8_303([316]), bytes.fromhex("c4bc"))
        self.assertEqual(base64_bytes_18580(bytes.fromhex("c4bc")), "xLw=")

    def test_offset_transform_preserves_order_and_large_values(self):
        self.assertEqual(
            offset_transform_10702([0, 1, 255, 256, 65535]),
            [10, 9, 263, 266, 65543],
        )

    def test_numeric_encoder_boundaries(self):
        self.assertEqual(
            numeric_utf8_303([0, 127, 128, 2047, 2048, 0xD800, 0xDFFF, 0xFFFF]),
            bytes.fromhex("007fc280dfbfe0a080eda080edbfbfefbfbf"),
        )

    def test_surrogate_units_are_not_combined_into_four_bytes(self):
        result = numeric_utf8_303(utf16_units_15983("😀"))
        self.assertEqual(result, bytes.fromhex("eda0bdedb880"))
        self.assertNotEqual(result, "😀".encode("utf-8"))

    def test_base64_padding_and_byte_domain(self):
        for values, expected in [
            ([], ""), ([0], "AA=="), ([0, 1], "AAE="), ([0, 1, 255], "AAH/")
        ]:
            with self.subTest(values=values):
                self.assertEqual(base64_bytes_18580(values), expected)
        with self.assertRaises(PartialCodecInputError):
            base64_bytes_18580("not the unreviewed string branch")

    def test_empty_key_is_explicitly_outside_this_model(self):
        with self.assertRaises(PartialCodecInputError):
            xor_mix_5810([1], [])

    def test_invalid_numeric_types_and_ranges_fail_without_echoing_values(self):
        for bad in [[True], [-1], [1.5], ["private-value"]]:
            for function in [offset_transform_10702, numeric_utf8_303, base64_bytes_18580]:
                with self.subTest(function=function.__name__, bad_type=type(bad[0]).__name__):
                    with self.assertRaises(PartialCodecInputError) as error:
                        function(bad)
                    self.assertNotIn("private-value", str(error.exception))
        for function in [offset_transform_10702, numeric_utf8_303]:
            with self.assertRaises(PartialCodecInputError):
                function([65536])
        with self.assertRaises(PartialCodecInputError):
            xor_mix_5810([256], [48])
        with self.assertRaises(PartialCodecInputError):
            base64_bytes_18580([256])

    def test_inputs_are_copied_not_mutated(self):
        data, key = [0, 1, 255], [48, 49]
        self.assertEqual(data, [0, 1, 255])
        xor_mix_5810(data, key)
        offset_transform_10702(data)
        numeric_utf8_303(data)
        base64_bytes_18580(data)
        self.assertEqual(data, [0, 1, 255])
        self.assertEqual(key, [48, 49])

    def test_local_size_limits_are_enforced(self):
        with self.assertRaises(PartialCodecInputError):
            offset_transform_10702([0] * (MAX_ELEMENTS + 1))
        with self.assertRaises(PartialCodecInputError):
            utf16_units_15983("😀" * (MAX_ELEMENTS // 2 + 1))

    def test_independent_js_synthetic_vectors(self):
        fixture_path = Path(__file__).parent / "fixtures/security_codec_vectors.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertFalse(fixture["target_code_executed"])
        self.assertFalse(fixture["real_session_values"])
        self.assertEqual(len(fixture["cases"]), 7)
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                units = utf16_units_15983(case["key"])
                mixed = xor_mix_5810(case["input"], units)
                transformed = offset_transform_10702(mixed)
                encoded = numeric_utf8_303(transformed)
                self.assertEqual(units, case["units"])
                self.assertEqual(mixed, case["mixed"])
                self.assertEqual(transformed, case["transformed"])
                self.assertEqual(list(encoded), case["encoded"])
                self.assertEqual(base64_bytes_18580(encoded), case["base64"])


if __name__ == "__main__":
    unittest.main()
