#!/usr/bin/env python3
"""One authenticated search page and at most one returned job detail; no retries."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from boss_apis.boss_api import BossAPI
from boss_apis.jobs_api import JobsAPI
from builder.auth import BossAuth
from utils.http_client import ProtocolStopped
from utils.private_capture import PrivateCapture
from utils.private_state import save_private
from utils.response_shape import response_shape


def run_probe(auth, *, query, city, private_dir, include_detail=False):
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "provenance": "observed normal HTTP adapter; not a browser capture",
        "contract_profile": "geek_spa_v6763",
        "account_verified": False, "search_verified": False, "detail_verified": False,
        "workflow_verified": False, "credentials_in_report": False,
        "automatic_pagination": False, "messages_or_applications_sent": False,
        "detail_requested": include_detail, "request_previews": [],
        "response_schema_is_sample_only": True,
    }
    session = auth.ensure_http_session()
    with PrivateCapture(session, private_dir) as capture:
        try:
            BossAPI.get_user_info(auth)
            if auth.status != "VERIFIED":
                raise ProtocolStopped("Current account verification failed; no job calls made")
            report["account_verified"] = True
            jobs = JobsAPI(auth)
            plan = jobs.search(query, city=city, page=1, page_size=15)
            report["request_previews"].append(plan.preview())
            result = session.execute_plan(plan)
            report["search_response_shape"] = response_shape(result)
            if type(result.get("code")) is not int or result["code"] != 0:
                raise ProtocolStopped("Job search did not return business success")
            data = result.get("zpData")
            rows = data.get("jobList") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ProtocolStopped("Search response does not match the observed jobList contract")
            report.update(search_verified=True, returned_job_count=len(rows))
            if not include_detail:
                report["workflow_verified"] = True
            elif not rows:
                report["detail_not_attempted"] = "Search returned no jobs; no identifier was invented"
            else:
                first = rows[0] if isinstance(rows[0], dict) else {}
                security_id, lid = first.get("securityId"), first.get("lid", "")
                if not isinstance(security_id, str) or not security_id or not isinstance(lid, str):
                    raise ProtocolStopped("No supported detail identifier in the actual first result")
                detail_plan = jobs.detail(security_id, lid=lid)
                report["request_previews"].append(detail_plan.preview())
                detail = session.execute_plan(detail_plan)
                report["detail_response_shape"] = response_shape(detail)
                if type(detail.get("code")) is not int or detail["code"] != 0:
                    raise ProtocolStopped("Job detail did not return business success")
                detail_data = detail.get("zpData")
                job_info = detail_data.get("jobInfo") if isinstance(detail_data, dict) else None
                if not isinstance(job_info, dict) or not job_info:
                    raise ProtocolStopped("Detail response lacks an observed nonempty jobInfo object")
                report.update(detail_verified=True, workflow_verified=True)
        except (ProtocolStopped, ValueError) as error:
            report["stopped"] = str(error)
        report["requests"] = list(session.events)
        report["private_capture_count"] = len(capture.records)
        report["final_account_status"] = auth.status
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--city", default="")
    parser.add_argument("--include-detail", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("Explicit --live is required for the bounded read-only probe")
    with BossAuth.load(args.state, live=True) as auth:
        report = run_probe(
            auth, query=args.query, city=args.city, private_dir=args.private_dir,
            include_detail=args.include_detail,
        )
        auth.save(args.state)
    save_private(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["workflow_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
