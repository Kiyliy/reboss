"""Synthetic source-level vectors only; no BOSS network or runtime execution."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from boss_apis.jobs_api import JobsAPI
from builder.auth import BossAuth
from builder.header import HeaderBuilder
from builder.trace_id import (
    _js_product_uint32, generate_trace_id, trace_checksum, valid_trace_id,
)

FIXTURES = Path(__file__).with_name("fixtures") / "trace_id_vectors.json"


class TraceIdTests(unittest.TestCase):
    def test_cross_language_vectors(self):
        records = json.loads(FIXTURES.read_text(encoding="utf-8"))
        self.assertEqual(records["provenance"], "synthetic JS Number arithmetic reference")
        self.assertFalse(records["target_runtime_executed"])
        self.assertGreaterEqual(len(records["vectors"]), 132)
        for row in records["vectors"]:
            with self.subTest(now=row["now_ms"]):
                value = generate_trace_id(now_ms=row["now_ms"], random_values=row["random_values"])
                self.assertEqual(value, row["expected"])
                self.assertTrue(valid_trace_id(value))

    def test_javascript_number_rounding_not_exact_integer_multiplication(self):
        self.assertEqual(_js_product_uint32(0x9E3779B1, 0x7FFFFFFF), 3788015616)
        self.assertNotEqual(
            _js_product_uint32(0x9E3779B1, 0x7FFFFFFF),
            (0x9E3779B1 * 0x7FFFFFFF) & 0xFFFFFFFF,
        )

    def test_lowercase_fixed_width_time_and_zero_entropy(self):
        value = generate_trace_id(now_ms=0, random_values=[0] * 6)
        self.assertEqual(len(value), 24)
        self.assertEqual(value[2:21], "0" * 19)

    def test_timestamp_keeps_last_thirteen_hex_digits(self):
        value = generate_trace_id(now_ms=1 << 52, random_values=[0] * 6)
        self.assertEqual(value[2:15], "0" * 13)

    def test_changed_checksum_is_invalid(self):
        value = generate_trace_id(now_ms=1, random_values=[0.5] * 6)
        changed = value[:-1] + ("0" if value[-1] != "0" else "1")
        self.assertFalse(valid_trace_id(changed))

    def test_invalid_trace_and_core(self):
        for value in (None, 123, "", "F-" + "0" * 21, "F-" + "0" * 22 + "\n"):
            self.assertFalse(valid_trace_id(value))
        for value in ("a" * 18, "A" * 19, "x" * 19, "0" * 19 + "\n"):
            with self.assertRaises(ValueError):
                trace_checksum(value)

    def test_invalid_time_rejected(self):
        for value in (-1, 1.0, True, 1 << 53, "100"):
            with self.assertRaises(ValueError):
                generate_trace_id(now_ms=value, random_values=[0] * 6)

    def test_bad_entropy_rejected(self):
        for values in ([0] * 5, [0] * 7, [1] * 6, [-0.1] * 6, [True] * 6,
                       [float("nan")] * 6, [float("inf")] * 6, ["0"] * 6):
            with self.assertRaises(ValueError):
                generate_trace_id(now_ms=1, random_values=values)

    def test_default_is_new_local_metadata(self):
        value = generate_trace_id()
        self.assertTrue(valid_trace_id(value))

    def test_header_generation_is_profile_specific(self):
        self.assertNotIn("traceId", dict(HeaderBuilder.build().get()))
        with patch("builder.trace_id.generate_trace_id", return_value="fixture-trace"):
            headers = dict(HeaderBuilder.build(trace_profile="geek_spa_v6763").get())
        self.assertEqual(headers["traceId"], "fixture-trace")
        for field in ("zp_token", "token", "Cookie", "__zp_stoken__"):
            self.assertNotIn(field, headers)
        with self.assertRaises(ValueError):
            HeaderBuilder.build(trace_profile="unknown")

    def test_job_plan_adds_metadata_without_claiming_authentication(self):
        with BossAuth() as auth:
            plan = JobsAPI(auth).search("synthetic-query")
            self.assertTrue(valid_trace_id(dict(plan.headers)["traceId"]))
            self.assertNotIn("Cookie", dict(plan.headers))
            self.assertEqual(auth.status, "UNKNOWN")
            self.assertFalse(plan.preview()["contains_values"])
            self.assertIsNone(auth._session)

    def test_one_immutable_plan_does_not_regenerate_header_on_preview(self):
        with BossAuth() as auth:
            plan = JobsAPI(auth).search("synthetic-query")
            before = plan.fingerprint()
            plan.preview()
            self.assertEqual(plan.fingerprint(), before)


if __name__ == "__main__":
    unittest.main()
