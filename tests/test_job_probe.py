"""All examples use synthetic fixtures and a local MockTransport."""
import json
from pathlib import Path
import tempfile
import unittest

import httpx

from builder.auth import BossAuth
from tools.probe_jobs import run_probe
from utils.private_capture import PrivateCapture
from utils.response_shape import response_shape


class ShapeTests(unittest.TestCase):
    def test_values_never_appear_in_structural_sample(self):
        value = {"token": "FIXTURE_SECRET", "userId": 12345678,
                 "jobList": [{"jobName": "PRIVATE_TITLE", "securityId": "FIXTURE_ID"}]}
        shape = json.dumps(response_shape(value))
        for secret in ("FIXTURE_SECRET", "12345678", "PRIVATE_TITLE", "FIXTURE_ID"):
            self.assertNotIn(secret, shape)
        self.assertIn("securityId", shape)

    def test_dynamic_keys_and_hex_keys_are_omitted(self):
        shape = response_shape({"123456789": "secret", "abcdef0123456789": "secret",
                                "somebody@example.invalid": "secret", "jobList": []})
        self.assertEqual(list(shape["properties"]), ["jobList"])
        self.assertEqual(shape["omitted_dynamic_or_excess_keys"], 3)

    def test_depth_and_property_count_are_bounded(self):
        shape = response_shape({"a": {"b": {"c": 1}}, "d": 2}, max_depth=1, max_properties=1)
        self.assertTrue(shape["properties"]["a"]["truncated"])
        self.assertEqual(shape["omitted_dynamic_or_excess_keys"], 1)

    def test_bool_is_not_reported_as_integer(self):
        self.assertEqual(response_shape(True), {"type": "boolean"})


class JobProbeTests(unittest.TestCase):
    def probe(self, replies, *, detail=True):
        replies, requests = iter(replies), []

        def handle(request):
            requests.append(request)
            reply = next(replies)
            return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)

        with tempfile.TemporaryDirectory() as directory:
            captures = Path(directory) / "captures"
            with BossAuth(transport=httpx.MockTransport(handle)) as auth:
                report = run_probe(auth, query="fixture-query", city="",
                                   private_dir=captures, include_detail=detail)
            index = json.loads((captures / "index.json").read_text())
            raw = [json.loads(p.read_text()) for p in sorted(captures.glob("request-*.json"))]
        return report, requests, index, raw

    def account(self):
        return {"code": 0, "zpData": {"userId": 123}}

    def search(self):
        return {"code": 0, "zpData": {"jobList": [
            {"securityId": "fixture-security-id", "lid": "fixture-lid",
             "jobName": "PRIVATE_JOB_TITLE"},
        ]}}

    def test_successful_search_and_one_detail_keep_ids_private(self):
        report, requests, index, raw = self.probe([
            self.account(), self.search(),
            {"code": 0, "zpData": {"jobInfo": {"jobName": "PRIVATE_JOB_TITLE"}}},
        ])
        self.assertTrue(report["workflow_verified"])
        self.assertEqual(len(requests), 3)
        self.assertEqual(requests[1].method, "POST")
        self.assertIn(b"securityId=fixture-security-id", requests[2].url.query)
        self.assertNotIn("fixture-security-id", json.dumps(report))
        self.assertNotIn("PRIVATE_JOB_TITLE", json.dumps(report))
        self.assertEqual(len(index["captures"]), 3)
        self.assertEqual(raw[2]["provenance"], "observed HTTP adapter, not browser or wire capture")

    def test_invalid_auth_prevents_all_job_requests(self):
        report, requests, _, _ = self.probe([{"code": 7}])
        self.assertFalse(report["account_verified"])
        self.assertEqual(len(requests), 1)

    def test_risk_stop_does_not_retry_or_request_detail(self):
        report, requests, _, _ = self.probe([self.account(), {"code": 37}])
        self.assertFalse(report["search_verified"])
        self.assertEqual(report["final_account_status"], "BLOCKED")
        self.assertEqual(len(requests), 2)

    def test_empty_search_does_not_invent_detail_identifier(self):
        report, requests, _, _ = self.probe([
            self.account(), {"code": 0, "zpData": {"jobList": []}},
        ])
        self.assertTrue(report["search_verified"])
        self.assertFalse(report["detail_verified"])
        self.assertEqual(len(requests), 2)

    def test_missing_id_does_not_fall_back_to_unrelated_job_id(self):
        report, requests, _, _ = self.probe([
            self.account(), {"code": 0, "zpData": {"jobList": [{"jobId": "different"}]}},
        ])
        self.assertFalse(report["detail_verified"])
        self.assertEqual(len(requests), 2)

    def test_missing_joblist_is_not_called_search_success(self):
        report, requests, _, _ = self.probe([self.account(), {"code": 0, "zpData": {}}])
        self.assertFalse(report["search_verified"])
        self.assertEqual(len(requests), 2)

    def test_missing_detail_body_is_not_called_workflow_success(self):
        report, requests, _, _ = self.probe([self.account(), self.search(), {"code": 0}])
        self.assertFalse(report["detail_verified"])
        self.assertEqual(len(requests), 3)

    def test_without_detail_flag_only_two_requests_are_made(self):
        report, requests, _, _ = self.probe([self.account(), self.search()], detail=False)
        self.assertTrue(report["workflow_verified"])
        self.assertFalse(report["detail_requested"])
        self.assertEqual(len(requests), 2)

    def test_capture_directory_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory, BossAuth(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"code": 0}))
        ) as auth:
            with self.assertRaises(ValueError):
                PrivateCapture(auth.ensure_http_session(), directory)


if __name__ == "__main__":
    unittest.main()
