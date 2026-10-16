"""Grouped adapters for discovered contracts; all calls default to planning only."""
import json
from pathlib import Path
import time

from builder.form import spa_form, sms_form
from builder.header import HeaderBuilder
from builder.params import Params
from builder.request_plan import RequestPlan

REGISTRY = Path(__file__).resolve().parents[1] / "catalog" / "api_registry.json"


class ContractIncomplete(ValueError):
    pass


class BoundEndpoint:
    def __init__(self, auth, contract):
        self.auth = auth
        self.contract = contract

    def describe(self):
        return dict(self.contract)

    def __call__(self, *, params=None, data=None, raw_body=None, content_type=None,
                 execute=False, approval=None, method=None, cache_buster=None):
        c = self.contract
        if not c.get("path_complete", False):
            raise ContractIncomplete("Dynamic or incomplete path; a runtime capture is required")
        if c.get("origin_status") != "MAIN_ORIGIN_EVIDENCE":
            raise ContractIncomplete("The deployment origin has not been established")
        choices = [m for m in c.get("methods", []) if m in {"GET", "POST"}]
        method = method or (choices[0] if len(choices) == 1 else None)
        if method not in choices:
            raise ContractIncomplete("Select a method with recorded evidence")
        encoding = c.get("encodings", {}).get(method)
        headers = HeaderBuilder.build(self.auth, "https://www.zhipin.com" + c["path"])
        if isinstance(params, Params):
            # Do not append cache-busters to the caller's mutable parameter object.
            query = params.copy()
        else:
            query = Params((key, str(value)) for key, value in (params or {}).items())
        if c.get("spa_cache_buster") and cache_buster is not False:
            if cache_buster is None:
                cache_buster = str(int(time.time() * 1000))
            query.add("_", str(cache_buster))
        body = b""
        fields = ()
        if method == "GET":
            if data is not None or raw_body is not None:
                raise ValueError("Use params for this GET contract")
        elif raw_body is not None:
            if data is not None or not isinstance(raw_body, bytes) or not content_type:
                raise ValueError("Raw bodies require bytes, an explicit content type, and no data")
            body = raw_body
            headers.set_header("Content-Type", content_type)
        elif encoding == "form_spa":
            body = spa_form(data or {})
            fields = tuple((data or {}).keys())
            headers.set_header("Content-Type", "application/x-www-form-urlencoded")
        elif encoding == "form_sms":
            body = sms_form(data or {})
            fields = tuple((data or {}).keys())
            headers.set_header("Content-Type", "application/x-www-form-urlencoded")
        elif encoding == "json":
            body = json.dumps(data or {}, ensure_ascii=False, separators=(",", ":")).encode()
            fields = tuple((data or {}).keys())
            headers.set_header("Content-Type", "application/json;charset=UTF-8")
        else:
            raise ContractIncomplete("Body encoding is unverified; use a captured raw body explicitly")
        plan = RequestPlan(
            operation=c["operation_id"], method=method, path=c["path"],
            query=query.encode(), headers=tuple(headers.get()), body=body,
            field_names=fields, effect=c.get("effect", "UNREVIEWED"),
            provenance=c.get("provenance", "static-contract; not live-verified"),
        )
        if not execute:
            return plan
        return self.auth.ensure_http_session().execute_plan(plan, approval=approval)


class ApiGroup:
    def __init__(self, auth, contracts):
        self._endpoints = {
            c["method_name"]: BoundEndpoint(auth, c) for c in contracts
        }

    def __getattr__(self, name):
        if name in self._endpoints:
            return self._endpoints[name]
        raise AttributeError(name)

    def __dir__(self):
        return sorted(self._endpoints)

    def endpoints(self):
        return {name: endpoint.describe() for name, endpoint in self._endpoints.items()}


class BossSurface:
    def __init__(self, auth, *, registry=None):
        self.auth = auth
        content = registry if registry is not None else json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.contracts = content["endpoints"]
        self._by_path = {c["path"]: BoundEndpoint(auth, c) for c in self.contracts}
        groups = {}
        for contract in self.contracts:
            groups.setdefault(contract["group"], []).append(contract)
        self._groups = {name: ApiGroup(auth, rows) for name, rows in groups.items()}

    def __getattr__(self, name):
        if name in self._groups:
            return self._groups[name]
        raise AttributeError(name)

    def endpoint(self, path):
        try:
            return self._by_path[path]
        except KeyError:
            raise ContractIncomplete("Endpoint was not found in the captured source inventory") from None

    def summary(self):
        return {
            "discovered": len(self.contracts),
            "with_method_evidence": sum(bool(row["methods"]) for row in self.contracts),
            "without_method_evidence": sum(not row["methods"] for row in self.contracts),
            "browser_observed": sum(bool(row["runtime_observations"]) for row in self.contracts),
            "http_adapter_observed": sum(bool(row.get("adapter_observations")) for row in self.contracts),
            "groups": {name: len(group.endpoints()) for name, group in self._groups.items()},
            "default_mode": "request-plan-only",
            "all_endpoints_live_verified": False,
        }
