#!/usr/bin/env python3
"""BOSS adapter entrypoint. Default invocation is offline and has no side effects."""
import argparse
import json
import os
from pathlib import Path
import time

from boss_apis.boss_api import BossAPI
from boss_apis.login_api import LoginAPI, TERMINAL
from boss_apis.jobs_api import JobsAPI
from boss_apis.qr_login_api import QRLoginAPI
from boss_apis.surface_api import BossSurface
from builder.auth import BossAuth
from utils.http_client import ProtocolStopped
from utils.private_state import load_private, save_private

REFERENCE = {
    "repository": "https://github.com/cv-cat/DouYin_Spider",
    "commit": "fc8b9c2490a9561265425c26058290f01c064eda",
    "reuse": "architecture reference only; original BOSS implementation",
}


class Data_Spider:
    def __init__(self):
        self.boss_apis = BossAPI()
        self.login_apis = QRLoginAPI()

    def verify_session(self, auth):
        self.boss_apis.get_user_info(auth)
        return auth.safe_status()

    def capabilities(self):
        observed = self.historical_observations()
        unverified = [
            "authenticated_job_api", "browser_curl_full_equivalence",
            "dynamic_stoken_generation", "dynamic_validation_server_acceptance",
            "real_sms_delivery_and_login", "mini_program_account_login",
            "logout_server_revocation", "complete_server_api_coverage",
            "other_accounts_and_future_sessions",
        ]
        if not observed["normal_app_qr_login"]:
            unverified += ["real_account_login", "dispatcher_exchange"]
        return {
            "reference": REFERENCE,
            "default_mode": "offline",
            "implemented": [
                "scoped_cookie_persistence", "user_info_probe",
                "normal_qr_challenge", "scan_confirmation_observer",
                "captured_get_curl_replay",
                "grouped_evidence_backed_api_catalog", "dry_run_request_plans",
                "versioned_phone_login_contracts", "approved_qr_exchange",
                "mini_program_login_contracts", "job_search_and_detail_plans",
                "approved_logout_and_session_recheck",
                "spa_trace_id_source_level_reconstruction",
            ],
            "not_verified": unverified,
            "historical_live_observations": observed,
            "automatic_messages_or_applications": False,
            "catalog": self.catalog_summary(),
        }

    @staticmethod
    def catalog_summary():
        with BossAuth() as auth:
            return BossSurface(auth).summary()

    @staticmethod
    def historical_observations():
        reports = Path(__file__).resolve().parent / "reports"

        def load(name):
            try:
                value = json.loads((reports / name).read_text(encoding="utf-8"))
                return value if isinstance(value, dict) else {}
            except (OSError, ValueError):
                return {}

        qr = load("qr-login-current.json")
        persistence = load("auth-persistence-current.json")
        replay = load("replay-authenticated-user-info.json")
        jobs = load("jobs-current.json")
        job_codes = [
            item.get("application_code") for item in jobs.get("requests", [])
            if item.get("operation") == "geek_search_joblist"
        ]
        return {
            "normal_app_qr_login": qr.get("account_verified") is True,
            "fresh_process_account_recheck": persistence.get("account_logged_in") is True,
            "authenticated_account_curl_response_match": (
                replay.get("replay_application_code") == 0
                and replay.get("comparison", {}).get("response_utf8_bytes_match") is True
            ),
            "last_job_probe_business_code": job_codes[-1] if job_codes else None,
            "authenticated_job_search_verified": jobs.get("search_verified") is True,
            "dynamic_validation_solved": False,
            "validates_current_session": False,
            "scope": "single recorded run; not browser fingerprint or whole-site equivalence",
        }


def qr_payload(auth, state):
    return {"schema_version": 1, "auth": auth.to_state(), "challenge": state}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", nargs="?", default="status",
        choices=["status", "catalog", "job-preview", "verify-session", "qr-create", "qr-watch"],
    )
    parser.add_argument("--state", type=Path)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--endpoint", help="Exact catalog path to describe, without any network request")
    parser.add_argument("--query", help="Search text for an offline job request preview")
    parser.add_argument("--city", default="")
    args = parser.parse_args()
    spider = Data_Spider()
    if args.action == "status":
        print(json.dumps(spider.capabilities(), ensure_ascii=False, indent=2))
        return 0
    if args.action in {"catalog", "job-preview"}:
        try:
            with BossAuth() as auth:
                if args.action == "catalog":
                    surface = BossSurface(auth)
                    result = surface.endpoint(args.endpoint).describe() if args.endpoint else surface.summary()
                else:
                    result = JobsAPI(auth).search(args.query, city=args.city).preview()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except ValueError as error:
            print(json.dumps({"status": "STOPPED", "error_type": type(error).__name__}))
            return 2
    if not args.live or not args.state:
        parser.error("Network actions require --live and a private --state path")
    if args.action == "qr-create" and (not args.image or args.state.exists()):
        parser.error("qr-create requires --image and a NEW state filename")
    if args.action == "qr-create" and args.image.exists():
        parser.error("Use a new image filename; do not overwrite a previous challenge")
    if args.action == "qr-watch" and not 1 <= args.seconds <= 90:
        parser.error("--seconds must be between 1 and 90")
    try:
        if args.action == "verify-session":
            with BossAuth.load(args.state, live=True) as auth:
                result = spider.verify_session(auth)
                auth.save(args.state)
        elif args.action == "qr-create":
            import qrcode
            with BossAuth(live=True) as auth:
                state = LoginAPI.create(auth)
                save_private(args.state, qr_payload(auth, state))
                args.image.parent.mkdir(parents=True, exist_ok=True)
                # Official component renders the server-issued uuid directly.
                qr = qrcode.QRCode(
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=9, border=4,
                )
                qr.add_data(state["qrId"])
                qr.make(fit=True)
                qr.make_image(fill_color="black", back_color="white").save(args.image)
                os.chmod(args.image, 0o600)
                result = LoginAPI.safe_status(state)
        else:
            saved = load_private(args.state)
            state = saved["challenge"]
            deadline = time.monotonic() + args.seconds
            with BossAuth.from_state(saved["auth"], live=True) as auth:
                try:
                    while state["phase"] not in TERMINAL:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            state["phase"] = "WAIT_WINDOW_ENDED"
                            break
                        LoginAPI.poll_once(auth, state, timeout=min(15, remaining))
                        save_private(args.state, qr_payload(auth, state))
                        if state["phase"] not in TERMINAL:
                            time.sleep(min(1, max(0, deadline - time.monotonic())))
                except ProtocolStopped as error:
                    state.update(phase="STOPPED", error=str(error))
                finally:
                    save_private(args.state, qr_payload(auth, state))
                result = LoginAPI.safe_status(state)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ProtocolStopped, ValueError, KeyError, OSError) as error:
        # Do not echo URL queries, private paths, cookie values, or JSON bodies.
        print(json.dumps({"status": "STOPPED", "error_type": type(error).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
