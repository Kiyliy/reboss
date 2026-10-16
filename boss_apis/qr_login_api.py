"""QR and mini-program contracts, with explicit approval before credential exchange."""
import time

from boss_apis.boss_api import BossAPI
from boss_apis.login_api import LoginAPI, require_success
from builder.header import HeaderBuilder
from builder.params import Params
from builder.request_plan import RequestPlan
from utils.http_client import ProtocolStopped


class QRLoginAPI(LoginAPI):
    @staticmethod
    def _plan(name, path, fields, *, effect):
        if any(not isinstance(value, str) and type(value) is not int for value in fields.values()):
            raise ValueError("QR query fields require observed scalar values")
        return RequestPlan(
            operation=name, method="GET", path=path,
            query=Params((key, str(value)) for key, value in fields.items()).encode(),
            headers=tuple(HeaderBuilder.build().get()), field_names=tuple(fields),
            effect=effect, provenance="shipped-login-contract; exchange unverified live",
        )

    @staticmethod
    def prepare_dispatch(state, *, pk, fp=None, extra=None):
        if state.get("phase") != "CONFIRMED_AWAITING_EXCHANGE" or state.get("confirmed") is not True:
            raise ProtocolStopped("A normal observed phone confirmation is required")
        QRLoginAPI._validate_context(pk, fp)
        fields = dict(extra or {})
        if any(name in fields for name in ("qrId", "uuid", "pk", "fp", "validate", "allweb")):
            raise ValueError("Extra fields cannot replace identifiers or invent proof")
        fields.update(qrId=state["qrId"], pk=pk)
        if fp is not None:
            fields["fp"] = fp
        return QRLoginAPI._plan(
            "qr_dispatch", "/wapi/zppassport/qrcode/dispatcher", fields,
            effect="AUTHENTICATION_OR_REGISTRATION",
        )

    @staticmethod
    def exchange(auth, state, plan, *, approval):
        is_app = state.get("phase") == "CONFIRMED_AWAITING_EXCHANGE" and state.get("confirmed") is True
        is_mp = state.get("phase") == "MP_SCANNED_AWAITING_EXCHANGE" and state.get("scaned") is True
        if not (is_app or is_mp):
            raise ProtocolStopped("No normal observed QR confirmation is available")
        expected = "/wapi/zppassport/qrcode/dispatcher" if is_app else "/wapi/zppassport/qrcode/loginConfirm"
        if plan.path != expected or plan.method != "GET":
            raise ValueError("The prepared exchange does not belong to this QR flow")
        from urllib.parse import parse_qs
        query = parse_qs(plan.query)
        key, value = ("qrId", state["qrId"]) if is_app else ("uuid", state["shortRandKey"])
        if query.get(key) != [value]:
            raise ValueError("The exchange identifier does not match this QR state")
        state["phase"] = "EXCHANGE_IN_FLIGHT"
        try:
            body = auth.ensure_http_session().execute_plan(plan, approval=approval)
            data = require_success(body)
            state.update(phase="EXCHANGE_RESPONSE_ACCEPTED", exchange_response_accepted=True)
            if data.get("commonDevice"):
                state["phase"] = "ADDITIONAL_VERIFICATION_REQUIRED"
                return QRLoginAPI.safe_status(state, auth=auth)
            BossAPI.get_user_info(auth)
        except (ProtocolStopped, ValueError):
            state["phase"] = "STOPPED"
            raise
        state["phase"] = "ACCOUNT_VERIFIED" if auth.status == "VERIFIED" else "SESSION_UNVERIFIED"
        state["credentials_exchanged"] = auth.status == "VERIFIED"
        return QRLoginAPI.safe_status(state, auth=auth)

    @staticmethod
    def create_mini_program(auth):
        session = auth.ensure_http_session()
        session.request("entry")
        require_success(session.json("bootstrap"))
        data = require_success(session.json("qr_create"))
        key = data.get("shortRandKey")
        if not isinstance(key, str) or not key:
            raise ProtocolStopped("Server did not return a mini-program short key")
        plan = QRLoginAPI._plan(
            "mp_code", "/wapi/zppassport/qrcode/getMpCode",
            {"uuid": key, "width": 200}, effect="READ",
        )
        code = require_success(session.execute_plan(plan))
        if not isinstance(code.get("mpCodeUrl"), str):
            raise ProtocolStopped("Server did not return a mini-program image URL")
        # Kept in a caller's private state, never printed or auto-downloaded.
        return {"phase": "MP_WAITING_FOR_SCAN", "shortRandKey": key,
                "mpCodeUrl": code["mpCodeUrl"], "scaned": False,
                "created_at": time.time(), "observer_requests": 0}

    @staticmethod
    def poll_mini_program(auth, state, *, now=None):
        if state.get("phase") != "MP_WAITING_FOR_SCAN":
            return state
        now = time.time() if now is None else now
        if now - state["created_at"] >= 180 or state.get("observer_requests", 0) >= 20:
            state["phase"] = "WAIT_WINDOW_ENDED"
            return state
        plan = QRLoginAPI._plan(
            "mp_scan", "/wapi/zppassport/qrcode/scanByMp",
            {"uuid": state["shortRandKey"]}, effect="READ",
        )
        state["observer_requests"] = state.get("observer_requests", 0) + 1
        try:
            body = auth.ensure_http_session().execute_plan(plan)
        except (ProtocolStopped, ValueError):
            state["phase"] = "STOPPED"
            raise
        if body.get("code") not in (None, 0):
            state["phase"] = "STOPPED"
            raise ProtocolStopped("Mini-program scan rejected")
        if type(body.get("scaned")) is not bool:
            state["phase"] = "STOPPED"
            raise ProtocolStopped("Unknown mini-program scan shape")
        if body.get("scaned") is True:
            state.update(phase="MP_SCANNED_AWAITING_EXCHANGE", scaned=True)
        return state

    @staticmethod
    def prepare_mini_program_confirm(state, *, pk, fp=None):
        if state.get("phase") != "MP_SCANNED_AWAITING_EXCHANGE" or state.get("scaned") is not True:
            raise ProtocolStopped("A normal mini-program scan must be observed first")
        QRLoginAPI._validate_context(pk, fp)
        fields = {"uuid": state["shortRandKey"], "pk": pk}
        if fp is not None:
            fields["fp"] = fp
        return QRLoginAPI._plan(
            "mp_login_confirm", "/wapi/zppassport/qrcode/loginConfirm", fields,
            effect="AUTHENTICATION_OR_REGISTRATION",
        )

    @staticmethod
    def _validate_context(pk, fp):
        if not isinstance(pk, str):
            raise ValueError("pk must come from the actual page context")
        if fp is not None and (not isinstance(fp, str) or not fp):
            raise ValueError("fp must be an actual browser-derived encoded value")

    @staticmethod
    def safe_status(state, *, auth=None):
        result = LoginAPI.safe_status(state)
        result.update(
            exchange_response_accepted=state.get("exchange_response_accepted", False),
            credentials_exchanged=state.get("credentials_exchanged", False),
            account_logged_in=(
                state.get("phase") == "ACCOUNT_VERIFIED"
                and auth is not None and auth.status == "VERIFIED"
            ),
        )
        return result
