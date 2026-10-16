"""Normal QR flow up to phone confirmation; credential exchange is not enabled.

Provenance: BOSS user-login.5398946e.js, with a bounded diagnostic observer.
Uses the official one-second second-scan fallback, not a browser UI reconstruction.
"""
import time

from builder.params import Params
from utils.http_client import ProtocolStopped

TERMINAL = {
    "CONFIRMED_AWAITING_EXCHANGE", "CANCELLED", "WAIT_WINDOW_ENDED", "STOPPED",
}


def require_success(body):
    if body.get("code") != 0:
        raise ProtocolStopped("Application did not return success; no retry")
    data = body.get("zpData")
    return data if isinstance(data, dict) else {}


class LoginAPI:
    @staticmethod
    def create(auth, *, now=None):
        session = auth.ensure_http_session()
        session.request("entry")
        require_success(session.json("bootstrap"))
        data = require_success(session.json("qr_create"))
        qr_id = data.get("qrId")
        if not isinstance(qr_id, str) or not qr_id:
            raise ProtocolStopped("Server did not issue a usable QR identifier")
        return {
            "phase": "WAITING_FOR_SCAN",
            "qrId": qr_id,
            "created_at": time.time() if now is None else now,
            "confirmed": False,
            "credentials_exchanged": False,
            "observer_requests": 0,
        }

    @staticmethod
    def poll_once(auth, state, *, now=None, timeout=15):
        use_wall_clock = now is None
        now = time.time() if now is None else now
        phase = state["phase"]
        if phase in TERMINAL:
            return state
        if phase not in {"WAITING_FOR_SCAN", "WAITING_FOR_CONFIRMATION"}:
            raise ProtocolStopped("Unknown QR state")
        if state.get("observer_requests", 0) >= 20:
            state["phase"] = "WAIT_WINDOW_ENDED"
            return state
        if phase == "WAITING_FOR_SCAN":
            remaining = 30 - (now - state["created_at"])
            if remaining <= 0:
                # This is the frontend wait window, not measured server expiry.
                state["phase"] = "WAIT_WINDOW_ENDED"
                return state
            session = auth.ensure_http_session()
            state["observer_requests"] += 1
            body = session.json(
                "qr_scan", params=Params().add("uuid", state["qrId"]),
                timeout=min(timeout, remaining),
            )
            if body.get("code") not in (None, 0):
                raise ProtocolStopped("Scan rejected; stopped")
            if body.get("scaned") is True:
                data = require_success(session.json(
                    "qr_second_key", params=Params().add("uuid", state["qrId"])
                ))
                second = data.get("qrId")
                if not isinstance(second, str) or not second:
                    raise ProtocolStopped("Missing second-phase QR identifier")
                state.update(
                    phase="WAITING_FOR_CONFIRMATION", secondQrId=second,
                    confirmation_ready_at=(
                        time.time() if use_wall_clock else now
                    ) + 1,
                )
        else:
            if now < state.get("confirmation_ready_at", 0):
                return state
            session = auth.ensure_http_session()
            state["observer_requests"] += 1
            body = session.json(
                "qr_confirm", params=Params().add("qrId", state["qrId"]),
                timeout=timeout,
            )
            if body.get("code") not in (None, 0):
                raise ProtocolStopped("Confirmation rejected; stopped")
            if body.get("scaned") is True:
                if not isinstance(body.get("login"), bool):
                    raise ProtocolStopped("Unknown confirmation shape")
                state["confirmed"] = body["login"]
                state["phase"] = (
                    "CONFIRMED_AWAITING_EXCHANGE" if body["login"] else "CANCELLED"
                )
        return state

    @staticmethod
    def safe_status(state):
        return {
            "phase": state["phase"],
            "app_confirmation_observed": state.get("confirmed", False),
            "credentials_exchanged": False,
            "account_logged_in": False,
            "server_expiry_measured": False,
            "error": state.get("error"),
        }
