"""Offline fixtures only: no real phone number, account, SMS or QR is used."""
import base64
from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from boss_apis.phone_login_api import PhoneLoginAPI, VerificationMaterial
from boss_apis.qr_login_api import QRLoginAPI
from boss_apis.jobs_api import JobsAPI
from boss_apis.account_api import AccountAPI
from boss_apis.surface_api import BossSurface, ContractIncomplete
from builder.auth import BossAuth
from builder.form import sms_form, spa_form, UNDEFINED
from builder.header import HeaderBuilder
from builder.login_crypto import encode_login_value, PUBLIC_LOGIN_KEY_B64
from builder.request_plan import RequestPlan, ActionApproval
from builder.params import Params
from main import main as cli_main, Data_Spider
from utils.http_client import ProtocolStopped

PHONE = "13800000000"  # Synthetic fixture; all transports below are local mocks.
ROOT = Path(__file__).resolve().parents[1]


class MockCase(unittest.TestCase):
    def make_auth(self, replies=()):
        replies, requests = iter(replies), []

        def handle(request):
            requests.append(request)
            value = next(replies)
            return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
        auth = BossAuth(transport=httpx.MockTransport(handle))
        self.addCleanup(auth.close)
        return auth, requests

    def proof(self, kind=4):
        values = {
            1: {"challenge": "fixture-challenge", "validate": "fixture-validate", "seccode": "fixture-seccode"},
            2: {"csessionId": "fixture-csession"},
            3: {"captcha": "fixture-captcha", "randKey": "fixture-rand"},
            4: {"validate": "fixture-validate"},
        }
        return VerificationMaterial(kind, values[kind], origin="offline-fixture")

    def approval(self, plan):
        return ActionApproval.for_request(plan, confirmed=True, reason="offline mock test")

    def sent_flow(self, profile="sign_v5333", replies=()):
        auth, requests = self.make_auth(replies)
        flow = PhoneLoginAPI(auth, profile=profile)
        flow.prepare_send(phone=PHONE, verification=self.proof(), pk="fixture-pk", now=1)
        flow.record_sms_response({"code": 0, "zpData": {"token": "fixture-sms-token"}}, now=1)
        return flow, requests


class SerializerTests(unittest.TestCase):
    def test_sms_rfc3986_and_base64_characters(self):
        self.assertEqual(sms_form({"regionCode": "+86", "account": "a+/=", "space": "a b"}),
                         b"regionCode=%2B86&account=a%2B%2F%3D&space=a%20b")

    def test_sms_arrays_null_and_undefined(self):
        self.assertEqual(sms_form({"x": ["a", "b"], "n": None, "u": UNDEFINED}),
                         b"x%5B0%5D=a&x%5B1%5D=b&n=")

    def test_spa_reverse_array_and_scalar_null(self):
        self.assertEqual(spa_form({"x": ["a", "b"], "n": None, "u": UNDEFINED}),
                         b"x[]=b&x[]=a&n=null&u=")

    def test_spa_encode_uri_component_punctuation(self):
        self.assertEqual(spa_form({"x": "!*'() +"}), b"x=!*'()%20%2B")

    def test_spa_rejects_unsafe_keys(self):
        with self.assertRaises(ValueError):
            spa_form({"a&evil": "x"})


class CryptoTests(unittest.TestCase):
    def test_iv_prefix_aes_cbc_utf8_padding(self):
        for value in ("fixture-phone", "中文", "", "0" * 16):
            encoded = encode_login_value(value, iv=bytes(range(16)))
            raw = base64.b64decode(encoded)
            self.assertEqual(raw[:16], bytes(range(16)))
            decryptor = Cipher(
                algorithms.AES(base64.b64decode(PUBLIC_LOGIN_KEY_B64)),
                modes.CBC(raw[:16]),
            ).decryptor()
            padded = decryptor.update(raw[16:]) + decryptor.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            self.assertEqual((unpadder.update(padded) + unpadder.finalize()).decode(), value)

    def test_fresh_iv_each_time(self):
        self.assertNotEqual(encode_login_value("fixture"), encode_login_value("fixture"))

    def test_no_wrong_iv_length(self):
        with self.assertRaises(ValueError):
            encode_login_value("fixture", iv=b"short")


