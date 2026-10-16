"""Immutable, value-redacted request planning with payload-bound write approval."""
from dataclasses import dataclass, field
import hashlib
import json
from urllib.parse import parse_qsl, urlsplit

from builder.header import Header, ORIGIN


@dataclass(frozen=True, repr=False)
class RequestPlan:
    operation: str
    method: str
    path: str
    query: str = field(default="", repr=False)
    headers: tuple = field(default=(), repr=False)
    body: bytes = field(default=b"", repr=False)
    field_names: tuple = ()
    effect: str = "UNREVIEWED"
    provenance: str = "static-contract; not live-verified"

    def __post_init__(self):
        parts = urlsplit(self.path)
        if (not self.path.startswith("/wapi/") or parts.scheme or parts.netloc
                or parts.query or parts.fragment or any(x in self.path for x in ("\r", "\n", "\0", "\\"))
                or ".." in self.path.split("/") or "{" in self.path or "%" in self.path):
            raise ValueError("A complete root-relative BOSS API path is required")
        if self.method not in {"GET", "POST"}:
            raise ValueError("The request method has not been established")
        if self.method == "GET" and self.body:
            raise ValueError("GET request bodies are not supported")
        if any(c in self.query for c in "\r\n\0#"):
            raise ValueError("Invalid raw query")
        if not isinstance(self.body, bytes) or len(self.body) > 2 * 1024 * 1024:
            raise ValueError("A bounded bytes body is required")
        if not isinstance(self.headers, tuple) or any(
            not isinstance(pair, tuple) or len(pair) != 2 for pair in self.headers
        ):
            raise ValueError("Request headers must be immutable tuples")
        validator = Header()
        for name, value in self.headers:
            validator.set_header(name, value)
        if any(name.lower() in {"host", "authorization", "cookie"} for name, _ in self.headers):
            raise ValueError("Session credentials must come from BossAuth, not request plans")

    @property
    def url(self):
        return ORIGIN + self.path + ("?" + self.query if self.query else "")

    def fingerprint(self):
        prefix = json.dumps(
            [self.operation, self.method, self.path, self.query, self.headers, self.effect],
            ensure_ascii=False, separators=(",", ":"),
        ).encode()
        return hashlib.sha256(prefix + b"\0" + self.body).hexdigest()

    def preview(self):
        from utils.operation_policy import operation_effect
        return {
            "operation": self.operation, "method": self.method, "path": self.path,
            "query_field_names": [key for key, _ in parse_qsl(self.query, keep_blank_values=True)],
            "body_field_names": list(self.field_names),
            "header_names": [key for key, _ in self.headers],
            "body_bytes": len(self.body), "effect": self.effect,
            "requires_approval": (
                self.effect != "READ" or operation_effect(self.method, self.path) != "READ"
            ),
            "provenance": self.provenance,
            "contains_values": False,
        }

    def __repr__(self):
        return f"RequestPlan({self.method} {self.path}, effect={self.effect})"


@dataclass(repr=False)
class ActionApproval:
    """Application guard, not proof of identity or a substitute for user consent."""
    request_fingerprint: str
    reason: str
    consumed: bool = False

    @classmethod
    def for_request(cls, plan, *, confirmed, reason):
        if confirmed is not True or not isinstance(reason, str) or not reason.strip():
            raise ValueError("Explicit confirmation and a review reason are required")
        return cls(plan.fingerprint(), reason)

    def consume(self, plan):
        if self.consumed or self.request_fingerprint != plan.fingerprint():
            raise ValueError("Approval is used or belongs to a different exact request")
        self.consumed = True

    def __repr__(self):
        return f"ActionApproval(consumed={self.consumed})"
