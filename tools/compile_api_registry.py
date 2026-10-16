#!/usr/bin/env python3
"""Merge static candidates, pinned helper contracts and value-free capture facts."""
import argparse
from collections import Counter, defaultdict
import json
import keyword
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, parse_qsl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils.operation_policy import operation_effect


def snake(value):
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return "_" + value if keyword.iskeyword(value) or not value[:1].isalpha() else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovered", type=Path, required=True)
    parser.add_argument("--helpers", type=Path, required=True)
    parser.add_argument("--captures", type=Path, action="append", default=[])
    parser.add_argument("--adapter-report", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()
    discovered = json.loads(args.discovered.read_text(encoding="utf-8"))
    helpers = json.loads(args.helpers.read_text(encoding="utf-8"))
    by_path = {
        row["path"]: row
        for rows in discovered["groups"].values() for row in rows
    }
    helper_map = defaultdict(list)
    for record in helpers["contracts"]:
        helper_map[record["path"]].append(record)
    runtime = defaultdict(list)
    adapter_runtime = defaultdict(list)
    script_sources = {}
    for folder in args.captures:
        index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
        for source in index.get("scripts", []):
            script_sources[source["sha256"]] = {
                "file": source["file"], "url": source["url"],
                "sha256": source["sha256"], "bytes": source["bytes"],
            }
        for item in index.get("networkRequests", []):
            url = urlsplit(item["url"])
            if url.hostname != "www.zhipin.com" or not url.path.startswith("/wapi/"):
                continue
            raw = json.loads((folder / item["captureFile"]).read_text(encoding="utf-8"))["networkRequest"]
            code = None
            try:
                body = json.loads(raw.get("responseBody", ""))
                code = body.get("code") if isinstance(body, dict) else None
            except (TypeError, ValueError):
                pass
            runtime[url.path].append({
                "method": item["method"], "status": item.get("status"),
                "application_code": code if type(code) is int else None,
                "body_retained": item.get("bodySha256") is not None,
                "query_field_names": sorted({k for k, _ in parse_qsl(url.query, keep_blank_values=True)}),
                "capture": folder.name,
            })
            if url.path not in by_path:
                by_path[url.path] = {
                    "path": url.path, "group": url.path.split("/")[2],
                    "methods": [], "occurrences": [],
                }
    for filename in args.adapter_report:
        report = json.loads(filename.read_text(encoding="utf-8"))
        if (report.get("credentials_in_report") is not False
                or report.get("provenance") != "observed normal HTTP adapter; not a browser capture"):
            raise ValueError("Only explicit value-free adapter reports are supported")
        for event in report.get("requests", []):
            pathname = event.get("path", "")
            if not re.fullmatch(r"/wapi/[A-Za-z0-9_./-]+", pathname):
                continue
            method = event.get("method")
            if method not in {"GET", "POST"}:
                continue
            adapter_runtime[pathname].append({
                "method": method, "status": event.get("http_status"),
                "application_code": event.get("application_code"),
                "report": filename.name,
                "run_account_verified": report.get("account_verified") is True,
                "provenance": "HTTP adapter; not browser capture",
            })
            if pathname not in by_path:
                by_path[pathname] = {"path": pathname, "methods": [], "occurrences": []}
    public_urls = {source["file"]: source["url"] for source in script_sources.values()}
    public_urls.update({
        "app.85b65004.js": "https://static.zhipin.com/zhipin-sign/v5333/static/js/app.85b65004.js",
        "user-login.5398946e.js": "https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js",
        "vendors.9a2efe85.js": "https://static.zhipin.com/zhipin-sign/v5333/static/js/vendors.9a2efe85.js",
    })
    # Explicit login wrappers were statically located in two published bundles.
    sms_paths = {}
    for tail in ("smsCodeV2", "smsCode", "smsCodeV3", "smsCodeByWy"):
        sms_paths["/wapi/zppassport/send/" + tail] = "form_sms"
    for tail in ("phoneV2", "phone", "phoneV3", "phoneByWy"):
        sms_paths["/wapi/zppassport/login/" + tail] = "form_sms"
    sms_paths["/wapi/zppassport/validate/getLoginSuggest"] = "form_sms"
    endpoints = []
    names = set()
    for pathname, row in sorted(by_path.items()):
        occurrences = row["occurrences"]
        hs, rs, ar = helper_map[pathname], runtime[pathname], adapter_runtime[pathname]
        methods = set(row["methods"]) - {"UNKNOWN"}
        methods.update(record["method"] for record in hs + rs + ar)
        methods &= {"GET", "POST"}
        encodings = {}
        for method in methods:
            evidence = {h["encoding"] for h in hs if h["method"] == method}
            encodings[method] = "query" if method == "GET" else (
                next(iter(evidence)) if len(evidence) == 1 else "UNKNOWN"
            )
        if pathname in sms_paths:
            methods.add("POST")
            encodings["POST"] = sms_paths[pathname]
        complete = bool(rs or ar or hs or any(o.get("path_complete") for o in occurrences))
        namespace = pathname.split("/")[2]
        group = namespace[2:] if namespace.startswith("zp") else namespace
        group = snake(group)
        method_name = snake("/".join(pathname.split("/")[3:]).removesuffix(".json"))
        if not method_name:
            method_name = "root"
        op_id = group + "_" + method_name
        if op_id in names:
            method_name += "_endpoint_" + str(len(endpoints))
            op_id = group + "_" + method_name
        names.add(op_id)
        effects = {operation_effect(method, pathname) for method in methods}
        effect = "READ" if effects == {"READ"} else operation_effect("", pathname)
        # A raw string inventory alone cannot establish a deployment origin.
        origin_known = bool(hs or rs or ar or pathname in sms_paths or namespace == "zppassport")
        source_files = sorted({o["relative_file"] for o in occurrences})
        source_urls = sorted({
            public_urls[Path(filename).name] for filename in source_files
            if Path(filename).name in public_urls
        })
        endpoints.append({
            "operation_id": op_id, "method_name": method_name, "group": group,
            "path": pathname, "methods": sorted(methods), "encodings": encodings,
            "path_complete": complete and "{dynamic}" not in pathname,
            "origin_status": "MAIN_ORIGIN_EVIDENCE" if origin_known else "UNRESOLVED",
            "effect": effect, "spa_cache_buster": bool(hs),
            "status": "BROWSER_OBSERVED" if rs else ("HTTP_ADAPTER_OBSERVED" if ar else "STATIC_ONLY"),
            "runtime_observations": rs, "parameter_schema": "NOT_SERVER_VERIFIED",
            "adapter_observations": ar,
            "helper_evidence": hs,
            "source_files": source_files, "source_urls": source_urls,
            "provenance": "observed-behavior + source-assisted" if rs or ar else "source-assisted only",
        })
    summary = {
        "endpoints": len(endpoints),
        "with_method_evidence": sum(bool(e["methods"]) for e in endpoints),
        "without_method_evidence": sum(not e["methods"] for e in endpoints),
        "browser_observed": sum(bool(e["runtime_observations"]) for e in endpoints),
        "http_adapter_observed": sum(bool(e["adapter_observations"]) for e in endpoints),
        "helper_contracts": len(helpers["contracts"]),
        "with_main_origin_evidence": sum(e["origin_status"] == "MAIN_ORIGIN_EVIDENCE" for e in endpoints),
        "dynamic_or_incomplete_paths": sum(not e["path_complete"] for e in endpoints),
        "all_site_coverage_claimed": False,
        "all_flows_live_verified": False,
        "groups": dict(Counter(e["group"] for e in endpoints)),
    }
    output = {
        "schema_version": 1, "profile": "observed sign-v5333, SEO-v5481/v5447, SPA-v6763",
        "summary": summary, "public_script_sources": list(script_sources.values()),
        "limitations": [
            "Only captured public chunks are inventoried; authenticated and recruiter-only chunks may be absent.",
            "Method evidence and request planning do not prove successful endpoint execution.",
            "Unknown deployment origins, methods, encodings, and dynamic paths stay blocked.",
            "No phone, OTP, cookies, QR identifiers, request values, or raw response bodies are exported.",
        ],
        "endpoints": endpoints,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# BOSS 接口覆盖表", "",
        "本表覆盖本次取得的公开前端脚本和匿名抓包，不是全站服务端接口全集。"
        "“已抓包”不代表已登录、业务成功或完整 cURL 等价。", "",
        f"当前共 {summary['endpoints']} 个路径条目，其中 "
        f"{summary['with_method_evidence']} 个有方法证据、"
        f"{summary['browser_observed']} 个曾在浏览器发出请求。", "",
        f"另外 {summary['http_adapter_observed']} 个 API 路径有正常 HTTP 客户端的真实运行记录；"
        "这些不是浏览器抓包，也不把所在登录流程成功扩展为所有业务接口成功。", "",
        "| 分组 | Python 方法 | 路径 | 方法证据 | 编码 | 状态与依据 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for e in endpoints:
        source = f"[发布脚本]({e['source_urls'][0]})" if e["source_urls"] else "仅捕获证据，见台账"
        lines.append(f"| {e['group']} | `{e['method_name']}` | `{e['path']}` | "
                     f"{', '.join(e['methods']) or 'UNKNOWN'} | "
                     f"{', '.join(sorted(set(e['encodings'].values()))) or 'UNKNOWN'} | {e['status']} · {source} |")
    lines.extend(["", "对应的原始发布文件及 SHA-256 记录在 `catalog/api_registry.json`，"
                  "表内状态由匿名捕获和公开脚本决定，不包含私有请求值。",
                  "", "静态业务映射的主要依据是 [职位 SPA 业务模块]"
                  "(https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/app~2.4f650b7a.js)"
                  " 和 [登录组件]"
                  "(https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)。"])
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