class ApprovalTests(MockCase):
    def plan(self):
        return RequestPlan("logout", "POST", "/wapi/zppassport/user/logout",
                           effect="AUTHENTICATION_OR_REGISTRATION")

    def test_write_without_approval_never_calls_transport(self):
        auth, requests = self.make_auth()
        with self.assertRaises(ProtocolStopped):
            auth.ensure_http_session().execute_plan(self.plan())
        self.assertEqual(requests, [])

    def test_forged_read_classification_does_not_skip_gate(self):
        auth, requests = self.make_auth()
        with self.assertRaises(ProtocolStopped):
            auth.ensure_http_session().execute_plan(replace(self.plan(), effect="READ"))
        self.assertEqual(requests, [])

    def test_approval_binds_exact_body(self):
        auth, requests = self.make_auth()
        plan = self.plan()
        grant = self.approval(plan)
        with self.assertRaises(ValueError):
            auth.ensure_http_session().execute_plan(replace(plan, body=b"changed=1"), approval=grant)
        self.assertEqual(requests, [])

    def test_one_use_approval(self):
        auth, requests = self.make_auth([{"code": 0}])
        plan = self.plan()
        grant = self.approval(plan)
        auth.ensure_http_session().execute_plan(plan, approval=grant)
        with self.assertRaises(ValueError):
            auth.ensure_http_session().execute_plan(plan, approval=grant)
        self.assertEqual(len(requests), 1)

    def test_get_exchange_also_needs_approval(self):
        auth, requests = self.make_auth()
        plan = RequestPlan("qr", "GET", "/wapi/zppassport/qrcode/dispatcher",
                           query="qrId=fixture", effect="AUTHENTICATION_OR_REGISTRATION")
        with self.assertRaises(ProtocolStopped):
            auth.ensure_http_session().execute_plan(plan)
        self.assertEqual(requests, [])

    def test_preview_and_repr_redact_values(self):
        plan = RequestPlan("sms", "POST", "/wapi/zppassport/send/smsCodeByWy",
                           body=b"phoneCode=FIXTURE_SECRET", field_names=("phoneCode",))
        self.assertNotIn("FIXTURE_SECRET", str(plan))
        self.assertNotIn("FIXTURE_SECRET", json.dumps(plan.preview()))

    def test_encoded_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            RequestPlan("bad", "GET", "/wapi/%2e%2e/private")

    def test_headers_are_immutable(self):
        with self.assertRaises(ValueError):
            RequestPlan("bad", "GET", "/wapi/example", headers=[("Accept", "x")])

    def test_preview_does_not_trust_forged_read_label(self):
        self.assertTrue(replace(self.plan(), effect="READ").preview()["requires_approval"])

    def test_missing_business_code_stops_non_poll(self):
        auth, requests = self.make_auth([{"unexpected": True}])
        plan = RequestPlan("userinfo", "GET", "/wapi/zpuser/wap/getUserInfo.json", effect="READ")
        with self.assertRaises(ProtocolStopped):
            auth.ensure_http_session().execute_plan(plan)
        self.assertEqual(len(requests), 1)

    def test_spa_risk_codes_clear_old_login_observation(self):
        for code in (5002, 5003, 5004, 5012):
            auth, _ = self.make_auth([{"code": code}])
            auth.status, auth.application_token = "VERIFIED", "fixture-old"
            plan = RequestPlan("userinfo", "GET", "/wapi/zpuser/wap/getUserInfo.json", effect="READ")
            with self.assertRaises(ProtocolStopped):
                auth.ensure_http_session().execute_plan(plan)
            self.assertEqual(auth.status, "BLOCKED")
            self.assertEqual(auth.last_code, code)
            self.assertIsNone(auth.application_token)


