#!/usr/bin/env python3
"""Complete one explicitly approved normal App QR login; never auto-retry."""
import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from boss_apis.qr_login_api import QRLoginAPI
from builder.auth import BossAuth
from builder.request_plan import ActionApproval
from utils.http_client import ProtocolStopped
from utils.private_state import load_private, save_private


class PageKeyParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("id") == "page_key_name":
            self.values.append(attrs.get("value", ""))

    def key(self):
        if len(self.values) > 1 or any(not isinstance(v, str) for v in self.values):
            raise ProtocolStopped("Page key context is ambiguous")
        # Published queryKa catches a missing #page_key_name and returns "".
        return self.values[0] if self.values else ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--auth-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--approve-exchange", action="store_true")
    parser.add_argument("--recheck-confirmation", action="store_true")
    args = parser.parse_args()
    if not args.approve_exchange:
        parser.error("The user's explicit approval for this cloud login is required")
    if args.private_dir.exists() or args.auth_output.exists():
        parser.error("Use new private capture and auth-output paths")
    saved = load_private(args.state)
    state = saved["challenge"]
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "provenance": "observed normal HTTP adapter; not a browser capture",
        "explicit_user_approval": True, "credential_exchange_attempted": False,
        "account_verified": False, "private_auth_saved": False,
        "browser_fingerprint_fabricated": False, "credentials_in_report": False,
    }
    captures = []
    with BossAuth.from_state(saved["auth"], live=True) as auth:
        session = auth.ensure_http_session()

        def capture(response):
            response.read()
            request = response.request
            name = f"request-{len(captures) + 1:02d}.json"
            save_private(args.private_dir / name, {
                "provenance": "observed HTTP adapter, not browser or wire capture",
                "networkRequest": {
                    "url": str(request.url), "method": request.method,
                    "requestHeaders": dict(request.headers),
                    "requestBody": request.content.decode("utf-8"),
                    "status": str(response.status_code),
                    "responseHeaders": dict(response.headers),
                    "responseBody": response.text,
                },
                "requestHeaderPairs": list(request.headers.multi_items()),
                "responseHeaderPairs": list(response.headers.multi_items()),
            })
            captures.append({
                "file": name, "path": request.url.path,
                "method": request.method, "status": response.status_code,
            })

        session.client.event_hooks["response"].append(capture)
        try:
            if args.recheck_confirmation:
                QRLoginAPI.reconcile_confirmation(auth, state, user_confirmed=True)
                save_private(args.state, {"schema_version": 1, "auth": auth.to_state(), "challenge": state})
            if state.get("phase") != "CONFIRMED_AWAITING_EXCHANGE":
                raise ProtocolStopped("The server has not confirmed this QR login")
            entry = session.request("entry")
            if len(entry.content) > 4 * 1024 * 1024:
                raise ProtocolStopped("Entry response exceeded the context inspection limit")
            context = PageKeyParser()
            context.feed(entry.text)
            plan = QRLoginAPI.prepare_dispatch(state, pk=context.key())
            report["page_context"] = {
                "source": "current normal entry HTML",
                "page_key_input_present": bool(context.values),
                "empty_fallback_used": not context.values,
                "fingerprint_available": False,
            }
            approval = ActionApproval.for_request(
                plan, confirmed=True,
                reason="User approved this cloud QR login and read-only account verification",
            )
            report["request_preview"] = plan.preview()
            report["credential_exchange_attempted"] = True
            result = QRLoginAPI.exchange(auth, state, plan, approval=approval)
            report["result"] = result
            report["account_verified"] = bool(result["account_logged_in"])
            if report["account_verified"]:
                auth.save(args.auth_output)
                report["private_auth_saved"] = True
        except (ProtocolStopped, ValueError) as error:
            report["stopped"] = str(error)
            report["result"] = QRLoginAPI.safe_status(state, auth=auth)
        finally:
            saved["auth"] = auth.to_state()
            save_private(args.state, saved)
            report["requests"] = session.events
            report["private_capture_count"] = len(captures)
            if args.private_dir.exists():
                save_private(args.private_dir / "index.json", {"captures": captures})
            save_private(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["account_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
