"""Diagnostic headers, not a claim of Chrome/TLS fingerprint equivalence."""
import re

ORIGIN = "https://www.zhipin.com"
USER_AGENT = "BOSS-Protocol-Diagnostics/0.2"


class Header:
    def __init__(self):
        self._pairs = []

    def set_header(self, name, value):
        if not isinstance(name, str) or not re.fullmatch(
            r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", name
        ):
            raise ValueError("Invalid HTTP header name")
        if not isinstance(value, str) or any(c in value for c in "\r\n\0"):
            raise ValueError("Invalid HTTP header value")
        self._pairs = [(k, v) for k, v in self._pairs if k.lower() != name.lower()]
        self._pairs.append((name, value))
        return self

    def get(self):
        return list(self._pairs)


class HeaderBuilder:
    @staticmethod
    def build(auth=None, url=None):
        headers = (
            Header()
            .set_header("User-Agent", USER_AGENT)
            .set_header("Accept", "application/json, text/plain, */*")
            .set_header("Referer", ORIGIN + "/web/user/")
            .set_header("X-Requested-With", "XMLHttpRequest")
        )
        if auth is not None and url is not None:
            bst = auth.cookie_value_for_url("bst", url)
            if bst:
                headers.set_header("zp_token", bst)
        # No invented store token, traceId algorithm, fp, or __zp_stoken__.
        return headers