class PhoneTests(MockCase):
    def test_profile_required_and_not_guessed(self):
        auth, _ = self.make_auth()
        with self.assertRaises(ValueError):
            PhoneLoginAPI(auth, profile="auto")

    def test_all_four_variant_paths_and_proof_fields(self):
        for kind, tail in ((1, "smsCodeV2"), (2, "smsCode"), (3, "smsCodeV3"), (4, "smsCodeByWy")):
            auth, requests = self.make_auth()
            flow = PhoneLoginAPI(auth, profile="sign_v5333")
            plan = flow.prepare_send(phone=PHONE, verification=self.proof(kind), pk="fixture")
            fields = parse_qs(plan.body.decode(), keep_blank_values=True)
            self.assertTrue(plan.path.endswith(tail))
            self.assertNotIn("phone", fields)
            self.assertNotIn("identity", fields)
            self.assertNotIn("csessionId", fields)
            self.assertEqual(fields["purpose"], ["0"])
            self.assertEqual(fields["version"], ["1"])
            self.assertEqual(requests, [])

    def test_spa_profile_does_not_add_v5333_fields(self):
        flow, _ = self.sent_flow(profile="geek_spa_v6763")
        self.assertFalse(flow.sms_token)
        plans = flow.prepare_login(phone=PHONE, code="fixture-code", verification=self.proof(),
                                   pk="fixture", terms_confirmed=True, registration_acknowledged=True)
        self.assertEqual(len(plans), 1)
        self.assertNotIn("token", plans[0].field_names)
        self.assertNotIn("version", plans[0].field_names)

    def test_suggest_uses_sms_token_but_final_login_does_not(self):
        flow, _ = self.sent_flow()
        plans = flow.prepare_login(phone=PHONE, code="fixture-code", verification=self.proof(),
                                   pk="fixture", terms_confirmed=True, registration_acknowledged=True)
        self.assertEqual(len(plans), 2)
        suggest, login = [parse_qs(plan.body.decode()) for plan in plans]
        self.assertEqual(suggest["token"], ["fixture-sms-token"])
        self.assertEqual(suggest["code"], ["fixture-code"])
        self.assertNotIn("token", login)
        self.assertNotIn("version", login)
        self.assertEqual(suggest["encryptedAccount"], login["encryptedAccount"])

    def test_sms_requires_normal_verification(self):
        auth, _ = self.make_auth()
        flow = PhoneLoginAPI(auth, profile="sign_v5333")
        with self.assertRaises(ValueError):
            flow.prepare_send(phone=PHONE, verification=VerificationMaterial(4, {}), pk="fixture")

    def test_type2_transport_remains_blocked(self):
        auth, requests = self.make_auth()
        flow = PhoneLoginAPI(auth, profile="sign_v5333")
        plan = flow.prepare_send(phone=PHONE, verification=self.proof(2), pk="fixture")
        with self.assertRaises(ProtocolStopped):
            flow.send_sms(plan, approval=self.approval(plan))
        self.assertEqual(requests, [])

    def test_sms_error_type_four_is_not_success(self):
        auth, _ = self.make_auth()
        flow = PhoneLoginAPI(auth, profile="sign_v5333")
        flow.prepare_send(phone=PHONE, verification=self.proof(), pk="fixture")
        with self.assertRaises(ProtocolStopped):
            flow.record_sms_response({"code": 0, "zpData": {"errorType": 4}})
        self.assertEqual(flow.phase, "STOPPED")

    def test_unsolicited_sms_response_cannot_advance_state(self):
        auth, _ = self.make_auth()
        flow = PhoneLoginAPI(auth, profile="sign_v5333")
        with self.assertRaises(ProtocolStopped):
            flow.record_sms_response({"code": 0})
        self.assertEqual(flow.phase, "NEEDS_NORMAL_VERIFICATION")

    def test_repeated_sms_response_cannot_extend_cooldown(self):
        flow, _ = self.sent_flow()
        with self.assertRaises(ProtocolStopped):
            flow.record_sms_response({"code": 0}, now=99)
        self.assertEqual(flow.cooldown_until, 61)

    def test_cooldown_prevents_another_prepare(self):
        flow, _ = self.sent_flow()
        with self.assertRaises(ProtocolStopped):
            flow.prepare_send(phone=PHONE, verification=self.proof(), pk="fixture", now=30)

    def test_registration_and_terms_require_explicit_review(self):
        flow, _ = self.sent_flow()
        with self.assertRaises(ProtocolStopped):
            flow.prepare_login(phone=PHONE, code="fixture", verification=self.proof(),
                               pk="fixture", terms_confirmed=False, registration_acknowledged=True)

    def test_different_phone_cannot_reuse_sms_flow(self):
        flow, _ = self.sent_flow()
        with self.assertRaises(ValueError):
            flow.prepare_login(phone="13900000000", code="fixture", verification=self.proof(),
                               pk="fixture", terms_confirmed=True, registration_acknowledged=True)

    def test_extra_fields_cannot_replace_encrypted_identity(self):
        flow, _ = self.sent_flow()
        with self.assertRaises(ValueError):
            flow.prepare_login(phone=PHONE, code="fixture", verification=self.proof(),
                               pk="fixture", terms_confirmed=True, registration_acknowledged=True,
                               extra={"encryptedAccount": "not-allowed"})

    def test_purpose_cannot_silently_change_between_sms_and_login(self):
        flow, _ = self.sent_flow()
        with self.assertRaises(ValueError):
            flow.prepare_login(phone=PHONE, code="fixture", verification=self.proof(),
                               pk="fixture", purpose=1,
                               terms_confirmed=True, registration_acknowledged=True)

    def test_mock_full_sms_sequence_requires_account_check(self):
        auth, requests = self.make_auth([
            {"code": 0, "zpData": {"token": "fixture-sms-token"}},
            {"code": 0, "zpData": {"identity": 0}},
            {"code": 0, "zpData": {}},
            {"code": 0, "zpData": {"userId": 123, "token": "fixture-app|suffix"}},
        ])
        flow = PhoneLoginAPI(auth, profile="sign_v5333")
        send = flow.prepare_send(phone=PHONE, verification=self.proof(), pk="fixture")
        flow.send_sms(send, approval=self.approval(send))
        plans = flow.prepare_login(phone=PHONE, code="fixture", verification=self.proof(),
                                   pk="fixture", terms_confirmed=True, registration_acknowledged=True)
        status = flow.submit_login(plans, approvals=[self.approval(p) for p in plans])
        self.assertEqual(status["phase"], "ACCOUNT_VERIFIED")
        self.assertEqual(len(requests), 4)
        self.assertEqual(dict(HeaderBuilder.build(auth, "https://www.zhipin.com/").get())["token"],
                         "fixture-app")

    def test_identity_switch_pauses_and_requires_fresh_approval(self):
        flow, requests = self.sent_flow(replies=[
            {"code": 0, "zpData": {"identity": 1}},
            {"code": 0, "zpData": {}},
            {"code": 7},
        ])
        plans = flow.prepare_login(phone=PHONE, code="fixture", verification=self.proof(),
                                   pk="fixture", terms_confirmed=True, registration_acknowledged=True)
        result = flow.submit_login(plans, approvals=[self.approval(p) for p in plans])
        self.assertEqual(result["phase"], "IDENTITY_REVIEW_REQUIRED")
        self.assertEqual(len(requests), 1)
        self.assertEqual(result["identity_review"], {"existing_identity": 1, "requested_purpose": 0})
        with self.assertRaises(ProtocolStopped):
            flow.review_identity(purpose=1, confirmed=True)
        reviewed = flow.review_identity(purpose=0, confirmed=True)
        self.assertEqual(plans[-1].fingerprint(), reviewed[0].fingerprint())
        self.assertEqual(parse_qs(reviewed[0].body.decode())["purpose"], ["0"])
        result = flow.submit_login(reviewed, approvals=[self.approval(reviewed[0])])
        self.assertEqual(result["phase"], "SESSION_UNVERIFIED")

    def test_common_device_stops_at_additional_verification(self):
        flow, requests = self.sent_flow(profile="geek_spa_v6763", replies=[
            {"code": 0, "zpData": {"commonDevice": True}},
        ])
        plans = flow.prepare_login(phone=PHONE, code="fixture", verification=self.proof(),
                                   pk="fixture", terms_confirmed=True, registration_acknowledged=True)
        result = flow.submit_login(plans, approvals=[self.approval(plans[0])])
        self.assertEqual(result["phase"], "ADDITIONAL_VERIFICATION_REQUIRED")
        self.assertFalse(result["account_logged_in"])
        self.assertEqual(len(requests), 1)

    def test_completed_login_cannot_be_replayed_with_new_approvals(self):
        flow, requests = self.sent_flow(profile="geek_spa_v6763", replies=[
            {"code": 0, "zpData": {}}, {"code": 0, "zpData": {"userId": 123}},
        ])
        plans = flow.prepare_login(phone=PHONE, code="fixture", verification=self.proof(),
                                   pk="fixture", terms_confirmed=True, registration_acknowledged=True)
        flow.submit_login(plans, approvals=[self.approval(p) for p in plans])
        with self.assertRaises(ProtocolStopped):
            flow.submit_login(plans, approvals=[self.approval(p) for p in plans])
        self.assertEqual(len(requests), 2)

    def test_failed_login_attempt_cannot_resume(self):
        flow, requests = self.sent_flow(replies=[httpx.Response(503, text="fixture")])
        plans = flow.prepare_login(phone=PHONE, code="fixture", verification=self.proof(),
                                   pk="fixture", terms_confirmed=True, registration_acknowledged=True)
        for _ in range(2):
            with self.assertRaises(ProtocolStopped):
                flow.submit_login(plans, approvals=[self.approval(p) for p in plans])
        self.assertEqual(flow.phase, "STOPPED")
        self.assertEqual(len(requests), 1)

    def test_unknown_identity_is_not_coerced_to_a_role(self):
        flow, requests = self.sent_flow(replies=[{"code": 0, "zpData": {"identity": True}}])
        plans = flow.prepare_login(phone=PHONE, code="fixture", verification=self.proof(),
                                   pk="fixture", terms_confirmed=True, registration_acknowledged=True)
        with self.assertRaises(ProtocolStopped):
            flow.submit_login(plans, approvals=[self.approval(p) for p in plans])
        self.assertEqual(flow.phase, "STOPPED")
        self.assertEqual(len(requests), 1)


