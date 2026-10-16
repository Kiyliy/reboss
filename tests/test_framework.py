"""Offline tests using httpx.MockTransport, not live BOSS login assertions."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import httpx

from boss_apis.boss_api import BossAPI
from boss_apis.login_api import LoginAPI
from builder.auth import BossAuth
from builder.header import Header, HeaderBuilder
from builder.params import Params
from main import Data_Spider
from utils.http_client import ProtocolStopped

ROOT = Path(__file__).resolve().parents[1]
USER_INFO = "https://www.zhipin.com/wapi/zpuser/wap/getUserInfo.json"


class MockCase(unittest.TestCase):
    def make_auth(self, replies):
        requests = []
        replies = iter(replies)

        def handle(request):
            requests.append(request)
            reply = next(replies)
            return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)

        auth = BossAuth(transport=httpx.MockTransport(handle))
        self.addCleanup(auth.close)
        return auth, requests


class ParamsTests(unittest.TestCase):
    def test_duplicates_empty_order(self):
        self.assertEqual(
            Params().add("a", "1").add("a", "2").add("empty", "").encode(),
            "a=1&a=2&empty=",
        )

    def test_raw_encoding_not_normalized(self):
        raw = "a=%2f&a=%2F&b=%20&c=+&empty="
        self.assertEqual(Params(raw=raw).encode(), raw)

    def test_raw_cannot_be_edited(self):
        with self.assertRaises(ValueError):
            Params(raw="a=%20").add("b", "2")

    def test_explicit_string_types(self):
        with self.assertRaises(TypeError):
            Params().add("count", 1)

    def test_query_fragment_rejected(self):
        with self.assertRaises(ValueError):
            Params(raw="a=1#secret")


class HeaderTests(unittest.TestCase):
    def test_header_injection_rejected(self):
        with self.assertRaises(ValueError):
            Header().set_header("Accept", "json\r\nX-Injected: true")

    def test_header_name_injection_rejected(self):
        with self.assertRaises(ValueError):
            Header().set_header("Bad:Name", "value")

    def test_case_insensitive_replacement(self):
        self.assertEqual(
            Header().set_header("Accept", "a").set_header("accept", "").get(),
            [("accept", "")],
        )


class AuthTests(MockCase):
    def test_cookie_presence_is_not_login(self):
        auth, _ = self.make_auth([httpx.Response(
            200, json={"code": 0}, headers=[
                ("set-cookie", "bst=test-only; Path=/; Secure; HttpOnly"),
                ("set-cookie", "scope=small; Path=/web/; Secure"),
                ("set-cookie", "old=gone; Path=/; Max-Age=0"),
            ],
        )])
        auth.ensure_http_session().json("bootstrap")
        self.assertIs(auth.ensure_http_session().client.cookies.jar, auth.cookies)
        self.assertFalse(auth.safe_status()["account_logged_in"])
        self.assertIn("bst=test-only", auth.cookie_header_for_url(USER_INFO))
        self.assertNotIn("scope=", auth.cookie_header_for_url(USER_INFO))
        self.assertNotIn("old=", auth.cookie_header_for_url(USER_INFO))

    def test_bst_header_is_derived_only_when_present(self):
        auth, _ = self.make_auth([httpx.Response(
            200, json={"code": 0},
            headers={"set-cookie": "bst=test-only; Path=/; Secure"},
        )])
        before = dict(HeaderBuilder.build(auth, USER_INFO).get())
        self.assertNotIn("zp_token", before)
        auth.ensure_http_session().json("bootstrap")
        after = dict(HeaderBuilder.build(auth, USER_INFO).get())
        self.assertEqual(after["zp_token"], "test-only")
        self.assertNotIn("token", after)
        self.assertNotIn("__zp_stoken__", after)

    def test_save_reload_preserves_cookie_attributes_not_login_claim(self):
        expiry = "Wed, 01 Jan 2031 00:00:00 GMT"
        auth, _ = self.make_auth([
            httpx.Response(200, json={"code": 0}, headers={
                "set-cookie": "sid=test-only; Path=/; Secure; HttpOnly; "
                "SameSite=Lax; Expires=" + expiry,
            }),
            {"code": 0, "zpData": {"userId": 123}},
        ])
        auth.ensure_http_session().json("bootstrap")
        BossAPI.get_user_info(auth)
        self.assertTrue(auth.safe_status()["account_logged_in"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            auth.save(path)
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            loaded = BossAuth.load(path)
            self.addCleanup(loaded.close)
            self.assertFalse(loaded.safe_status()["account_logged_in"])
            original = list(auth.cookies)[0]
            restored = list(loaded.cookies)[0]
            for name in ("domain", "path", "expires", "secure", "domain_specified"):
                self.assertEqual(getattr(original, name), getattr(restored, name))
            self.assertEqual(restored._rest, original._rest)
            self.assertEqual(loaded.cookie_header_for_url(USER_INFO), "sid=test-only")

    def test_foreign_cookie_scope_rejected(self):
        auth, _ = self.make_auth([httpx.Response(
            200, json={"code": 0},
            headers={"set-cookie": "sid=test-only; Path=/; Secure"},
        )])
        auth.ensure_http_session().json("bootstrap")
        state = auth.to_state()
        state["cookies"][0]["domain"] = "example.com"
        with self.assertRaises(ValueError):
            BossAuth.from_state(state)
        for url in ("https://example.com/", "http://www.zhipin.com/"):
            with self.assertRaises(ValueError):
                auth.cookie_header_for_url(url)

    def test_expired_cookie_not_restored(self):
        auth, _ = self.make_auth([httpx.Response(
            200, json={"code": 0},
            headers={"set-cookie": "sid=test-only; Path=/; Secure"},
        )])
        auth.ensure_http_session().json("bootstrap")
        state = auth.to_state()
        state["cookies"][0]["expires"] = int(time.time()) - 1
        loaded = BossAuth.from_state(state)
        self.assertEqual(list(loaded.cookies), [])

    def test_http_success_and_business_failure_not_login(self):
        auth, requests = self.make_auth([{"code": 7, "message": "session invalid"}])
        result = Data_Spider().verify_session(auth)
        self.assertEqual(result["account_status"], "INVALID")
        self.assertFalse(result["account_logged_in"])
        self.assertEqual(len(requests), 1)

    def test_missing_identity_not_login(self):
        for body in (
            {"code": 0, "zpData": {}},
            {"code": 0, "zpData": {"userId": 0}},
            {"code": 0, "zpData": {"userId": True}},
        ):
            auth, _ = self.make_auth([body])
            BossAPI.get_user_info(auth)
            self.assertFalse(auth.safe_status()["account_logged_in"])

    def test_user_id_and_success_mark_observed_account(self):
        auth, _ = self.make_auth([{"code": 0, "zpData": {"userId": "test-user"}}])
        BossAPI.get_user_info(auth)
        self.assertTrue(auth.safe_status()["account_logged_in"])
        self.assertNotIn("test-user", json.dumps(auth.safe_status()))

    def test_failed_recheck_does_not_keep_stale_success(self):
        auth, _ = self.make_auth([
            {"code": 0, "zpData": {"userId": 123}},
            httpx.Response(503),
        ])
        BossAPI.get_user_info(auth)
        self.assertTrue(auth.safe_status()["account_logged_in"])
        with self.assertRaises(ProtocolStopped):
            BossAPI.get_user_info(auth)
        self.assertFalse(auth.safe_status()["account_logged_in"])


class TransportTests(MockCase):
    def test_default_network_disabled(self):
        with BossAuth() as auth:
            with self.assertRaises(ProtocolStopped):
                BossAPI.get_user_info(auth)

    def test_dispatcher_is_not_an_ordinary_read_only_get(self):
        auth, requests = self.make_auth([])
        with self.assertRaises(ProtocolStopped):
            auth.ensure_http_session().request("dispatcher")
        self.assertEqual(requests, [])

    def test_redirect_not_followed(self):
        auth, requests = self.make_auth([httpx.Response(
            302, headers={"location": "https://example.com/"},
        )])
        with self.assertRaises(ProtocolStopped):
            auth.ensure_http_session().request("entry")
        self.assertEqual(len(requests), 1)

    def test_risk_stops_without_retry(self):
        auth, requests = self.make_auth([{"code": 35, "message": "verification"}])
        with self.assertRaises(ProtocolStopped):
            BossAPI.get_user_info(auth)
        self.assertEqual(auth.status, "BLOCKED")
        self.assertEqual(len(requests), 1)

    def test_non_json_stops(self):
        auth, _ = self.make_auth([httpx.Response(200, text="<html>verify</html>")])
        with self.assertRaises(ProtocolStopped):
            BossAPI.get_user_info(auth)

    def test_missing_business_code_stops(self):
        auth, _ = self.make_auth([{"zpData": {"userId": 123}}])
        with self.assertRaises(ProtocolStopped):
            BossAPI.get_user_info(auth)

    def test_boolean_code_is_not_numeric_success(self):
        auth, _ = self.make_auth([{"code": False, "zpData": {"userId": 123}}])
        with self.assertRaises(ProtocolStopped):
            BossAPI.get_user_info(auth)
        self.assertFalse(auth.safe_status()["account_logged_in"])

    def test_raw_query_sent_unchanged_for_ascii_capture(self):
        auth, requests = self.make_auth([{"scaned": False}])
        raw = "uuid=test%2Fonly&empty=&uuid=second"
        auth.ensure_http_session().json("qr_scan", params=Params(raw=raw))
        self.assertEqual(requests[0].url.query, raw.encode())

    def test_request_budget(self):
        auth, requests = self.make_auth([{"code": 7}])
        session = auth.ensure_http_session()
        session.request_limit = 1
        session.json("user_info")
        with self.assertRaises(ProtocolStopped):
            session.json("user_info")
        self.assertEqual(len(requests), 1)


class QRTests(MockCase):
    def challenge(self):
        return {
            "phase": "WAITING_FOR_SCAN", "qrId": "fixture-only-first",
            "created_at": 100, "confirmed": False,
            "credentials_exchanged": False, "observer_requests": 0,
        }

    def test_bootstrap_three_requests_not_login(self):
        auth, requests = self.make_auth([
            httpx.Response(200, text="<html></html>"),
            {"code": 0},
            {"code": 0, "zpData": {"qrId": "fixture-only-first"}},
        ])
        state = LoginAPI.create(auth, now=100)
        self.assertEqual([r.method for r in requests], ["GET", "POST", "POST"])
        self.assertEqual(state["phase"], "WAITING_FOR_SCAN")
        self.assertFalse(LoginAPI.safe_status(state)["account_logged_in"])
        self.assertFalse(auth.safe_status()["account_logged_in"])

    def test_bad_bootstrap_stops_before_challenge(self):
        auth, requests = self.make_auth([
            httpx.Response(200, text="ok"), {"code": 7},
        ])
        with self.assertRaises(ProtocolStopped):
            LoginAPI.create(auth, now=100)
        self.assertEqual(len(requests), 2)

    def test_create_requires_server_identifier(self):
        auth, _ = self.make_auth([
            httpx.Response(200, text="ok"), {"code": 0},
            {"code": 0, "zpData": {}},
        ])
        with self.assertRaises(ProtocolStopped):
            LoginAPI.create(auth, now=100)

    def test_unscanned_keeps_waiting(self):
        auth, requests = self.make_auth([{"scaned": False}])
        state = LoginAPI.poll_once(auth, self.challenge(), now=105)
        self.assertEqual(state["phase"], "WAITING_FOR_SCAN")
        self.assertEqual(requests[0].url.query, b"uuid=fixture-only-first")

    def test_wait_timeout_does_not_claim_server_expiry(self):
        state = LoginAPI.poll_once(BossAuth(), self.challenge(), now=131)
        self.assertEqual(state["phase"], "WAIT_WINDOW_ENDED")
        self.assertFalse(LoginAPI.safe_status(state)["server_expiry_measured"])

    def test_confirmation_does_not_exchange_or_authenticate(self):
        auth, requests = self.make_auth([
            {"scaned": True},
            {"code": 0, "zpData": {"qrId": "fixture-only-second"}},
            {"scaned": True, "login": True},
        ])
        state = self.challenge()
        LoginAPI.poll_once(auth, state, now=105)
        self.assertEqual(state["phase"], "WAITING_FOR_CONFIRMATION")
        LoginAPI.poll_once(auth, state, now=105.5)
        self.assertEqual(len(requests), 2)
        LoginAPI.poll_once(auth, state, now=107)
        result = LoginAPI.safe_status(state)
        self.assertTrue(result["app_confirmation_observed"])
        self.assertFalse(result["credentials_exchanged"])
        self.assertFalse(result["account_logged_in"])
        self.assertEqual(requests[-1].url.query, b"qrId=fixture-only-first")
        self.assertFalse(any("dispatcher" in r.url.path for r in requests))
        self.assertNotIn("fixture-only", json.dumps(result))

    def test_mobile_cancel_does_not_refresh_or_retry(self):
        auth, requests = self.make_auth([{"scaned": True, "login": False}])
        state = self.challenge()
        state["phase"] = "WAITING_FOR_CONFIRMATION"
        LoginAPI.poll_once(auth, state, now=105)
        self.assertEqual(state["phase"], "CANCELLED")
        LoginAPI.poll_once(auth, state, now=106)
        self.assertEqual(len(requests), 1)

    def test_ambiguous_confirmation_fails_closed(self):
        auth, _ = self.make_auth([{"scaned": True, "login": "true"}])
        state = self.challenge()
        state["phase"] = "WAITING_FOR_CONFIRMATION"
        with self.assertRaises(ProtocolStopped):
            LoginAPI.poll_once(auth, state, now=105)

    def test_bad_second_key_stops(self):
        auth, _ = self.make_auth([{"scaned": True}, {"code": 0, "zpData": {}}])
        with self.assertRaises(ProtocolStopped):
            LoginAPI.poll_once(auth, self.challenge(), now=105)

    def test_terminal_state_is_idempotent(self):
        auth, requests = self.make_auth([])
        state = self.challenge()
        state["phase"] = "CONFIRMED_AWAITING_EXCHANGE"
        old = deepcopy(state)
        LoginAPI.poll_once(auth, state, now=105)
        self.assertEqual(state, old)
        self.assertEqual(requests, [])


class CLITests(unittest.TestCase):
    def test_entrypoint_defaults_to_offline_report(self):
        process = subprocess.run(
            [sys.executable, str(ROOT / "main.py")],
            capture_output=True, text=True, timeout=15, cwd=ROOT,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["default_mode"], "offline")

    def test_live_flag_required(self):
        process = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), "qr-create",
             "--state", "never-created.json", "--image", "never-created.png"],
            capture_output=True, text=True, timeout=15, cwd=ROOT,
        )
        self.assertEqual(process.returncode, 2)
        self.assertFalse((ROOT / "never-created.json").exists())


if __name__ == "__main__":
    unittest.main()
