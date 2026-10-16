"""A scoped cookie jar and observed account status, not a token-forging helper."""
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
import time
from urllib.parse import urlsplit
from urllib.request import Request

from utils.private_state import load_private, save_private

COOKIE_FIELDS = (
    "version", "name", "value", "port", "port_specified", "domain",
    "domain_specified", "domain_initial_dot", "path", "path_specified",
    "secure", "expires", "discard", "comment", "comment_url", "rfc2109",
)


class BossAuth:
    def __init__(self, *, live=False, transport=None):
        self.cookies = CookieJar(
            DefaultCookiePolicy(
                strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain
            )
        )
        self.live = live
        self.transport = transport
        self._session = None
        self.status = "UNKNOWN"
        self.verified_at = None
        self.last_code = None
        self.application_token = None

    def ensure_http_session(self):
        if self._session is None:
            from utils.http_client import Session
            self._session = Session(self, live=self.live, transport=self.transport)
        return self._session

    def cookie_header_for_url(self, url):
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != "www.zhipin.com"
                or parts.port not in (None, 443) or parts.username or parts.password):
            raise ValueError("Cookies may only be used on the approved BOSS origin")
        request = Request(url)
        self.cookies.add_cookie_header(request)
        return request.get_header("Cookie", "")

    def cookie_value_for_url(self, name, url):
        values = [
            part.strip().partition("=")[2]
            for part in self.cookie_header_for_url(url).split(";")
            if part.strip().partition("=")[0] == name
        ]
        if len(set(values)) > 1:
            raise ValueError("Ambiguous scoped cookie; capture the browser header")
        return values[0] if values else None

    def observe_user_info(self, body):
        self.last_code = body.get("code")
        data = body.get("zpData")
        user_id = data.get("userId") if isinstance(data, dict) else None
        valid_id = (
            isinstance(user_id, int) and not isinstance(user_id, bool) and user_id > 0
        ) or (
            isinstance(user_id, str) and bool(user_id.strip()) and user_id.strip() != "0"
        )
        if type(self.last_code) is int and self.last_code == 0 and valid_id:
            self.status = "VERIFIED"
            self.verified_at = time.time()
            token = data.get("token")
            self.application_token = token if isinstance(token, str) and token else None
        else:
            self.status = "INVALID" if self.last_code == 7 else "UNVERIFIED"
            self.verified_at = None
            self.application_token = None
        return self.safe_status()

    def safe_status(self):
        return {
            "account_status": self.status,
            "account_logged_in": self.status == "VERIFIED",
            "verified_at": self.verified_at,
            "last_application_code": self.last_code,
            "cookie_names": sorted({cookie.name for cookie in self.cookies}),
            "credentials_in_report": False,
        }

    def to_state(self):
        rows = []
        for cookie in self.cookies:
            row = {key: getattr(cookie, key) for key in COOKIE_FIELDS}
            row["rest"] = dict(cookie._rest)
            rows.append(row)
        return {
            "schema_version": 1,
            "cookies": rows,
            "provenance": "normal-session-cookie-jar",
            "last_observation": self.safe_status(),
            "application_token": self.application_token,
        }

    @classmethod
    def from_state(cls, state, **kwargs):
        if state.get("schema_version") != 1:
            raise ValueError("Unsupported auth state format")
        auth = cls(**kwargs)
        token = state.get("application_token")
        if token is not None and not isinstance(token, str):
            raise ValueError("Invalid application token type")
        auth.application_token = token
        for row in state.get("cookies", []):
            if row.get("domain", "").lstrip(".") not in (
                "zhipin.com", "www.zhipin.com"
            ):
                raise ValueError("Cookie outside the BOSS scope")
            values = {key: row[key] for key in COOKIE_FIELDS}
            values["rest"] = row.get("rest", {})
            cookie = Cookie(**values)
            if not cookie.is_expired():
                auth.cookies.set_cookie(cookie)
        # A saved observation is historical. A fresh process must verify again.
        return auth

    def save(self, path):
        save_private(path, self.to_state())

    @classmethod
    def load(cls, path, **kwargs):
        return cls.from_state(load_private(path), **kwargs)

    def close(self):
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