class QRExchangeTests(MockCase):
    def app_state(self):
        return {"phase": "CONFIRMED_AWAITING_EXCHANGE", "confirmed": True,
                "qrId": "fixture-original", "secondQrId": "fixture-second"}

    def test_dispatch_uses_original_qr_and_not_first_scan_context_as_proof(self):
        plan = QRLoginAPI.prepare_dispatch(self.app_state(), pk="fixture")
        query = parse_qs(plan.query)
        self.assertEqual(query["qrId"], ["fixture-original"])
        self.assertNotIn("validate", query)
        self.assertNotIn("allweb", query)
        self.assertNotIn("fixture-original", json.dumps(plan.preview()))

    def test_unconfirmed_dispatch_rejected(self):
        with self.assertRaises(ProtocolStopped):
            QRLoginAPI.prepare_dispatch({"phase": "WAITING_FOR_SCAN"}, pk="")

    def test_late_confirmation_is_checked_once_not_assumed(self):
        auth, requests = self.make_auth([{"scaned": True, "login": True}])
        state = {
            "phase": "STOPPED", "error": "Transport stopped: ReadTimeout",
            "qrId": "fixture-original",
        }
        result = QRLoginAPI.reconcile_confirmation(auth, state, user_confirmed=True)
        self.assertEqual(result["phase"], "CONFIRMED_AWAITING_EXCHANGE")
        self.assertFalse(result["account_logged_in"])
        self.assertEqual(len(requests), 1)
        with self.assertRaises(ProtocolStopped):
            QRLoginAPI.reconcile_confirmation(auth, state, user_confirmed=True)

    def test_late_confirmation_cannot_resume_a_risk_stop(self):
        auth, requests = self.make_auth()
        state = {
            "phase": "STOPPED", "error": "Verification/risk code 35; no bypass or retry",
            "qrId": "fixture-original",
        }
        with self.assertRaises(ProtocolStopped):
            QRLoginAPI.reconcile_confirmation(auth, state, user_confirmed=True)
        self.assertEqual(requests, [])

    def test_user_confirmation_does_not_replace_server_confirmation(self):
        auth, requests = self.make_auth([{"scaned": False}])
        state = {"phase": "WAIT_WINDOW_ENDED", "qrId": "fixture-original"}
        result = QRLoginAPI.reconcile_confirmation(auth, state, user_confirmed=True)
        self.assertEqual(result["phase"], "CONFIRMATION_NOT_OBSERVED")
        self.assertFalse(result["account_logged_in"])
        self.assertEqual(len(requests), 1)

    def test_mismatched_identifier_rejected(self):
        auth, requests = self.make_auth()
        plan = QRLoginAPI.prepare_dispatch(self.app_state(), pk="fixture")
        plan = replace(plan, query="qrId=other&pk=fixture")
        with self.assertRaises(ValueError):
            QRLoginAPI.exchange(auth, self.app_state(), plan, approval=self.approval(plan))
        self.assertEqual(requests, [])

    def test_dispatch_success_is_not_enough_for_login(self):
        auth, _ = self.make_auth([{"code": 0, "zpData": {}}, {"code": 7}])
        state = self.app_state()
        plan = QRLoginAPI.prepare_dispatch(state, pk="fixture")
        result = QRLoginAPI.exchange(auth, state, plan, approval=self.approval(plan))
        self.assertFalse(result["account_logged_in"])

    def test_mini_program_uses_short_key(self):
        auth, requests = self.make_auth([
            httpx.Response(200, text="entry"),
            {"code": 0}, {"code": 0, "zpData": {"qrId": "different", "shortRandKey": "fixture-short"}},
            {"code": 0, "zpData": {"mpCodeUrl": "https://example.invalid/fixture.png"}},
            {"scaned": True},
        ])
        state = QRLoginAPI.create_mini_program(auth)
        self.assertIn(b"uuid=fixture-short", requests[3].url.query)
        QRLoginAPI.poll_mini_program(auth, state)
        plan = QRLoginAPI.prepare_mini_program_confirm(state, pk="fixture")
        self.assertEqual(parse_qs(plan.query)["uuid"], ["fixture-short"])

    def test_qr_exchange_failure_stops_retry(self):
        auth, requests = self.make_auth([{"code": 6}])
        state = self.app_state()
        plan = QRLoginAPI.prepare_dispatch(state, pk="fixture")
        for _ in range(2):
            with self.assertRaises(ProtocolStopped):
                QRLoginAPI.exchange(auth, state, plan, approval=self.approval(plan))
        self.assertEqual(state["phase"], "STOPPED")
        self.assertEqual(len(requests), 1)

    def test_qr_status_requires_current_account_observation(self):
        auth, _ = self.make_auth([{"code": 0}, {"code": 0, "zpData": {"userId": 123}}])
        state = self.app_state()
        plan = QRLoginAPI.prepare_dispatch(state, pk="fixture")
        result = QRLoginAPI.exchange(auth, state, plan, approval=self.approval(plan))
        self.assertTrue(result["account_logged_in"])
        self.assertTrue(result["credentials_exchanged"])
        self.assertFalse(QRLoginAPI.safe_status(state)["account_logged_in"])

    def test_mini_program_wait_window_is_not_server_ttl(self):
        auth, requests = self.make_auth()
        state = {"phase": "MP_WAITING_FOR_SCAN", "created_at": 1, "shortRandKey": "fixture"}
        QRLoginAPI.poll_mini_program(auth, state, now=182)
        result = QRLoginAPI.safe_status(state)
        self.assertEqual(result["phase"], "WAIT_WINDOW_ENDED")
        self.assertFalse(result["server_expiry_measured"])
        self.assertEqual(requests, [])

    def test_qr_context_is_not_coerced_from_missing_values(self):
        for pk, fp in ((None, None), ("fixture", ""), ("fixture", {"not": "a fingerprint"})):
            with self.assertRaises(ValueError):
                QRLoginAPI.prepare_dispatch(self.app_state(), pk=pk, fp=fp)


