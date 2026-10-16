"""All tests are offline; fixtures are in memory and no JS is executed."""

from collections import Counter
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


TOOL = Path(__file__).resolve().parents[1] / "tools" / "discover_api_catalog.py"
SPEC = importlib.util.spec_from_file_location("api_discovery_candidate", TOOL)
api = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = api
SPEC.loader.exec_module(api)


def scan(source, filename="chunk.js"):
    return api.scan_source(source, filename)


def entries(source):
    catalog = api.assemble_catalog([scan(source)])
    return {item["path"]: item for group in catalog["groups"].values() for item in group}


class LiteralExtractionTests(unittest.TestCase):
    def test_comments_are_not_endpoints(self):
        result = entries('''
            // axios.get("/wapi/geek/comment");
            /* ye({method:"post", url:"/wapi/user/comment"}) */
            const actual = "/wapi/common/actual";
        ''')
        self.assertEqual(set(result), {"/wapi/common/actual"})

    def test_comment_markers_inside_strings_are_not_comments(self):
        result = entries('const u="https://example.invalid/wapi/common/actual?next=//ignored";')
        occurrence = result["/wapi/common/actual"]["occurrences"][0]
        self.assertTrue(occurrence["origin_stripped"])
        self.assertTrue(occurrence["query_stripped"])

    def test_duplicate_urls_keep_occurrences_and_conflicting_evidence(self):
        source = 'axios.get("/wapi/user/info?a=1");axios.post("/wapi/user/info?a=2");const u="/wapi/user/info";'
        result = entries(source)["/wapi/user/info"]
        self.assertEqual(len(result["occurrences"]), 3)
        self.assertEqual(result["methods"], ["GET", "POST", "UNKNOWN"])
        self.assertEqual(result["method_status"], "CONFLICTING_STATIC_EVIDENCE")
        expected_digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        for occurrence in result["occurrences"]:
            self.assertEqual(occurrence["relative_file"], "chunk.js")
            self.assertEqual(occurrence["sha256"], expected_digest)
            self.assertTrue(source[occurrence["char_start"]:].startswith("/wapi/user/info"))

    def test_unicode_and_crlf_positions_are_codepoints_not_bytes(self):
        source = '// 中文\r\nconst u = "/wapi/geek/list?key=discarded";'
        occurrence = scan(source)["occurrences"][0]
        self.assertEqual(occurrence["line"], 2)
        self.assertEqual(occurrence["column"], len('const u = "') + 1)
        self.assertEqual(occurrence["char_start"], source.index("/wapi/"))
        self.assertEqual(source[occurrence["char_start"]:occurrence["char_end"]], "/wapi/geek/list")

    def test_escape_sequences_keep_original_positions(self):
        source = r'axios.get("\x2fwapi\/geek/\u006cist\u003fphone=13800138000");'
        occurrence = entries(source)["/wapi/geek/list"]["occurrences"][0]
        self.assertTrue(occurrence["literal_escaped"])
        self.assertTrue(occurrence["query_stripped"])
        self.assertEqual(occurrence["char_start"], source.index(r"\x2f"))
        self.assertEqual(occurrence["method"], "GET")

    def test_regex_literals_do_not_create_endpoints(self):
        source = r'''const r = /["']\/wapi\/geek\/fake["']/g;
                    if (ok) /"\/wapi\/user\/fake"/.test(x);
                    const u="/wapi/common/real";'''
        self.assertEqual(set(entries(source)), {"/wapi/common/real"})

    def test_embedded_code_string_is_not_parsed_as_javascript(self):
        self.assertEqual(entries('const text = \'axios.get("/wapi/geek/not-a-url-literal")\';'), {})

    def test_plain_template_and_dynamic_template(self):
        source = 'axios.get(`/wapi/geek/list`);fetch(`/wapi/user/${account}/profile?phone=${phone}`,{method:"POST"});'
        result = entries(source)
        constant = result["/wapi/geek/list"]["occurrences"][0]
        dynamic = result["/wapi/user/{dynamic}/profile"]["occurrences"][0]
        self.assertTrue(constant["template"])
        self.assertFalse(constant["dynamic"])
        self.assertTrue(dynamic["template"])
        self.assertTrue(dynamic["dynamic"])
        self.assertTrue(dynamic["dynamic_in_path"])
        self.assertFalse(dynamic["path_complete"])
        self.assertEqual(dynamic["method"], "POST")
        self.assertNotIn("account", json.dumps(result))
        self.assertNotIn("${phone}", json.dumps(result))

    def test_dynamic_query_does_not_invent_dynamic_path(self):
        occurrence = entries('const u=`/wapi/geek/list?page=${value}`;')["/wapi/geek/list"]["occurrences"][0]
        self.assertTrue(occurrence["dynamic"])
        self.assertFalse(occurrence["dynamic_in_path"])
        self.assertTrue(occurrence["path_complete"])

    def test_nested_template_expression_is_scanned_independently(self):
        source = '''const u = `/wapi/geek/${pick({a: `x${y}`, b: "/wapi/common/inside"})}/list`;'''
        result = entries(source)
        self.assertEqual(set(result), {"/wapi/geek/{dynamic}/list", "/wapi/common/inside"})
        self.assertEqual(result["/wapi/common/inside"]["methods"], ["UNKNOWN"])

    def test_comments_and_braces_in_template_expressions(self):
        source = '''const u = `/wapi/geek/${fn("}", /* "/wapi/fake" */ {x: 1})}/list`;'''
        self.assertEqual(set(entries(source)), {"/wapi/geek/{dynamic}/list"})

    def test_tagged_or_transformed_literals_are_unknown(self):
        for source in (
            'axios.get(tag`/wapi/geek/list`);',
            'axios.get("/wapi/geek/list".replace("list","delete"));',
            'axios.get(("/wapi/geek/list").replace("list","delete"));',
            'axios.get("/wapi/geek/list"[index]);',
        ):
            with self.subTest(source=source):
                occurrence = next(iter(entries(source).values()))["occurrences"][0]
                self.assertEqual(occurrence["method"], "UNKNOWN")
                self.assertTrue(occurrence["dynamic"])
                self.assertFalse(occurrence["path_complete"])

    def test_static_concatenation(self):
        result = entries('axios.get("/wapi/geek/"+"job"+"/list");')
        occurrence = result["/wapi/geek/job/list"]["occurrences"][0]
        self.assertTrue(occurrence["concatenated"])
        self.assertFalse(occurrence["dynamic"])
        self.assertEqual(occurrence["method"], "GET")

    def test_dynamic_concatenation(self):
        occurrence = entries('axios.post("/wapi/user/" + user.id + "/update", payload);')[
            "/wapi/user/{dynamic}/update"
        ]["occurrences"][0]
        self.assertTrue(occurrence["dynamic"])
        self.assertTrue(occurrence["concatenated"])
        self.assertEqual(occurrence["method"], "POST")
        self.assertNotIn("user.id", json.dumps(occurrence))

    def test_concatenated_query_is_removed(self):
        occurrence = entries('axios.get("/wapi/geek/list" + "?phone=" + phone);')[
            "/wapi/geek/list"
        ]["occurrences"][0]
        self.assertTrue(occurrence["query_stripped"])
        self.assertFalse(occurrence["dynamic_in_path"])
        self.assertTrue(occurrence["dynamic"])

    def test_unknown_prefix_is_not_a_complete_endpoint_contract(self):
        occurrence = entries('const u = base + "/wapi/geek/list";')["/wapi/geek/list"]["occurrences"][0]
        self.assertTrue(occurrence["dynamic_prefix"])
        self.assertFalse(occurrence["path_complete"])

    def test_split_wapi_anchor_is_intentionally_not_reconstructed(self):
        self.assertEqual(entries('axios.get("/wa" + "pi/geek/list");'), {})

    def test_parenthesized_url_and_concatenation(self):
        result = entries('axios.post((("/wapi/user/") + id + "/set"));')
        self.assertEqual(result["/wapi/user/{dynamic}/set"]["methods"], ["POST"])

    def test_malformed_literals_do_not_gain_method_evidence(self):
        source = 'axios.get("/wapi/geek/list"); const invalid = "/wapi/user/broken\n;'
        result = entries(source)
        self.assertEqual(result["/wapi/geek/list"]["methods"], ["UNKNOWN"])
        self.assertNotIn("/wapi/user/broken", result)

    def test_concat_operands_do_not_change_expression_precedence(self):
        sources = (
            'axios.get("/wapi/user/info" + condition ? other : fallback);',
            'axios.get("/wapi/user/info" + suffix === target);',
            'axios.get("/wapi/user/info" + suffix || fallback);',
            'ye({url:"/wapi/user/info" + suffix == other,method:"GET"});',
        )
        for source in sources:
            with self.subTest(source=source):
                occurrences = scan(source)["occurrences"]
                self.assertTrue(occurrences)
                self.assertTrue(all(item["method"] == "UNKNOWN" for item in occurrences))

    def test_grouped_dynamic_operand_preserves_concat_method_evidence(self):
        occurrence = entries('axios.get("/wapi/user/" + (condition ? a : b));')[
            "/wapi/user/{dynamic}"
        ]["occurrences"][0]
        self.assertEqual(occurrence["method"], "GET")
        self.assertTrue(occurrence["dynamic"])

    def test_call_and_index_dynamic_operands(self):
        result = entries('axios.get("/wapi/user/" + encodeURIComponent(ids[index]) + "/info");')
        self.assertEqual(result["/wapi/user/{dynamic}/info"]["methods"], ["GET"])

    def test_unresolved_concatenation_stays_dynamic_and_unknown(self):
        occurrence = scan('axios.get("/wapi/user/" + id * 2);')["occurrences"][0]
        self.assertTrue(occurrence["expression_unresolved"])
        self.assertTrue(occurrence["dynamic"])
        self.assertTrue(occurrence["concatenated"])
        self.assertFalse(occurrence["path_complete"])
        self.assertEqual(occurrence["method"], "UNKNOWN")

    def test_concatenated_call_result_is_not_a_dynamic_url_argument(self):
        occurrence = entries('const result = axios.get("/wapi/user/info") + suffix;')[
            "/wapi/user/info"
        ]["occurrences"][0]
        self.assertFalse(occurrence["dynamic"])
        self.assertEqual(occurrence["method"], "GET")


