#!/usr/bin/env python3
"""Reproduce one observed read-only request, without exposing captured headers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

ALLOWED_HOSTS = {"www.zhipin.com", "static.zhipin.com", "img.bosszhipin.com"}
BODY_UNAVAILABLE = "<Response body not available anymore>"
UNAVAILABLE_BODIES = {BODY_UNAVAILABLE, "<not available anymore>"}


def quoted(value):
    """Quote one curl config value without shell interpolation."""
    if "\r" in value or "\n" in value or "\0" in value:
        raise ValueError("Control characters are not allowed in URL/header values")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_config(record):
    if record.get("method") != "GET":
        raise ValueError("Only observed GET requests may be replayed")
    parts = urlsplit(record["url"])
    if (parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS
            or parts.username or parts.password or parts.port not in (None, 443)
            or parts.fragment):
        raise ValueError("Request must target an approved HTTPS BOSS origin")
    if (parts.hostname == "www.zhipin.com"
            and parts.path != "/wapi/zpuser/wap/getUserInfo.json"):
        raise ValueError("GET alone is not read-only; endpoint has not been approved")
    headers = record.get("requestHeaders", {})
    if not isinstance(headers, dict):
        raise ValueError("Expected the observed MCP header dictionary")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    pseudo = {
        ":scheme": "https", ":method": "GET",
        ":authority": parts.netloc, ":path": path,
    }
    for name, value in pseudo.items():
        if name in headers and headers[name] != value:
            raise ValueError(f"Observed pseudo-header disagrees with URL: {name}")
    lines = [
        "silent", "show-error", "compressed", "http2", "globoff", "path-as-is",
        'proto = "=https"', "max-time = 20", "connect-timeout = 10",
        'request = "GET"', "url = " + quoted(record["url"]),
    ]
    header_names = []
    for name, value in headers.items():
        if name.startswith(":"):
            continue  # Represented by method, URL and HTTP/2, not literal -H headers.
        if not re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", name):
            raise ValueError("Invalid HTTP header name")
        if not isinstance(value, str):
            raise ValueError("Header values must be strings")
        lines.append("header = " + quoted(name + ": " + value if value else name + ";"))
        header_names.append(name)
    lowered = {name.lower() for name in header_names}
    for implicit in ("Accept", "User-Agent", "Accept-Encoding"):
        if implicit.lower() not in lowered:
            lines.append("header = " + quoted(implicit + ":"))
    return "\n".join(lines) + "\n", header_names


def compare_response(record, actual_bytes, actual_status):
    observed = record.get("responseBody")
    available = isinstance(observed, str) and observed not in UNAVAILABLE_BODIES
    byte_match = None
    json_match = None
    if available:
        byte_match = observed.encode("utf-8") == actual_bytes
        try:
            json_match = json.loads(observed) == json.loads(actual_bytes)
        except (ValueError, UnicodeDecodeError):
            pass
    return {
        "observed_http_status": int(record["status"]),
        "replay_http_status": actual_status,
        "http_status_match": int(record["status"]) == actual_status,
        "observed_response_body_available": available,
        "response_utf8_bytes_match": byte_match,
        "response_json_match": json_match,
        "replay_body_sha256": hashlib.sha256(actual_bytes).hexdigest(),
        "replay_body_bytes": len(actual_bytes),
        "verified_equivalent": available and byte_match is True
        and int(record["status"]) == actual_status,
    }


def write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(data)
    os.chmod(path, 0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Send exactly one GET")
    args = parser.parse_args()
    record = json.loads(args.capture.read_text())["networkRequest"]
    config, names = build_config(record)
    private = args.private_dir.resolve()
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(private, 0o700)
    config_file = private / "request.curl"
    write_private(config_file, config)
    report = {
        "target": urlsplit(record["url"])._replace(query="", fragment="").geturl(),
        "method": "GET",
        "captured_header_names": names,
        "ordinary_headers_preserved": True,
        "credentials_in_report": False,
        "request_replayed": False,
        "framework_reference": "https://github.com/cv-cat/DouYin_Spider",
        "limitations": [
            "MCP header dictionary does not preserve duplicate headers or wire ordering.",
            "HTTP/2 pseudo-headers are represented through URL and method.",
            "TLS and HTTP/2 browser fingerprints are not claimed to match.",
            "No guarantee that timestamps or server-side session state remain valid.",
            "GET endpoints may mutate state; only the evidence allowlist is enabled.",
            "Response equality alone does not prove account login or job integration.",
        ],
    }
    if args.execute:
        response = private / "replay-body.bin"
        response_headers = private / "replay-headers.txt"
        for output in (response, response_headers):
            write_private(output, "")
        completed = subprocess.run([
            "curl", "--config", str(config_file),
            "--output", str(response),
            "--dump-header", str(response_headers),
            "--write-out", "%{json}",
        ], capture_output=True, text=True, timeout=25)
        report["request_replayed"] = True
        report["curl_exit_code"] = completed.returncode
        if completed.returncode == 0:
            metrics = json.loads(completed.stdout)
            report["negotiated_http_version"] = metrics["http_version"]
            report["comparison"] = compare_response(
                record, response.read_bytes(), int(metrics["http_code"])
            )
            try:
                result = json.loads(response.read_bytes())
                if isinstance(result, dict):
                    report["replay_application_code"] = result.get("code")
            except (ValueError, UnicodeDecodeError):
                pass
        else:
            report["error"] = "curl failed; private diagnostics retained"
            write_private(private / "curl-error.txt", completed.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