class SurfaceTests(MockCase):
    def test_every_catalog_path_has_a_named_adapter(self):
        auth, _ = self.make_auth()
        surface = BossSurface(auth)
        self.assertGreaterEqual(len(surface.contracts), 380)
        for contract in surface.contracts:
            group = getattr(surface, contract["group"])
            self.assertTrue(callable(getattr(group, contract["method_name"])))
            self.assertEqual(surface.endpoint(contract["path"]).describe()["path"], contract["path"])

    def test_unknown_contract_is_describable_not_silently_executed(self):
        auth, requests = self.make_auth()
        surface = BossSurface(auth)
        unknown = next(e for e in surface.contracts if not e["methods"])
        with self.assertRaises(ContractIncomplete):
            surface.endpoint(unknown["path"])(execute=True)
        self.assertEqual(requests, [])

    def test_search_is_post_form_and_defaults_to_dry_run(self):
        auth, requests = self.make_auth()
        plan = JobsAPI(auth).search("Python", city="101010100")
        self.assertEqual(plan.method, "POST")
        self.assertEqual(parse_qs(plan.body.decode())["query"], ["Python"])
        self.assertEqual(dict(plan.headers)["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual(requests, [])

    def test_page_two_requires_verified_account(self):
        auth, requests = self.make_auth()
        with self.assertRaises(ProtocolStopped):
            JobsAPI(auth).search("Python", page=2)
        self.assertEqual(requests, [])

    def test_search_filters_keep_comma_join(self):
        auth, _ = self.make_auth()
        plan = JobsAPI(auth).search("Python", filters={"salary": ["1", "2"]})
        self.assertEqual(parse_qs(plan.body.decode())["salary"], ["1,2"])

    def test_logout_is_protected_and_verifies_current_client(self):
        auth, requests = self.make_auth([{"code": 0}, {"code": 7}])
        plan = AccountAPI.prepare_logout(auth)
        result = AccountAPI.logout(auth, plan, approval=self.approval(plan))
        self.assertTrue(result["current_client_logged_out"])
        self.assertFalse(result["global_session_revocation_verified"])
        self.assertEqual(len(requests), 2)

    def test_unresolved_origin_stays_blocked(self):
        auth, requests = self.make_auth()
        surface = BossSurface(auth)
        row = next(c for c in surface.contracts if c["origin_status"] == "UNRESOLVED")
        with self.assertRaises(ContractIncomplete):
            surface.endpoint(row["path"])(execute=True)
        self.assertEqual(requests, [])

    def test_surface_does_not_mutate_callers_query(self):
        auth, _ = self.make_auth()
        query = Params().add("query", "fixture")
        endpoint = BossSurface(auth).endpoint("/wapi/zpgeek/job/detail.json")
        first = endpoint(params=query, cache_buster="one")
        second = endpoint(params=query, cache_buster="two")
        self.assertEqual(query.get(), [("query", "fixture")])
        self.assertEqual(parse_qs(first.query)["_"], ["one"])
        self.assertEqual(parse_qs(second.query)["_"], ["two"])

    def test_raw_capture_query_can_stay_unchanged(self):
        auth, _ = self.make_auth()
        raw = "securityId=fixture%2fvalue&a=&a=two"
        plan = BossSurface(auth).endpoint("/wapi/zpgeek/job/detail.json")(
            params=Params(raw=raw), cache_buster=False,
        )
        self.assertEqual(plan.query, raw)


class OfflineCliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        output = io.StringIO()
        with patch("sys.argv", ["main.py", *arguments]), redirect_stdout(output):
            status = cli_main()
        return status, json.loads(output.getvalue())

    def test_status_exposes_implemented_vs_verified(self):
        result = Data_Spider().capabilities()
        self.assertIn("approved_qr_exchange", result["implemented"])
        self.assertIn("other_accounts_and_future_sessions", result["not_verified"])
        self.assertFalse(result["historical_live_observations"]["validates_current_session"])
        self.assertFalse(result["catalog"]["all_endpoints_live_verified"])

    def test_catalog_works_without_live_or_state(self):
        status, result = self.run_cli("catalog")
        self.assertEqual(status, 0)
        self.assertEqual(result["discovered"], 387)

    def test_job_preview_works_offline_and_redacts_query(self):
        status, result = self.run_cli("job-preview", "--query", "fixture-private-query")
        self.assertEqual(status, 0)
        self.assertEqual(result["method"], "POST")
        self.assertNotIn("fixture-private-query", json.dumps(result))

    def test_unknown_catalog_entry_has_no_traceback_or_request(self):
        status, result = self.run_cli("catalog", "--endpoint", "/wapi/unknown")
        self.assertEqual(status, 2)
        self.assertEqual(result["status"], "STOPPED")


if __name__ == "__main__":
    unittest.main()
