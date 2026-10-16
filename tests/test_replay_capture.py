import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "tools/replay_capture.py"
spec = importlib.util.spec_from_file_location("replay_capture", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReplayTests(unittest.TestCase):
    def record(self):
        return {
            "method": "GET",
            "url": "https://www.zhipin.com/wapi/zpuser/wap/getUserInfo.json?a=1&a=2",
            "status": "200",
            "requestHeaders": {
                ":method": "GET", ":scheme": "https",
                ":authority": "www.zhipin.com",
                ":path": "/wapi/zpuser/wap/getUserInfo.json?a=1&a=2",
                "accept": "application/json",
                "cookie": "test-only=value",
            },
        }

    def test_preserves_url_and_cookie_in_private_config(self):
        text, names = module.build_config(self.record())
        self.assertIn("?a=1&a=2", text)
        self.assertIn("cookie: test-only=value", text)
        self.assertNotIn('header = ":method', text)
        self.assertIn("cookie", names)

    def test_no_post(self):
        record = self.record()
        record["method"] = "POST"
        with self.assertRaises(ValueError):
            module.build_config(record)

    def test_no_unrelated_origin(self):
        record = self.record()
        record["url"] = "https://example.com/"
        with self.assertRaises(ValueError):
            module.build_config(record)

    def test_no_pseudo_header_mismatch(self):
        record = self.record()
        record["requestHeaders"][":path"] = "/different"
        with self.assertRaises(ValueError):
            module.build_config(record)

    def test_get_dispatcher_is_not_read_only(self):
        record = self.record()
        record["url"] = "https://www.zhipin.com/wapi/zppassport/qrcode/dispatcher"
        with self.assertRaises(ValueError):
            module.build_config(record)

    def test_empty_header_preserved_and_defaults_suppressed(self):
        record = self.record()
        record["requestHeaders"]["x-empty"] = ""
        config, _ = module.build_config(record)
        self.assertIn('header = "x-empty;"', config)
        self.assertIn('header = "User-Agent:"', config)
        self.assertIn("globoff", config)

    def test_no_header_injection(self):
        record = self.record()
        record["requestHeaders"]["accept"] = "text/html\r\nInjected: true"
        with self.assertRaises(ValueError):
            module.build_config(record)

    def test_missing_body_never_passes(self):
        record = self.record()
        record["responseBody"] = module.BODY_UNAVAILABLE
        result = module.compare_response(record, b'{"code":0}', 200)
        self.assertFalse(result["verified_equivalent"])
        self.assertIsNone(result["response_json_match"])

    def test_alternate_missing_body_marker(self):
        record = self.record()
        record["responseBody"] = "<not available anymore>"
        result = module.compare_response(record, b'{"code":0}', 200)
        self.assertFalse(result["observed_response_body_available"])
        self.assertFalse(result["verified_equivalent"])

    def test_json_equal_not_byte_equal(self):
        record = self.record()
        record["responseBody"] = '{"code":0}'
        result = module.compare_response(record, b'{"code": 0}', 200)
        self.assertTrue(result["response_json_match"])
        self.assertFalse(result["response_utf8_bytes_match"])
        self.assertFalse(result["verified_equivalent"])

    def test_exact_response(self):
        record = self.record()
        record["responseBody"] = '{"code":0}'
        self.assertTrue(
            module.compare_response(record, b'{"code":0}', 200)["verified_equivalent"]
        )


if __name__ == "__main__":
    unittest.main()
