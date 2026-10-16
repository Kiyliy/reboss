"""Version-specific normal SMS login contracts; no challenge solving or fabrication."""
from dataclasses import dataclass, field
import hashlib
import re
import time

from boss_apis.boss_api import BossAPI
from builder.form import sms_form
from builder.header import Header, ORIGIN, USER_AGENT
from builder.login_crypto import encode_login_value
from builder.request_plan import RequestPlan
from utils.http_client import ProtocolStopped

PROFILES = {"sign_v5333", "geek_spa_v6763"}
VARIANTS = {
    1: ("smsCodeV2", "phoneV2", ("challenge", "validate", "seccode"), "challenge"),
    2: ("smsCode", "phone", (), "csessionId"),
    3: ("smsCodeV3", "phoneV3", ("captcha", "randKey"), "captcha"),
    4: ("smsCodeByWy", "phoneByWy", ("validate",), "validate"),
}
PROTECTED_EXTRA = {
    "regionCode", "phone", "smsType", "purpose", "identity", "pk",
    "phoneCode", "encryptedAccount", "fp",
}


@dataclass(repr=False, frozen=True)
class VerificationMaterial:
    verify_type: int
    values: dict = field(repr=False)
    origin: str = "official-verification-sdk"

    def fields(self):
        if self.verify_type not in VARIANTS or type(self.verify_type) is not int:
            raise ValueError("Use the type returned by the official verification SDK")
        _, _, fields, gate = VARIANTS[self.verify_type]
        if not self.values.get(gate):
            raise ValueError("Normal verification has not supplied its required result")
        for name in fields:
            if not isinstance(self.values.get(name), str) or not self.values[name]:
                raise ValueError("Incomplete verification material")
        return {name: self.values[name] for name in fields}

    def __repr__(self):
        return f"VerificationMaterial(type={self.verify_type}, values=<redacted>)"


def login_headers(profile):
    referer = "/web/user/" if profile == "sign_v5333" else "/web/geek/jobs"
    return (
        Header().set_header("User-Agent", USER_AGENT)
        .set_header("Accept", "application/json, text/plain, */*")
        .set_header("Referer", ORIGIN + referer)
        .set_header("Content-Type", "application/x-www-form-urlencoded")
    )


def validate_phone(phone, region):
    if not isinstance(phone, str) or not re.fullmatch(r"\d{6,11}", phone.strip()):
        raise ValueError("The phone number format is not supported by the observed UI")
    if not isinstance(region, str) or not re.fullmatch(r"\+\d{1,4}", region):
        raise ValueError("Use an explicit international region code")
    phone = phone.strip()
    if region == "+86" and not re.fullmatch(r"1[3-9]\d{9}", phone):
        raise ValueError("Invalid mainland phone number format")
    return phone