class MethodEvidenceTests(unittest.TestCase):
    def test_direct_get_post_allowlist(self):
        source = 'axios.get("/wapi/geek/a");axios.post("/wapi/geek/b");$.get("/wapi/geek/c");jQuery.post("/wapi/geek/d");'
        result = entries(source)
        self.assertEqual([result[f"/wapi/geek/{letter}"]["methods"] for letter in "abcd"],
                         [["GET"], ["POST"], ["GET"], ["POST"]])

    def test_explicit_fetch_options_only(self):
        result = entries('fetch("/wapi/geek/a",{method:"gEt"});fetch("/wapi/geek/b",{method:"POST",body:data});fetch("/wapi/geek/c");')
        self.assertEqual(result["/wapi/geek/a"]["methods"], ["GET"])
        self.assertEqual(result["/wapi/geek/b"]["methods"], ["POST"])
        self.assertEqual(result["/wapi/geek/c"]["methods"], ["UNKNOWN"])

    def test_non_http_get_and_minified_aliases_remain_unknown(self):
        for name in ("cache.get", "map.get", "api.get", "x.post", "request", "some.axios.get"):
            with self.subTest(name=name):
                self.assertEqual(entries(f'{name}("/wapi/user/info");')["/wapi/user/info"]["methods"], ["UNKNOWN"])

    def test_same_object_method_can_precede_or_follow_url(self):
        source = 'ye({method:"post",url:"/wapi/passport/a",data:x});ye({"url":"/wapi/passport/b","method":"GET",params:{x:1}});'
        result = entries(source)
        self.assertEqual(result["/wapi/passport/a"]["methods"], ["POST"])
        self.assertEqual(result["/wapi/passport/b"]["methods"], ["GET"])
        self.assertEqual(result["/wapi/passport/b"]["occurrences"][0]["method_evidence"]["rule"],
                         "same_url_method_object")

    def test_method_evidence_locations_are_auditable(self):
        source = 'ye({url:"/wapi/user/info", method:"post"});'
        occurrence = entries(source)["/wapi/user/info"]["occurrences"][0]
        span = occurrence["method_evidence"]["method_location"]
        self.assertEqual(source[span["char_start"]:span["char_end"]], '"post"')
        self.assertFalse(occurrence["method_evidence"]["runtime_verified"])

    def test_nearby_and_nested_methods_are_not_inherited(self):
        sources = (
            'const method="GET";call("/wapi/user/info");',
            'ye({url:"/wapi/user/info",options:{method:"POST"}});',
            'const method={method:"POST"};const url="/wapi/user/info";',
            'ye({method:"POST",data:{url:"/wapi/user/info"}});',
            'ye({method:"POST",url:choose({other:"/wapi/user/info"})});',
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(entries(source)["/wapi/user/info"]["methods"], ["UNKNOWN"])

    def test_payload_url_method_object_is_not_a_request(self):
        source = 'ye({url:"/wapi/user/outer",method:"POST",data:{url:"/wapi/user/info",method:"GET"}});'
        result = entries(source)
        self.assertEqual(result["/wapi/user/outer"]["methods"], ["POST"])
        self.assertEqual(result["/wapi/user/info"]["methods"], ["UNKNOWN"])

    def test_ambiguous_options_fail_closed(self):
        bodies = (
            'method:"GET",...other',
            '...other,method:"GET"',
            'method:"GET",method:"POST"',
            'method:"GET",[key]:value',
            'method:verb',
            'method:pick("GET")',
            'method:"DELETE"',
            'method:`GET`',
            'get method(){return "GET"}',
            'method:"GET",type:"POST"',
        )
        for body in bodies:
            with self.subTest(body=body):
                source = 'fetch("/wapi/user/info",{' + body + '});'
                self.assertEqual(entries(source)["/wapi/user/info"]["methods"], ["UNKNOWN"])

    def test_duplicate_urls_and_spread_request_objects_fail_closed(self):
        sources = (
            'ye({url:"/wapi/user/info",method:"GET",...other});',
            'ye({...other,url:"/wapi/user/info",method:"GET"});',
            'ye({url:"/wapi/user/info",method:"GET",url:other});',
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(entries(source)["/wapi/user/info"]["methods"], ["UNKNOWN"])

    def test_ajax_type_only_when_direct_ajax_call(self):
        source = '$.ajax({url:"/wapi/user/a",type:"POST"});jQuery.ajax("/wapi/user/b",{type:"GET"});ye({url:"/wapi/user/c",type:"GET"});'
        result = entries(source)
        self.assertEqual(result["/wapi/user/a"]["methods"], ["POST"])
        self.assertEqual(result["/wapi/user/b"]["methods"], ["GET"])
        self.assertEqual(result["/wapi/user/c"]["methods"], ["UNKNOWN"])

    def test_get_name_does_not_imply_get_method(self):
        self.assertEqual(entries('const x="/wapi/user/getInfo";')["/wapi/user/getInfo"]["methods"], ["UNKNOWN"])

    def test_sms_send_and_logout_are_never_read_only(self):
        result = entries('axios.get("/wapi/zppassport/sms/send");axios.get("/wapi/user/logout");'
                         'axios.get("/wapi/user/logOutAll");axios.get("/wapi/user/smssend");')
        for entry in result.values():
            self.assertEqual(entry["methods"], ["GET"])
            self.assertEqual(entry["capability"]["candidate"], "MUTATION_OR_AUTH_CANDIDATE")
            self.assertFalse(entry["capability"]["read_only_verified"])
            self.assertFalse(entry["capability"]["safe_to_request"])

    def test_even_read_candidate_needs_manual_validation(self):
        entry = entries('axios.get("/wapi/geek/list");')["/wapi/geek/list"]
        self.assertEqual(entry["capability"]["candidate"], "READ_CANDIDATE_UNVERIFIED")
        self.assertTrue(entry["capability"]["manual_verification_required"])
        self.assertFalse(entry["capability"]["read_only_verified"])
        self.assertEqual(entry["parameters"], {"status": "UNKNOWN", "collected": False})


class PrivacyAndCoverageTests(unittest.TestCase):
    def test_queries_fragments_cookies_and_bodies_are_not_exported(self):
        source = '''fetch("/wapi/user/info?phone=13800138000&cookie=SECRET_COOKIE&next=/wapi/geek/hidden#SECRET_FRAGMENT",
                   {method:"POST",headers:{Cookie:"SECRET_HEADER"},body:"SECRET_BODY"});'''
        result = api.assemble_catalog([scan(source)])
        dumped = json.dumps(result)
        for secret in ("13800138000", "SECRET_COOKIE", "SECRET_FRAGMENT", "SECRET_HEADER", "SECRET_BODY", "/wapi/geek/hidden"):
            self.assertNotIn(secret, dumped)
        self.assertEqual(result["coverage"]["unique_endpoints"], 1)
        self.assertEqual(result["groups"]["user"][0]["path"], "/wapi/user/info")

    def test_query_literal_in_concatenation_is_not_a_second_endpoint(self):
        source = 'const url="/wapi/user/info?next=" + "/wapi/geek/hidden";'
        self.assertEqual(set(entries(source)), {"/wapi/user/info"})

    def test_query_interpolations_are_not_new_endpoints(self):
        source = 'const url=`/wapi/user/info?next=${"/wapi/geek/hidden"}&x=${`/wapi/common/${y}`}`;'
        self.assertEqual(set(entries(source)), {"/wapi/user/info"})

    def test_phone_and_cookie_values_in_path_are_redacted(self):
        result = entries('const a="/wapi/user/13800138000/info";const b="/wapi/common/cookie/PRIVATEVALUE";')
        dumped = json.dumps(result)
        self.assertNotIn("13800138000", dumped)
        self.assertNotIn("PRIVATEVALUE", dumped)
        self.assertIn("/wapi/user/{redacted}/info", result)
        self.assertIn("/wapi/common/cookie/{redacted}", result)
        for entry in result.values():
            self.assertFalse(entry["occurrences"][0]["path_complete"])

    def test_formatted_phone_route_values_are_redacted(self):
        source = 'const a="/wapi/user/138-0013-8000/info";const b="/wapi/user/138%2d0013%2d8000/info";'
        result = entries(source)
        self.assertEqual(set(result), {"/wapi/user/{redacted}/info"})
        self.assertNotIn("138-0013", json.dumps(result))

    def test_malicious_endpoint_paths_are_rejected_without_samples(self):
        paths = (
            "/wapi/../secret", "/wapi/geek/../../secret",
            "/wapi/geek/%2e%2e/secret", "/wapi/geek/%252e%252e/secret",
            "/wapi/geek/%2fsecret", "/wapi/geek/%5csecret",
            "/wapi/geek//secret", "/wapi/geek/secret\nnext",
            "/wapi/geek/secret\\next", "/wapi/geek/%00secret",
            "/wapi/geek/%3fphone=13800138000",
        )
        for path in paths:
            with self.subTest(path=path):
                result = api.assemble_catalog([scan("const u=" + json.dumps(path) + ";")])
                self.assertEqual(result["coverage"]["unique_endpoints"], 0)
                self.assertNotIn("13800138000", json.dumps(result))
                self.assertNotIn("secret", json.dumps(result["coverage"]["rejected_candidates"]))

    def test_unreserved_percent_escapes_normalized_with_flag(self):
        occurrence = entries('const u="/wapi/geek/%6cist";')["/wapi/geek/list"]["occurrences"][0]
        self.assertTrue(occurrence["percent_unreserved_normalized"])

    def test_group_aliases_and_unknown_namespaces(self):
        paths = (
            "/wapi/zppassport/a", "/wapi/zpuser/a", "/wapi/zpgeek/a", "/wapi/zpboss/a",
            "/wapi/zpcompany/a", "/wapi/zpcommon/a", "/wapi/newdomain/a",
        )
        result = api.assemble_catalog([scan(";".join(json.dumps(path) for path in paths))])
        for group in (*api.KNOWN_GROUPS, "newdomain"):
            self.assertEqual(len(result["groups"][group]), 1)

    def test_multiple_files_keep_distinct_hashes_and_relative_paths(self):
        scans = [scan('"/wapi/user/info";', "a/chunk.js"), scan('axios.get("/wapi/user/info");', "b/chunk.js")]
        catalog = api.assemble_catalog(scans)
        entry = catalog["groups"]["user"][0]
        self.assertEqual(len(entry["occurrences"]), 2)
        self.assertEqual(entry["method_status"], "PARTIAL_STATIC_EVIDENCE")
        self.assertEqual(len({item["sha256"] for item in entry["occurrences"]}), 2)
        self.assertEqual(catalog["coverage"]["files_scanned"], 2)

    def test_deterministic_catalog_and_explicit_partial_status(self):
        source = 'axios.get("/wapi/user/info");'
        first = api.assemble_catalog([scan(source)])
        second = api.assemble_catalog([scan(source)])
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertFalse(first["coverage"]["exhaustive"])
        self.assertFalse(first["tool"]["issues_network_requests"])
        self.assertFalse(first["tool"]["executes_javascript"])
        self.assertEqual(first["coverage"]["status"], "PARTIAL_STATIC_CANDIDATES")


class FilesystemAndCliTests(unittest.TestCase):
    def test_malicious_relative_filenames_are_rejected(self):
        for path in ("../x.js", "/tmp/x.js", "a/../../x.js", r"a\..\x.js", "private/x.js",
                     "a/PRIVATE/x.js", "a//x.js", "a/\n.js", "13800138000.js"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    scan('"/wapi/user/info"', path)

    def test_explicit_private_or_parent_paths_are_refused_before_io(self):
        for path in ("evidence/private", "evidence/PRIVATE/chunks", "../scripts", "https://example.invalid/scripts"):
            with self.subTest(path=path), mock.patch.object(Path, "is_dir") as is_dir:
                with self.assertRaises(ValueError):
                    api.checked_path(path, directory=True)
                is_dir.assert_not_called()

    def test_symlink_root_or_ancestor_is_refused(self):
        with mock.patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(ValueError):
                api.checked_path("/public/scripts", directory=True)

    def test_recursion_prunes_private_and_symlink_directories(self):
        directories = ["private", "chunks", "linked"]
        root = Path("/public/scripts")
        fake_walk = [(str(root), directories, ["a.js", "a.map", "linked.js", "13800138000.js"])]

        def symlink(path):
            return path.name in ("linked", "linked.js")

        with mock.patch.object(api.os, "walk", return_value=iter(fake_walk)), \
                mock.patch.object(Path, "is_symlink", autospec=True, side_effect=symlink):
            skipped = Counter()
            files = list(api.iter_script_files(root, skipped))
        self.assertEqual(directories, ["chunks"])
        self.assertEqual(files, [(root / "a.js", "a.js")])
        self.assertEqual(skipped["private_directories"], 1)
        self.assertEqual(skipped["symlinks"], 2)
        self.assertEqual(skipped["unsafe_file_names"], 1)

    def test_files_with_invalid_utf8_fail_without_content(self):
        root = Path("/public/scripts")
        with mock.patch.object(api, "checked_path", return_value=root), \
                mock.patch.object(api, "iter_script_files", return_value=[(root / "bad.js", "bad.js")]), \
                mock.patch.object(api, "read_script", return_value=b"\xffPRIVATE_CONTENT"):
            result = api.build_catalog([str(root)])
        self.assertEqual(result["coverage"]["files_failed"], 1)
        self.assertEqual(result["files"][0]["reason"], "invalid_utf8")
        self.assertNotIn("PRIVATE_CONTENT", json.dumps(result))

    def test_scan_file_bytes_are_hashed_without_newline_conversion(self):
        root = Path("/public/scripts")
        raw = b'// header\r\naxios.get("/wapi/user/info");\r\n'
        with mock.patch.object(api, "checked_path", return_value=root), \
                mock.patch.object(api, "iter_script_files", return_value=[(root / "a.js", "a.js")]), \
                mock.patch.object(api, "read_script", return_value=raw):
            result = api.build_catalog([str(root)])
        self.assertEqual(result["groups"]["user"][0]["occurrences"][0]["sha256"], hashlib.sha256(raw).hexdigest())

    def test_overlapping_roots_rejected(self):
        with mock.patch.object(api, "checked_path", side_effect=[Path("/public"), Path("/public/scripts")]):
            with self.assertRaises(ValueError):
                api.build_catalog(["/public", "/public/scripts"])

    def test_existing_or_nonjson_output_refused(self):
        with mock.patch.object(Path, "is_symlink", return_value=False), \
                mock.patch.object(Path, "exists", return_value=True):
            with self.assertRaises(ValueError):
                api.checked_path("/output/existing.json", directory=False)
        with mock.patch.object(Path, "is_symlink", return_value=False), \
                mock.patch.object(Path, "exists", return_value=False), \
                mock.patch.object(Path, "is_dir", return_value=True):
            with self.assertRaises(ValueError):
                api.checked_path("/output/script.js", directory=False)

    def test_output_open_is_exclusive_and_owner_only(self):
        handle = mock.MagicMock()
        handle.__enter__.return_value = handle
        with mock.patch.object(api, "checked_path", return_value=Path("/output/new.json")), \
                mock.patch.object(api.os, "open", return_value=123) as opened, \
                mock.patch.object(api.os, "fdopen", return_value=handle):
            api.write_catalog({"test": True}, "/output/new.json")
        flags = opened.call_args.args[1]
        self.assertTrue(flags & os.O_EXCL)
        self.assertTrue(flags & os.O_CREAT)
        self.assertEqual(opened.call_args.args[2], 0o600)
        handle.write.assert_called_once()

    def test_stdout_cli_does_not_write_files_or_open_network(self):
        catalog = api.assemble_catalog([scan('axios.get("/wapi/user/info");')])
        output = io.StringIO()
        with mock.patch.object(api, "build_catalog", return_value=catalog) as build, \
                mock.patch("socket.socket", side_effect=AssertionError("network must not be used")), \
                mock.patch.object(api.os, "open", side_effect=AssertionError("stdout must not open files")), \
                contextlib.redirect_stdout(output):
            code = api.main(["--scripts-dir", "public/scripts", "--scripts-dir", "public/readable", "--output", "-"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["coverage"]["unique_endpoints"], 1)
        self.assertEqual(build.call_args.args[0], ["public/scripts", "public/readable"])

    def test_partial_io_failure_cli_returns_one(self):
        catalog = api.assemble_catalog([], failed_files=[
            {"root_id": "root-1", "relative_file": "a.js", "sha256": None, "status": "excluded", "reason": "invalid_utf8"}
        ])
        with mock.patch.object(api, "build_catalog", return_value=catalog), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(api.main(["--scripts-dir", "public", "--output", "-"]), 1)

    def test_bad_cli_arguments_return_two_without_raw_path_disclosure(self):
        output = io.StringIO()
        with mock.patch.object(api, "build_catalog", side_effect=ValueError("13800138000")), \
                contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as error:
            api.main(["--scripts-dir", "public", "--output", "-"])
        self.assertEqual(error.exception.code, 2)
        self.assertNotIn("13800138000", output.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
