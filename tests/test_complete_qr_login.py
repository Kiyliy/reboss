"""Synthetic fixtures only; the CLI receives a MockTransport, never a live account."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from builder.auth import BossAuth
from tools.complete_qr_login import PageKeyParser, main
from utils.http_client import ProtocolStopped
from utils.private_state import save_private


class PageContextTests(unittest.TestCase):
    def test_real_input_value_is_parsed(self):
        parser = PageKeyParser()
        parser.feed('<input id="page_key_name" value="fixture&amp;">')
        self.assertEqual(parser.key(), "fixture&")

    def test_missing_input_uses_published_empty_fallback(self):
        parser = PageKeyParser()
        parser.feed("<html>fixture</html>")
        self.assertEqual(parser.key(), "")

    def test_duplicate_inputs_stop_instead_of_guessing(self):
        parser = PageKeyParser()
        parser.feed('<input id="page_key_name" value="a"><input id="page_key_name" value="b">')
        with self.assertRaises(ProtocolStopped):
            parser.key()

    def test_script_content_is_not_an_input_value(self):
        parser = PageKeyParser()
        parser.feed('<script>const x = \'<input id="page_key_name" value="fake">\';</script>')
        self.assertEqual(parser.key(), "")


class CompletionCliTests(unittest.TestCase):
    def run_flow(self, replies):
        requests = []
        replies = iter(replies)

        def handle(request):
            requests.append(request)
            reply = next(replies)
            return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)

        auth = BossAuth(transport=httpx.MockTransport(handle))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            save_private(state, {
                "schema_version": 1, "auth": BossAuth().to_state(),
                "challenge": {"phase": "CONFIRMED_AWAITING_EXCHANGE",
                              "confirmed": True, "qrId": "fixture-private-qr"},
            })
            argv = ["complete_qr_login.py", "--state", str(state),
                    "--private-dir", str(root / "captures"), "--auth-output", str(root / "auth.json"),
                    "--report", str(root / "report.json"), "--approve-exchange"]
            output = io.StringIO()
            with patch("sys.argv", argv), patch(
                "tools.complete_qr_login.BossAuth.from_state", return_value=auth,
            ), redirect_stdout(output):
                status = main()
            report = json.loads(output.getvalue())
            self.assertNotIn("fixture-private-qr", output.getvalue())
            persisted = (root / "auth.json").exists()
            captured = len(list((root / "captures").glob("request-*.json")))
        return status, report, requests, persisted, captured

    def test_mock_full_completion_captures_privately_and_rechecks_account(self):
        status, report, requests, persisted, captured = self.run_flow([
            httpx.Response(200, text='<input id="page_key_name" value="fixture-pk">'),
            {"code": 0}, {"code": 0, "zpData": {"userId": 123}},
        ])
        self.assertEqual(status, 0)
        self.assertTrue(report["account_verified"])
        self.assertTrue(persisted)
        self.assertEqual(captured, 3)
        self.assertEqual(len(requests), 3)
        self.assertIn(b"pk=fixture-pk", requests[1].url.query)
        self.assertEqual(report["request_preview"]["body_field_names"], [])

    def test_failed_exchange_never_saves_verified_auth_or_retries(self):
        status, report, requests, persisted, captured = self.run_flow([
            httpx.Response(200, text="<html>fixture</html>"),
            {"code": 35},
        ])
        self.assertEqual(status, 2)
        self.assertFalse(report["account_verified"])
        self.assertFalse(persisted)
        self.assertEqual(captured, 2)
        self.assertEqual(len(requests), 2)


if __name__ == "__main__":
    unittest.main()