class PhoneLoginAPI:
    def __init__(self, auth, *, profile):
        if profile not in PROFILES:
            raise ValueError("Choose sign_v5333 or geek_spa_v6763 explicitly")
        self.auth = auth
        self.profile = profile
        self.phase = "NEEDS_NORMAL_VERIFICATION"
        self.sms_token = ""
        self.cooldown_until = 0
        self._account_hash = None
        self._send_fingerprint = None
        self._login_fingerprint = None
        self._suggest_fingerprint = None
        self._send_verify_type = None
        self._send_purpose = None
        self._requested_purpose = None
        self._pending_login = None
        self._suggested_identity = None

    def _plan(self, name, path, fields):
        return RequestPlan(
            operation=name, method="POST", path=path,
            headers=tuple(login_headers(self.profile).get()),
            body=sms_form(fields), field_names=tuple(fields),
            effect="AUTHENTICATION_OR_REGISTRATION",
            provenance=f"{self.profile} static-contract; real SMS flow unverified",
        )

    def _fields(self, *, phone, region, purpose, pk, verification, send,
                code=None, fp=None, environment=None, extra=None):
        phone = validate_phone(phone, region)
        if type(purpose) is not int or purpose not in {0, 1}:
            raise ValueError("Purpose must be explicitly selected: 0 job seeker, 1 recruiter")
        if not isinstance(pk, str):
            raise ValueError("pk must come from the actual page context")
        fields = {"regionCode": region, "pk": pk, "smsType": 7, "purpose": purpose}
        if send:
            if self.profile == "sign_v5333":
                fields["version"] = 1
        else:
            if not isinstance(code, str) or not code.strip():
                raise ValueError("A user-provided SMS code is required")
            for key, value in (extra or {}).items():
                if key in PROTECTED_EXTRA:
                    raise ValueError("Extra fields cannot replace identity or verification inputs")
                fields[key] = value
            fields["phoneCode"] = code.strip()
        fields.update(verification.fields())
        if environment is not None:
            if not isinstance(environment, str) or not environment:
                raise ValueError("Use an observed environment value")
            fields["environment"] = environment
        # No plaintext phone is retained in the outbound plan.
        fields = {"encryptedAccount": encode_login_value(phone), **fields}
        if not send and fp is not None:
            if not isinstance(fp, str) or not fp:
                raise ValueError("fp must be a real browser-derived encoded value")
            fields["fp"] = fp
        account_hash = hashlib.sha256((region + "\0" + phone).encode()).hexdigest()
        return fields, account_hash

    def prepare_send(self, *, phone, verification, pk, purpose=0, region="+86",
                     now=None, environment=None):
        now = time.time() if now is None else now
        if now < self.cooldown_until:
            raise ProtocolStopped("Observed UI cooldown is still active")
        if self.phase not in {
            "NEEDS_NORMAL_VERIFICATION", "SMS_READY_FOR_REVIEW",
            "SMS_SENT_AWAITING_USER_CODE", "STOPPED",
        }:
            raise ProtocolStopped("Finish or discard the current login flow before preparing another")
        fields, account_hash = self._fields(
            phone=phone, region=region, purpose=purpose, pk=pk,
            verification=verification, send=True, environment=environment,
        )
        plan = self._plan(
            "phone_send_sms", "/wapi/zppassport/send/" + VARIANTS[verification.verify_type][0],
            fields,
        )
        self._account_hash = account_hash
        self._send_fingerprint = plan.fingerprint()
        self._send_verify_type = verification.verify_type
        self._send_purpose = purpose
        self._login_fingerprint = None
        self._suggest_fingerprint = None
        self._requested_purpose = None
        self._pending_login = None
        self._suggested_identity = None
        self.sms_token = ""
        self.phase = "SMS_READY_FOR_REVIEW"
        return plan

    def send_sms(self, plan, *, approval):
        if self.phase != "SMS_READY_FOR_REVIEW" or time.time() < self.cooldown_until:
            raise ProtocolStopped("SMS request is not pending review or cooldown is active")
        if plan.fingerprint() != self._send_fingerprint:
            raise ValueError("Send the exact reviewed SMS request from this flow")
        if self._send_verify_type == 2:
            raise ProtocolStopped("Type 2 SDK credential transport is unresolved; use official UI")
        self.phase = "SMS_REQUEST_IN_FLIGHT"
        try:
            response = self.auth.ensure_http_session().execute_plan(plan, approval=approval)
            self.record_sms_response(response)
        except (ProtocolStopped, ValueError):
            self.phase = "STOPPED"
            raise
        return self.safe_status()

    def record_sms_response(self, response, *, now=None):
        """Record a matching normal response, not evidence that an SMS was delivered."""
        if self.phase not in {"SMS_READY_FOR_REVIEW", "SMS_REQUEST_IN_FLIGHT"}:
            raise ProtocolStopped("No prepared SMS request is awaiting its response")
        if not isinstance(response, dict):
            self.phase = "STOPPED"
            raise ProtocolStopped("Unexpected SMS response shape")
        data = response.get("zpData")
        data = data if isinstance(data, dict) else {}
        if type(response.get("code")) is not int or response["code"] != 0 or data.get("errorType") == 4:
            self.phase = "STOPPED"
            raise ProtocolStopped("SMS was rejected or rate-limited; no automatic retry")
        if self.profile == "sign_v5333":
            token = data.get("token")
            self.sms_token = token if isinstance(token, str) else ""
        self.cooldown_until = (time.time() if now is None else now) + 60
        self.phase = "SMS_SENT_AWAITING_USER_CODE"
        return self.safe_status()

    def prepare_login(self, *, phone, code, verification, pk, terms_confirmed,
                      registration_acknowledged, purpose=0, region="+86",
                      fp=None, environment=None, extra=None):
        if terms_confirmed is not True or registration_acknowledged is not True:
            raise ProtocolStopped("Review terms and the possible first-login registration effect")
        if self.phase != "SMS_SENT_AWAITING_USER_CODE":
            raise ProtocolStopped("This flow has no successful SMS response")
        fields, account_hash = self._fields(
            phone=phone, region=region, purpose=purpose, pk=pk,
            verification=verification, send=False, code=code,
            fp=fp, environment=environment, extra=extra,
        )
        if account_hash != self._account_hash:
            raise ValueError("The SMS code must stay bound to the same requested account")
        if verification.verify_type != self._send_verify_type:
            raise ValueError("Verification type changed; use a fresh normal flow")
        if purpose != self._send_purpose:
            raise ValueError("Keep the explicitly selected purpose from the SMS request")
        login = self._plan(
            "phone_login", "/wapi/zppassport/login/" + VARIANTS[verification.verify_type][1],
            fields,
        )
        plans = []
        if self.profile == "sign_v5333":
            suggest = self._plan(
                "phone_login_suggest", "/wapi/zppassport/validate/getLoginSuggest",
                {"token": self.sms_token, "encryptedAccount": fields["encryptedAccount"],
                 "code": code.strip(), "regionCode": region},
            )
            self._suggest_fingerprint = suggest.fingerprint()
            plans.append(suggest)
        self._login_fingerprint = login.fingerprint()
        self._requested_purpose = purpose
        self._pending_login = login
        self.phase = "LOGIN_READY_FOR_REVIEW"
        plans.append(login)
        return tuple(plans)

    def submit_login(self, plans, *, approvals):
        if self.phase not in {"LOGIN_READY_FOR_REVIEW", "IDENTITY_REVIEWED"}:
            raise ProtocolStopped("No reviewed login sequence is pending; do not reuse a completed attempt")
        if not plans:
            raise ValueError("An explicit prepared login sequence is required")
        expected = [self._suggest_fingerprint, self._login_fingerprint]
        expected = [value for value in expected if value is not None]
        if [p.fingerprint() for p in plans] != expected or len(approvals) != len(plans):
            raise ValueError("Review and approve the exact planned login sequence")
        if self._send_verify_type == 2:
            raise ProtocolStopped("Type 2 SDK credential transport remains unresolved")
        self.phase = "LOGIN_REQUEST_IN_FLIGHT"
        try:
            for plan, approval in zip(plans, approvals):
                body = self.auth.ensure_http_session().execute_plan(plan, approval=approval)
                if type(body.get("code")) is not int or body["code"] != 0:
                    raise ProtocolStopped("Login step rejected; no retry or identity fallback")
                if plan.operation == "phone_login_suggest":
                    data = body.get("zpData") or {}
                    if isinstance(data, dict) and data.get("identity") is not None:
                        identity = data["identity"]
                        if type(identity) is not int or identity not in {0, 1}:
                            raise ProtocolStopped("Unknown suggested identity; use the official UI")
                        if identity != self._requested_purpose:
                            self.phase = "IDENTITY_REVIEW_REQUIRED"
                            self._suggested_identity = identity
                            return self.safe_status()
            self.phase = "LOGIN_RESPONSE_ACCEPTED"
            data = body.get("zpData") or {}
            if isinstance(data, dict) and data.get("commonDevice"):
                self.phase = "ADDITIONAL_VERIFICATION_REQUIRED"
                return self.safe_status()
            BossAPI.get_user_info(self.auth)
        except (ProtocolStopped, ValueError):
            self.phase = "STOPPED"
            raise
        self.phase = "ACCOUNT_VERIFIED" if self.auth.status == "VERIFIED" else "SESSION_UNVERIFIED"
        return self.safe_status()

    def review_identity(self, *, purpose, confirmed):
        """Confirm the requested role, without replacing it by the server's existing role."""
        if (self.phase != "IDENTITY_REVIEW_REQUIRED" or confirmed is not True
                or type(purpose) is not int or purpose not in {0, 1}
                or purpose != self._requested_purpose):
            raise ProtocolStopped("Explicit confirmation of the originally requested role is required")
        # The published UI warns about switching to the requested purpose. Its
        # callback does not rewrite the already-built request to the existing role.
        plan = self._pending_login
        self._suggest_fingerprint = None
        self._login_fingerprint = plan.fingerprint()
        self._pending_login = plan
        self._requested_purpose = purpose
        self.phase = "IDENTITY_REVIEWED"
        return (plan,)

    def safe_status(self):
        return {
            "profile": self.profile, "phase": self.phase,
            "account_logged_in": self.phase == "ACCOUNT_VERIFIED",
            "sms_token_present": bool(self.sms_token),
            "cooldown_until": self.cooldown_until,
            "credentials_in_report": False,
            "type2_implicit_transport_verified": False,
            "identity_review": (
                {"existing_identity": self._suggested_identity,
                 "requested_purpose": self._requested_purpose}
                if self.phase == "IDENTITY_REVIEW_REQUIRED" else None
            ),
        }
