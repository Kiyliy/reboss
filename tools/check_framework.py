#!/usr/bin/env python3
"""Run offline tests and optionally one fresh, anonymous user-info GET."""
import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from builder.auth import BossAuth
from main import Data_Spider, REFERENCE
from utils.http_client import ProtocolStopped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--live-anonymous", action="store_true")
    args = parser.parse_args()
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "reference": REFERENCE,
        "offline_tests": {
            "run": result.testsRun, "failures": len(result.failures),
            "errors": len(result.errors), "skipped": len(result.skipped),
            "passed": result.wasSuccessful(),
            "live_account_equivalence": False,
        },
        "anonymous_probe": {"executed": False},
    }
    if args.live_anonymous and result.wasSuccessful():
        with BossAuth(live=True) as auth:
            probe = {"executed": True, "fresh_empty_cookie_jar": True}
            try:
                probe["result"] = Data_Spider().verify_session(auth)
            except ProtocolStopped as error:
                probe["stopped"] = str(error)
            probe["requests"] = auth.ensure_http_session().events
            probe["credential_exchange_attempted"] = False
            report["anonymous_probe"] = probe
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not result.wasSuccessful():
        print(stream.getvalue(), file=sys.stderr)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
