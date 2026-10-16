"""Bounded transport for known normal-login and read-only operations."""
import httpx

from builder.header import HeaderBuilder, ORIGIN

# Source: captured login page and published app/login bundles, not guessed URLs.
ENDPOINTS = {
    "entry": ("GET", "/web/user/"),
    "bootstrap": ("POST", "/wapi/zppassport/set/zpToken"),
    "qr_create": ("POST", "/wapi/zppassport/captcha/randkey"),
    "qr_scan": ("GET", "/wapi/zppassport/qrcode/scan"),
    "qr_second_key": ("GET", "/wapi/zppassport/captcha/getSecondKey"),
    "qr_scan_second": ("GET", "/wapi/zppassport/qrcode/scanSecond"),
    "qr_confirm": ("GET", "/wapi/zppassport/qrcode/scanLogin"),
    "user_info": ("GET", "/wapi/zpuser/wap/getUserInfo.json"),
}
STOP_CODES = {31, 32, 35, 36, 37, 120, 121, 122}
LONG_POLL = {"qr_scan", "qr_scan_second", "qr_confirm"}


class ProtocolStopped(RuntimeError):
    """Safe-to-display reason; no credential-bearing URLs or response body."""


class Session:
    def __init__(self, auth, *, live=False, transport=None, request_limit=24):
        if not live and transport is None:
            raise ProtocolStopped("Network is disabled; explicitly enable live mode")
        self.auth = auth
        self.request_limit = request_limit
        self.events = []
        self.client = httpx.Client(
            cookies=auth.cookies, transport=transport,
            timeout=15, follow_redirects=False,
        )

    def request(self, operation, *, params=None, headers=None, timeout=15):
        if operation not in ENDPOINTS:
            raise ProtocolStopped("Operation not enabled by the evidence allowlist")
        if len(self.events) >= self.request_limit:
            raise ProtocolStopped("Session request budget reached")
        method, path = ENDPOINTS[operation]
        query = params.encode() if params is not None else ""
        url = ORIGIN + path + ("?" + query if query else "")
        event = {"operation": operation, "method": method, "path": path}
        self.events.append(event)
        try:
            response = self.client.request(
                method, url,
                headers=headers if headers is not None else HeaderBuilder.build().get(),
                timeout=max(0.1, min(float(timeout), 30)),
            )
        except httpx.HTTPError as error:
            event["transport_error"] = type(error).__name__
            raise ProtocolStopped(f"Transport stopped: {type(error).__name__}") from None
        event["http_status"] = response.status_code
        if response.status_code != 200:
            raise ProtocolStopped(f"HTTP {response.status_code}; no retry or redirect")
        return response

    def json(self, operation, **kwargs):
        response = self.request(operation, **kwargs)
        try:
            body = response.json()
        except ValueError:
            raise ProtocolStopped("Non-JSON response; stopped") from None
        if not isinstance(body, dict):
            raise ProtocolStopped("Unexpected JSON shape")
        code = body.get("code")
        self.events[-1]["application_code"] = code
        if "code" in body and (not isinstance(code, int) or isinstance(code, bool)):
            raise ProtocolStopped("Unexpected business code type")
        if code in STOP_CODES or isinstance(code, int) and 4942 <= code <= 4950:
            self.auth.status = "BLOCKED"
            self.auth.verified_at = None
            self.auth.last_code = code
            raise ProtocolStopped(f"Verification/risk code {code}; no bypass or retry")
        if "code" not in body and operation not in LONG_POLL:
            raise ProtocolStopped("Expected business code is missing")
        return body

    def close(self):
        self.client.close()
