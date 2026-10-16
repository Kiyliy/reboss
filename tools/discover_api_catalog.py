#!/usr/bin/env python3
"""Offline, conservative /wapi/ literal inventory. This is NOT a JavaScript AST.

Only the Python standard library is used. JavaScript is never executed. No
network, source-map retrieval, import resolution, or request execution exists.
See ../NOTES.md for the intentionally bounded evidence and privacy contract.
"""

from __future__ import annotations

import argparse
import bisect
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Iterable, Sequence


VERSION = "0.1.0"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TEMPLATE_DEPTH = 32
HOLE = "\ufff0"  # Internal marker; an actual occurrence of this character is rejected.
KNOWN_GROUPS = ("passport", "user", "geek", "boss", "company", "common")
METHODS = frozenset(("GET", "POST"))
DIRECT_METHODS = {
    f"{client}.{method}": method.upper()
    for client in ("axios", "$", "jQuery")
    for method in ("get", "post")
}
OPTION_CALLS = frozenset(
    ("fetch", "window.fetch", "globalThis.fetch", "axios", "$.ajax", "jQuery.ajax")
)
AJAX_CALLS = frozenset(("$.ajax", "jQuery.ajax"))
PAYLOAD_KEYS = frozenset(("data", "body", "params", "headers", "payload", "cookie", "cookies"))
SECRET_SEGMENTS = frozenset(
    ("cookie", "cookies", "phone", "mobile", "telephone", "authorization",
     "password", "secret", "access_token", "refresh_token", "sessionid",
     "session", "token", "ticket", "credential")
)
RISK_WORDS = frozenset(
    ("passport", "zppassport", "auth", "sms", "send", "logout", "login", "register",
     "captcha", "qrcode", "token", "password", "session", "verify", "validate",
     "add", "create", "update", "delete", "remove", "set", "save", "submit",
     "confirm", "bind", "unbind", "upload", "apply", "cancel", "pay", "purchase",
     "refresh", "mark")
)
LIMITATIONS = (
    "Conservative lexical extraction, not an AST or complete JavaScript parser.",
    "Only URL-shaped string/template literals with a literal /wapi/ anchor are inventoried.",
    "Split or computed /wapi/ anchors, variable tables, imports, aliases, eval, and source maps are not resolved.",
    "Regex/division, unusual JavaScript syntax, malformed input, and tagged templates can reduce coverage.",
    "GET/POST evidence is syntactic only; bindings, wrapper behavior, runtime reachability, and server behavior are unverified.",
    "No default method is assumed; methods other than explicit GET/POST remain UNKNOWN.",
    "Same-object evidence requires a direct url value and a unique literal method without spreads/computed keys.",
    "Dynamic fragments are placeholders, not parameter names or a verified endpoint contract.",
    "Query/fragment contents, request bodies, headers, cookies, and parameter schemas are not collected.",
    "Route redaction intentionally loses detail; an innocuous-looking GET is not proven read-only.",
    "Private directories, symlinks, unsafe filenames, invalid UTF-8, and oversized inputs are excluded.",
    "Coverage describes only the supplied local files, not all application chunks or all API wrappers.",
    "Filesystem checks assume an offline snapshot; they are not a sandbox against concurrent directory replacement.",
)


@dataclass(slots=True)
class Token:
    kind: str
    value: str
    start: int
    end: int
    offsets: tuple[int, ...] = ()
    ends: tuple[int, ...] = ()
    template: bool = False
    holes: bool = False
    escaped: bool = False
    valid: bool = True


class Lexer:
    """Small lexer for evidence boundaries, without JavaScript evaluation."""

    def __init__(self, source: str):
        self.source = source
        self.regions: list[list[Token]] = []
        self.diagnostics: Counter[str] = Counter()
        self.incomplete = False

    @staticmethod
    def _ident_start(char: str) -> bool:
        return char.isalpha() or char in "_$"

    @staticmethod
    def _ident(char: str) -> bool:
        return char.isalnum() or char in "_$"

    def _escape(self, pos: int) -> tuple[str, int, bool]:
        text = self.source
        if pos + 1 >= len(text):
            return "", len(text), False
        char = text[pos + 1]
        if char in "\r\n":
            end = pos + 2
            if char == "\r" and end < len(text) and text[end] == "\n":
                end += 1
            return "", end, True
        simple = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v"}
        if char in simple:
            return simple[char], pos + 2, True
        if char == "0" and (pos + 2 == len(text) or not text[pos + 2].isdigit()):
            return "\0", pos + 2, True
        if char in "123456789":
            return "", pos + 2, False  # Do not guess legacy octal escapes.
        if char == "x":
            digits = text[pos + 2:pos + 4]
            if len(digits) == 2 and re.fullmatch(r"[0-9a-fA-F]{2}", digits):
                return chr(int(digits, 16)), pos + 4, True
            return "", min(pos + 4, len(text)), False
        if char == "u":
            if text[pos + 2:pos + 3] == "{":
                close = text.find("}", pos + 3, pos + 11)
                digits = text[pos + 3:close] if close >= 0 else ""
                if re.fullmatch(r"[0-9a-fA-F]{1,6}", digits or ""):
                    codepoint = int(digits, 16)
                    if codepoint <= 0x10FFFF:
                        return chr(codepoint), close + 1, True
                return "", close + 1 if close >= 0 else pos + 2, False
            digits = text[pos + 2:pos + 6]
            if re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                return chr(int(digits, 16)), pos + 6, True
            return "", min(pos + 6, len(text)), False
        return char, pos + 2, True

    def _literal(self, start: int, depth: int) -> tuple[Token, int]:
        text = self.source
        quote = text[start]
        template = quote == "`"
        values: list[str] = []
        offsets: list[int] = []
        ends: list[int] = []
        valid = True
        holes = False
        escaped = False
        pos = start + 1
        closed = False
        while pos < len(text):
            char = text[pos]
            if char == quote:
                pos += 1
                closed = True
                break
            if char == "\\":
                escaped = True
                value, end, ok = self._escape(pos)
                values.append(value)
                offsets.extend([pos] * len(value))
                ends.extend([end] * len(value))
                valid = valid and ok
                pos = end
                continue
            if template and text.startswith("${", pos):
                holes = True
                if depth >= MAX_TEMPLATE_DEPTH:
                    self.incomplete = True
                    self.diagnostics["template_depth_limit"] += 1
                    pos = len(text)
                    valid = False
                    break
                # A literal inside a query interpolation is still query data,
                # not a second discovered endpoint. Also suppress its nested
                # template regions; never preserve those values as evidence.
                prefix = "".join(values)
                in_query = "/wapi/" in prefix and ("?" in prefix or "#" in prefix)
                region_count = len(self.regions)
                expression, end, ok = self._code(pos + 2, True, depth + 1)
                if in_query:
                    del self.regions[region_count:]
                    self.diagnostics["query_template_regions_skipped"] += 1
                else:
                    self.regions.append(expression)
                values.append(HOLE)
                offsets.append(pos)
                ends.append(end)
                valid = valid and ok
                pos = end
                continue
            if not template and char in "\r\n\u2028\u2029":
                valid = False
                break
            if char == HOLE:
                valid = False
            values.append(char)
            offsets.append(pos)
            ends.append(pos + 1)
            pos += 1
        valid = valid and closed
        if not valid:
            self.diagnostics["invalid_literals"] += 1
            self.incomplete = True
        self.diagnostics["template_literals" if template else "string_literals"] += 1
        return Token(
            "literal", "".join(values), start, pos, tuple(offsets), tuple(ends),
            template, holes, escaped, valid,
        ), pos

    def _regex_end(self, start: int) -> int | None:
        text = self.source
        pos = start + 1
        in_class = False
        while pos < len(text):
            char = text[pos]
            if char in "\r\n\u2028\u2029":
                return None
            if char == "\\":
                pos += 2
                continue
            if char == "[":
                in_class = True
            elif char == "]":
                in_class = False
            elif char == "/" and not in_class:
                pos += 1
                while pos < len(text) and self._ident(text[pos]):
                    pos += 1
                return pos
            pos += 1
        return None

    @staticmethod
    def _regex_allowed(tokens: list[Token], after_control: bool) -> bool:
        if not tokens or after_control:
            return True
        previous = tokens[-1]
        if previous.kind == "identifier":
            return previous.value in (
                "return", "throw", "case", "yield", "await", "delete", "typeof",
                "void", "new", "in", "of", "instanceof", "else", "do",
            )
        return previous.kind == "punct" and previous.value not in (
            ")", "]", "++", "--", ".", "?.",
        )

    def _code(self, start: int, stop_at_brace: bool, depth: int) -> tuple[list[Token], int, bool]:
        text = self.source
        tokens: list[Token] = []
        braces = 0
        controls: list[bool] = []
        after_control = False
        pos = start
        while pos < len(text):
            char = text[pos]
            if char.isspace() or char == "\ufeff":
                pos += 1
                continue
            if text.startswith("//", pos):
                end = re.compile(r"[\r\n\u2028\u2029]").search(text, pos + 2)
                pos = end.start() if end else len(text)
                self.diagnostics["line_comments_skipped"] += 1
                continue
            if text.startswith("/*", pos):
                end = text.find("*/", pos + 2)
                self.diagnostics["block_comments_skipped"] += 1
                if end < 0:
                    self.incomplete = True
                    self.diagnostics["unclosed_comments"] += 1
                    return tokens, len(text), False
                pos = end + 2
                continue
            if char in "'\"`":
                token, pos = self._literal(pos, depth)
                tokens.append(token)
                after_control = False
                continue
            if char == "/" and self._regex_allowed(tokens, after_control):
                end = self._regex_end(pos)
                if end is not None:
                    tokens.append(Token("regex", "<regex>", pos, end))
                    self.diagnostics["regex_literals_skipped"] += 1
                    pos = end
                    after_control = False
                    continue
            if self._ident_start(char):
                end = pos + 1
                while end < len(text) and self._ident(text[end]):
                    end += 1
                tokens.append(Token("identifier", text[pos:end], pos, end))
                pos = end
                after_control = False
                continue
            if char.isdigit():
                end = pos + 1
                while end < len(text) and (self._ident(text[end]) or text[end] == "."):
                    end += 1
                tokens.append(Token("number", text[pos:end], pos, end))
                pos = end
                after_control = False
                continue
            punct = next(
                (item for item in (
                    "===", "!==", ">>>", "**=", "...", "=>", "==", "!=",
                    "<=", ">=", "&&", "||", "??", "?.", "++", "--", "+=", "-=",
                    "*=", "/=", "**", "<<", ">>", "&=", "|=", "^=",
                ) if text.startswith(item, pos)),
                char,
            )
            if punct == "}" and stop_at_brace and braces == 0:
                return tokens, pos + 1, True
            if punct == "{":
                braces += 1
            elif punct == "}":
                braces -= 1
            if punct == "(":
                controls.append(bool(tokens and tokens[-1].value in (
                    "if", "while", "for", "with", "switch", "catch",
                )))
                after_control = False
            elif punct == ")":
                after_control = controls.pop() if controls else False
            else:
                after_control = False
            tokens.append(Token("punct", punct, pos, pos + len(punct)))
            pos += len(punct)
        if stop_at_brace:
            self.incomplete = True
            self.diagnostics["unclosed_template_expressions"] += 1
        return tokens, pos, not stop_at_brace

    def run(self) -> list[list[Token]]:
        main, _, _ = self._code(0, False, 0)
        return [main, *self.regions]


class Structure:
    """Balanced delimiters and local property/argument ranges, not an AST."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pairs: dict[int, int] = {}
        self.parents: list[int | None] = []
        self.objects: dict[int, tuple[dict[str, tuple[int, int]], str | None]] = {}
        stack: list[int] = []
        self.balanced = True
        closing = {")": "(", "]": "[", "}": "{"}
        for index, token in enumerate(tokens):
            self.parents.append(stack[-1] if stack else None)
            if token.kind != "punct":
                continue
            if token.value in ("(", "[", "{"):
                stack.append(index)
            elif token.value in closing:
                if stack and tokens[stack[-1]].value == closing[token.value]:
                    opening = stack.pop()
                    self.pairs[opening] = index
                    self.pairs[index] = opening
                else:
                    self.balanced = False
        self.balanced = self.balanced and not stack

    def unwrap(self, start: int, end: int) -> tuple[int, int]:
        while start < end and self.tokens[start].value == "(" and self.pairs.get(start) == end - 1:
            start += 1
            end -= 1
        return start, end

    def split(self, start: int, end: int, separator: str = ",") -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        beginning = start
        index = start
        while index < end:
            token = self.tokens[index]
            if token.kind == "punct" and token.value == separator:
                result.append((beginning, index))
                beginning = index + 1
            if token.value in ("(", "[", "{") and index in self.pairs:
                index = self.pairs[index] + 1
            else:
                index += 1
        if beginning < end:
            result.append((beginning, end))
        elif beginning != start:
            result.append((end, end))
        return result

    def object_properties(self, opening: int) -> tuple[dict[str, tuple[int, int]], str | None]:
        if opening in self.objects:
            return self.objects[opening]
        properties: dict[str, tuple[int, int]] = {}
        reason = None
        if self.tokens[opening].value != "{" or opening not in self.pairs:
            return properties, "not_a_direct_object"
        for start, end in self.split(opening + 1, self.pairs[opening]):
            if start == end:  # A trailing comma is harmless.
                continue
            key = self.tokens[start]
            if (
                end - start < 3 or key.kind not in ("identifier", "literal")
                or key.template or not key.valid or self.tokens[start + 1].value != ":"
            ):
                reason = "spread_computed_or_nonliteral_property"
                break
            if key.value in properties:
                reason = "duplicate_object_property"
                break
            properties[key.value] = (start + 2, end)
        self.objects[opening] = properties, reason
        return properties, reason

    def callee(self, opening: int) -> str | None:
        index = opening - 1
        if index < 0 or self.tokens[index].kind != "identifier":
            return None
        parts = [self.tokens[index].value]
        index -= 1
        while index >= 1 and self.tokens[index].value == "." and self.tokens[index - 1].kind == "identifier":
            parts[:0] = [self.tokens[index - 1].value, "."]
            index -= 2
        if index >= 0 and self.tokens[index].value in (".", "?.", "new", "function"):
            return None
        return "".join(parts)

    def ancestors(self, index: int) -> Iterable[int]:
        parent = self.parents[index]
        while parent is not None:
            yield parent
            parent = self.parents[parent]

    def expression_parts(self, start: int, end: int, literal_index: int) -> list[tuple[int, int]] | None:
        start, end = self.unwrap(start, end)
        raw_pieces = self.split(start, end, "+")
        pieces = [self.unwrap(a, b) for a, b in raw_pieces]
        if any(a == b for a, b in pieces):
            return None
        # Do not confuse `url + x ? other : fallback`, `url + x === y`,
        # comma expressions, etc. with a URL-valued concatenation. A grouped
        # operand may be opaque, but ungrouped operands must be simple atoms.
        if len(pieces) > 1 and any(not self.concat_atom(a, b) for a, b in raw_pieces):
            return None
        for a, b in pieces:
            if a <= literal_index < b:
                return pieces if a == literal_index and b == literal_index + 1 else None
        return None

    def concat_atom(self, start: int, end: int) -> bool:
        if start >= end:
            return False
        token = self.tokens[start]
        if token.value == "(" and self.pairs.get(start) == end - 1:
            return True
        if end - start == 1:
            return token.kind in ("identifier", "number", "literal")
        if token.kind != "identifier":
            return False
        index = start + 1
        while index < end:
            if self.tokens[index].value in (".", "?."):
                if index + 1 >= end or self.tokens[index + 1].kind != "identifier":
                    return False
                index += 2
            elif self.tokens[index].value in ("(", "[") and index in self.pairs:
                index = self.pairs[index] + 1
            else:
                return False
        return index == end

    def wrapped_literal_span(self, index: int) -> tuple[int, int]:
        start, end = index, index + 1
        for parent in self.ancestors(index):
            if self.tokens[parent].value == "(" and self.pairs.get(parent) == end:
                call_like = self.callee(parent) is not None or (
                    parent > 0 and self.tokens[parent - 1].value in (")", "]")
                )
                if parent + 1 == start and not call_like:
                    start, end = parent, end + 1
                    continue
            break
        return start, end

    def local_expression(self, index: int) -> list[tuple[int, int]]:
        start, end = self.wrapped_literal_span(index)
        parent = self.parents[start]
        lower = parent + 1 if parent is not None else 0
        upper = self.pairs.get(parent, len(self.tokens)) if parent is not None else len(self.tokens)
        adjacent_plus = (
            (start > lower and self.tokens[start - 1].value == "+")
            or (end < upper and self.tokens[end].value == "+")
        )
        if not adjacent_plus:
            return [(index, index + 1)]
        boundaries = frozenset((
            ",", ";", ":", "=", "=>", "?", "&&", "||", "??", "+=", "-=",
            "return", "throw", "yield", "const", "let", "var",
        ))
        left, right = start, end
        while left > lower:
            previous = left - 1
            if self.tokens[previous].value in boundaries:
                break
            if self.tokens[previous].value in (")", "]", "}") and previous in self.pairs:
                previous = self.pairs[previous]
            left = previous
        while right < upper:
            if self.tokens[right].value in boundaries:
                break
            if self.tokens[right].value in ("(", "[", "{") and right in self.pairs:
                right = self.pairs[right] + 1
            else:
                right += 1
        return self.expression_parts(left, right, index) or [(index, index + 1)]

    def in_payload(self, opening: int) -> bool:
        for parent in self.ancestors(opening):
            # A call is a new context, not the containing object's payload.
            if self.tokens[parent].value == "(" and self.callee(parent):
                return False
            if self.tokens[parent].value == "{":
                props, _ = self.object_properties(parent)
                return any(key in PAYLOAD_KEYS and a <= opening < b for key, (a, b) in props.items())
        return False


def location(start: int, end: int, line_starts: Sequence[int]) -> dict[str, int]:
    line = bisect.bisect_right(line_starts, start)
    return {
        "char_start": start, "char_end": end,
        "line": line, "column": start - line_starts[line - 1] + 1,
    }


def unknown_evidence(reason: str = "no_explicit_local_method") -> dict:
    return {"method": "UNKNOWN", "rule": reason, "runtime_verified": False}


def literal_method(structure: Structure, span: tuple[int, int]) -> tuple[str | None, Token | None]:
    start, end = structure.unwrap(*span)
    if end - start != 1:
        return None, None
    token = structure.tokens[start]
    if token.kind != "literal" or token.template or not token.valid:
        return None, None
    return (token.value.upper() if token.value.upper() in METHODS else None), token


def infer_method(structure: Structure, index: int, line_starts: Sequence[int]) -> dict:
    tokens = structure.tokens
    if not structure.balanced:
        return unknown_evidence("unbalanced_delimiters")
    fallback = unknown_evidence()
    for parent in structure.ancestors(index):
        if tokens[parent].value == "{":
            props, reason = structure.object_properties(parent)
            # Even ambiguous objects retain their already parsed URL, for an
            # explanatory UNKNOWN rather than proximity-based inference.
            url_span = props.get("url")
            if not url_span or not structure.expression_parts(*url_span, index):
                continue
            if reason:
                return unknown_evidence(reason)
            if structure.in_payload(parent):
                return unknown_evidence("url_in_payload_not_request_config")
            method_span = props.get("method")
            rule = "same_url_method_object"
            if method_span is None and "type" in props:
                outer = structure.parents[parent]
                if outer is not None and tokens[outer].value == "(" and structure.callee(outer) in AJAX_CALLS:
                    method_span = props["type"]
                    rule = "ajax_url_type_object"
            if method_span is None:
                return unknown_evidence("request_object_without_literal_method")
            method, method_token = literal_method(structure, method_span)
            if method is None:
                return unknown_evidence("method_not_a_literal_get_or_post")
            if "method" in props and "type" in props:
                return unknown_evidence("multiple_method_selectors")
            return {
                "method": method, "rule": rule, "runtime_verified": False,
                "method_location": location(method_token.start, method_token.end, line_starts),
                "request_location": location(tokens[parent].start, tokens[structure.pairs[parent]].end, line_starts),
            }
        if tokens[parent].value != "(":
            continue
        callee = structure.callee(parent)
        if callee not in DIRECT_METHODS and callee not in OPTION_CALLS:
            continue
        arguments = structure.split(parent + 1, structure.pairs[parent])
        arguments = [span for span in arguments if span[0] != span[1]]
        if not arguments or not structure.expression_parts(*arguments[0], index):
            continue
        if callee in DIRECT_METHODS:
            method_token = tokens[parent - 1]
            return {
                "method": DIRECT_METHODS[callee], "rule": "allowlisted_direct_request_member",
                "callee": callee, "runtime_verified": False,
                "method_location": location(method_token.start, method_token.end, line_starts),
                "request_location": location(tokens[parent - 3].start, tokens[structure.pairs[parent]].end, line_starts),
            }
        if len(arguments) != 2:
            return unknown_evidence("no_default_method_assumed")
        start, end = structure.unwrap(*arguments[1])
        if tokens[start].value != "{" or structure.pairs.get(start) != end - 1:
            return unknown_evidence("options_not_a_direct_object")
        props, reason = structure.object_properties(start)
        if reason:
            return unknown_evidence(reason)
        key = "method" if "method" in props else "type" if callee in AJAX_CALLS else "method"
        if key not in props:
            return unknown_evidence("no_default_method_assumed")
        if "method" in props and "type" in props:
            return unknown_evidence("multiple_method_selectors")
        method, method_token = literal_method(structure, props[key])
        if method is None:
            return unknown_evidence("method_not_a_literal_get_or_post")
        return {
            "method": method, "rule": "direct_call_literal_options_method",
            "callee": callee, "runtime_verified": False,
            "method_location": location(method_token.start, method_token.end, line_starts),
            "request_location": location(tokens[parent - 1].start, tokens[structure.pairs[parent]].end, line_starts),
        }
    return fallback


def safe_relative_file(value: str) -> bool:
    """Reject path traversal and secret-shaped filenames, never normalize them."""
    if not value or "\\" in value or value.startswith("/"):
        return False
    parts = value.split("/")
    return (
        not any(part in ("", ".", "..") or part.casefold() == "private" for part in parts)
        and all(re.fullmatch(r"[A-Za-z0-9_.~+$-]+", part) for part in parts)
        and not re.search(r"\d{11,}", value)
        and not PurePosixPath(value).is_absolute()
    )


def normalize_route(path: str) -> tuple[str | None, dict, str | None]:
    """Accept only safe route shapes; discard values rather than logging them."""
    flags = {"redacted": False, "percent_unreserved_normalized": False}
    if not path.startswith("/wapi/"):
        return None, flags, "not_wapi_root"
    if "%" in path:
        if re.search(r"%(?![0-9a-fA-F]{2})", path):
            return None, flags, "invalid_percent_escape"

        def decode(match: re.Match) -> str:
            char = chr(int(match.group(1), 16))
            return char if re.fullmatch(r"[A-Za-z0-9._~-]", char) else "%"

        path = re.sub(r"%([0-9a-fA-F]{2})", decode, path)
        if "%" in path:
            return None, flags, "encoded_reserved_or_nonascii_character"
        flags["percent_unreserved_normalized"] = True
    checked = path.replace(HOLE, "")
    if not re.fullmatch(r"/[A-Za-z0-9/._~-]*", checked):
        return None, flags, "unsafe_route_character"
    segments = path.split("/")
    if any(part in (".", "..") for part in segments):
        return None, flags, "dot_segment"
    if any(part == "" for part in segments[1:-1]):
        return None, flags, "empty_route_segment"
    if not any(segments[2:]):
        return None, flags, "incomplete_wapi_root"
    safe: list[str] = []
    previous = ""
    for segment in segments:
        original = segment
        if segment and previous.casefold() in SECRET_SEGMENTS:
            segment = "{redacted}"
            flags["redacted"] = True
        elif segment:
            segment, count = re.subn(r"\d{7,}", "{redacted}", segment)
            phone_shaped = bool(re.fullmatch(r"[0-9._~-]+", segment)) and sum(char.isdigit() for char in segment) >= 7
            if count or phone_shaped or len(segment) > 64:
                segment = "{redacted}" if phone_shaped or len(segment) > 64 else segment
                flags["redacted"] = True
        safe.append(segment.replace(HOLE, "{dynamic}"))
        previous = original
    return "/".join(safe), flags, None


def extract_literal(structure: Structure, index: int) -> tuple[dict | None, str | None]:
    token = structure.tokens[index]
    if not token.valid or "/wapi/" not in token.value:
        return None, None
    pieces = structure.local_expression(index)
    rendered: list[str] = []
    anchor_base = 0
    total = 0
    dynamic = False
    has_template = False
    all_valid = True
    for start, end in pieces:
        part = structure.tokens[start]
        if end - start == 1 and part.kind == "literal":
            value = part.value
            dynamic |= part.holes
            has_template |= part.template
            all_valid &= part.valid
            if start == index:
                anchor_base = total
        else:
            value = HOLE
            dynamic = True
        rendered.append(value)
        total += len(value)
    if not all_valid:
        return None, "invalid_literal_expression"
    value = "".join(rendered)
    anchor_offset = token.value.find("/wapi/")
    anchor_in_value = anchor_base + anchor_offset
    # Never interpret an API path carried inside another URL's query/fragment.
    query = value.find("?")
    fragment = value.find("#")
    cutoff = min((pos for pos in (query, fragment) if pos >= 0), default=len(value))
    if anchor_in_value >= cutoff:
        return None, "wapi_inside_query_or_fragment"
    path_value = value[:cutoff]
    origin_stripped = False
    prefix_dynamic = False
    if path_value.startswith("/wapi/"):
        path = path_value
    elif re.match(r"^https?://[^/?#\s]+/wapi/", path_value):
        path = path_value[path_value.find("/wapi/"):]
        origin_stripped = True
    elif path_value.startswith(HOLE + "/wapi/"):
        path = path_value[1:]
        prefix_dynamic = True
    else:
        return None, "non_url_shaped_literal"
    # Non-concatenation transformations and tagged templates must not appear
    # to be complete URL contracts or receive a direct-call method guess.
    wrapped_start, wrapped_end = structure.wrapped_literal_span(index)
    transformed = wrapped_end < len(structure.tokens) and structure.tokens[wrapped_end].value in (".", "?.", "[")
    unresolved_concat = len(pieces) == 1 and (
        (wrapped_start > 0 and structure.tokens[wrapped_start - 1].value == "+")
        or (wrapped_end < len(structure.tokens) and structure.tokens[wrapped_end].value == "+")
    )
    tagged = token.template and index > 0 and (
        structure.tokens[index - 1].kind == "identifier"
        or structure.tokens[index - 1].value in (")", "]")
    )
    if tagged and structure.tokens[index - 1].value in ("return", "throw", "yield"):
        tagged = False
    dynamic |= transformed or tagged or unresolved_concat
    normalized, flags, reason = normalize_route(path)
    if reason:
        return None, reason
    literal_end = min(len(token.value), max(anchor_offset, cutoff - anchor_base))
    if literal_end <= anchor_offset:
        return None, "empty_literal_path_span"
    path_dynamic = HOLE in path or transformed or tagged or unresolved_concat
    return {
        "path": normalized,
        "char_start": token.offsets[anchor_offset],
        "char_end": token.ends[literal_end - 1],
        "template": token.template,
        "expression_has_template": has_template,
        "dynamic": bool(dynamic),
        "dynamic_in_path": bool(path_dynamic),
        "dynamic_prefix": prefix_dynamic,
        "concatenated": len(pieces) > 1 or unresolved_concat,
        "expression_unresolved": unresolved_concat,
        "query_stripped": query >= 0 and (fragment < 0 or query < fragment),
        "fragment_stripped": fragment >= 0,
        "origin_stripped": origin_stripped,
        "literal_escaped": token.escaped,
        "transformed_or_tagged": transformed or tagged,
        "path_complete": not (path_dynamic or prefix_dynamic or flags["redacted"]),
        **flags,
    }, None


def scan_source(source: str, relative_file: str, sha256: str | None = None, root_id: str = "root-1") -> dict:
    """In-memory entry point, useful for offline tests and read-only pipelines."""
    if not safe_relative_file(relative_file):
        raise ValueError("unsafe relative source filename")
    digest = sha256 or hashlib.sha256(source.encode("utf-8")).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid SHA256")
    if not re.fullmatch(r"root-[1-9][0-9]*", root_id):
        raise ValueError("invalid root identifier")
    line_starts = [0, *(match.end() for match in re.finditer(r"\r\n|[\r\n\u2028\u2029]", source))]
    lexer = Lexer(source)
    regions = lexer.run()
    occurrences: list[dict] = []
    rejected: Counter[str] = Counter()
    for tokens in regions:
        structure = Structure(tokens)
        if not structure.balanced:
            lexer.diagnostics["unbalanced_token_regions"] += 1
        for index, token in enumerate(tokens):
            if token.kind != "literal":
                continue
            extracted, reason = extract_literal(structure, index)
            if reason:
                rejected[reason] += 1
            if extracted is None:
                continue
            evidence = infer_method(structure, index, line_starts)
            if lexer.incomplete:
                evidence = unknown_evidence("incomplete_lexical_input")
            if extracted["transformed_or_tagged"]:
                evidence = unknown_evidence("transformed_or_tagged_literal")
            if extracted["expression_unresolved"]:
                evidence = unknown_evidence("unsupported_literal_expression")
            path = extracted.pop("path")
            start, end = extracted.pop("char_start"), extracted.pop("char_end")
            occurrences.append({
                "path": path, "root_id": root_id, "relative_file": relative_file,
                "sha256": digest, **location(start, end, line_starts),
                "literal_location": location(token.start, token.end, line_starts),
                "method": evidence["method"], "method_evidence": evidence,
                **extracted,
            })
    occurrences.sort(key=lambda item: (item["char_start"], item["literal_location"]["char_start"]))
    return {
        "root_id": root_id, "relative_file": relative_file, "sha256": digest,
        "occurrences": occurrences, "diagnostics": dict(sorted(lexer.diagnostics.items())),
        "rejected_candidates": dict(sorted(rejected.items())),
        "lexically_complete": not lexer.incomplete,
    }


def group_for_path(path: str) -> str:
    namespace = path.split("/")[2].casefold()
    alias = namespace[2:] if namespace.startswith("zp") else namespace
    if alias in KNOWN_GROUPS:
        return alias
    return namespace if re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", namespace) else "other"


def capability_for(path: str, occurrences: list[dict]) -> dict:
    split_camel = re.sub(r"([a-z])([A-Z])", r"\1/\2", path)
    words = set(re.findall(r"[a-z]+", split_camel.casefold()))
    methods = {item["method"] for item in occurrences}
    reasons: list[str] = []
    risky = (
        bool(words & RISK_WORDS) or group_for_path(path) == "passport"
        or any(hint in path.casefold() for hint in ("logout", "sms", "send"))
    )
    if risky:
        reasons.append("auth_or_state_change_path_hint")
    if "POST" in methods:
        reasons.append("explicit_post_evidence")
    if any(item["dynamic"] or not item["path_complete"] for item in occurrences):
        reasons.append("dynamic_or_incomplete_route")
    if "UNKNOWN" in methods:
        reasons.append("unknown_method_occurrence")
    if risky or "POST" in methods:
        candidate = "MUTATION_OR_AUTH_CANDIDATE"
    elif methods == {"GET"} and not reasons:
        candidate = "READ_CANDIDATE_UNVERIFIED"
        reasons.append("only_explicit_get_evidence")
    else:
        candidate = "UNKNOWN"
    return {
        "candidate": candidate, "basis": "static_syntax_and_path_hints_only",
        "reasons": reasons, "manual_verification_required": True,
        "read_only_verified": False, "safe_to_request": False,
        "may_change_state": True if risky or "POST" in methods else None,
    }


def assemble_catalog(scans: Sequence[dict], roots: Sequence[dict] = (), skipped: dict | None = None,
                     failed_files: Sequence[dict] = (), max_file_bytes: int = MAX_FILE_BYTES) -> dict:
    by_path: dict[str, list[dict]] = {}
    files: list[dict] = []
    rejected: Counter[str] = Counter()
    for scan in scans:
        for occurrence in scan["occurrences"]:
            item = dict(occurrence)
            path = item.pop("path")
            by_path.setdefault(path, []).append(item)
        rejected.update(scan["rejected_candidates"])
        files.append({
            key: scan[key] for key in (
                "root_id", "relative_file", "sha256", "diagnostics", "lexically_complete",
            )
        } | {"status": "scanned", "occurrences": len(scan["occurrences"])})
    files.extend(failed_files)
    groups: dict[str, list[dict]] = {group: [] for group in KNOWN_GROUPS}
    method_counts: Counter[str] = Counter()
    all_occurrences: list[dict] = []
    for path in sorted(by_path):
        occurrences = sorted(
            by_path[path], key=lambda item: (item["root_id"], item["relative_file"], item["char_start"])
        )
        methods = sorted({item["method"] for item in occurrences})
        explicit = set(methods) - {"UNKNOWN"}
        if len(explicit) > 1:
            status = "CONFLICTING_STATIC_EVIDENCE"
        elif not explicit:
            status = "UNKNOWN"
        elif "UNKNOWN" in methods:
            status = "PARTIAL_STATIC_EVIDENCE"
        else:
            status = "STATIC_EXPLICIT_ONLY"
        group = group_for_path(path)
        groups.setdefault(group, []).append({
            "path": path, "group": group, "methods": methods, "method_status": status,
            "runtime_verified": False,
            "parameters": {"status": "UNKNOWN", "collected": False},
            "capability": capability_for(path, occurrences),
            "occurrences": occurrences,
        })
        method_counts.update(item["method"] for item in occurrences)
        all_occurrences.extend(occurrences)
    return {
        "schema_version": "1.0",
        "tool": {
            "name": "discover_api_catalog", "version": VERSION,
            "extraction": "conservative_js_lexer_not_ast", "offline": True,
            "executes_javascript": False, "issues_network_requests": False,
        },
        "positions": {
            "offset_unit": "Unicode code points in the UTF-8-decoded file",
            "char_start": "zero-based inclusive; first source character of the literal /wapi/ anchor",
            "char_end": "zero-based exclusive; URL-bearing literal fragment before query/fragment",
            "line_and_column": "one-based; CRLF is a single line break",
            "sha256": "SHA-256 of the original file bytes, not normalized text",
        },
        "privacy": {
            "raw_source_snippets_collected": False, "query_keys_or_values_collected": False,
            "fragment_values_collected": False, "request_bodies_collected": False,
            "headers_or_cookies_collected": False, "parameter_names_inferred": False,
            "dynamic_expression_text_collected": False,
            "sensitive_route_values": "redacted or rejected, without rejected-value samples",
        },
        "coverage": {
            "status": "PARTIAL_STATIC_CANDIDATES", "exhaustive": False,
            "roots": list(roots), "files_scanned": len(scans),
            "files_failed": len(failed_files), "skipped_counts": dict(sorted((skipped or {}).items())),
            "max_file_bytes": max_file_bytes, "unique_endpoints": len(by_path),
            "occurrences": len(all_occurrences),
            "occurrences_by_method": {method: method_counts[method] for method in ("GET", "POST", "UNKNOWN")},
            "template_occurrences": sum(item["template"] for item in all_occurrences),
            "dynamic_occurrences": sum(item["dynamic"] for item in all_occurrences),
            "rejected_candidates": dict(sorted(rejected.items())),
            "limitations": list(LIMITATIONS),
        },
        "files": sorted(files, key=lambda item: (item["root_id"], item["relative_file"])),
        "groups": groups,
    }


def checked_path(raw: str, *, directory: bool) -> Path:
    if not raw or "\0" in raw or "\\" in raw or "://" in raw or ".." in Path(raw).parts:
        raise ValueError("unsafe filesystem path")
    absolute = Path(os.path.abspath(raw))
    if any(part.casefold() == "private" for part in absolute.parts):
        raise ValueError("private directories are outside the scan/output scope")
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise ValueError("symlink paths are not permitted")
    if directory and not absolute.is_dir():
        raise ValueError("scripts directory does not exist or is not a directory")
    if not directory:
        if absolute.exists():
            raise ValueError("output already exists; choose a new JSON path")
        if not absolute.parent.is_dir():
            raise ValueError("output parent directory must already exist")
        if absolute.suffix.casefold() != ".json":
            raise ValueError("output must have a .json suffix, or use '-' for stdout")
    return absolute


def iter_script_files(root: Path, skipped: Counter) -> Iterable[tuple[Path, str]]:
    def walk_error(_error: OSError) -> None:
        skipped["unreadable_directories"] += 1

    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False, onerror=walk_error):
        current_path = Path(current)
        kept: list[str] = []
        for name in sorted(directories):
            child = current_path / name
            relative = child.relative_to(root).as_posix()
            if name.casefold() == "private":
                skipped["private_directories"] += 1
            elif child.is_symlink():
                skipped["symlinks"] += 1
            elif not safe_relative_file(relative):
                skipped["unsafe_directory_names"] += 1
            else:
                kept.append(name)
        directories[:] = kept
        for name in sorted(filenames):
            child = current_path / name
            if child.suffix.casefold() not in (".js", ".mjs", ".cjs"):
                continue
            relative = child.relative_to(root).as_posix()
            if child.is_symlink():
                skipped["symlinks"] += 1
            elif not safe_relative_file(relative):
                skipped["unsafe_file_names"] += 1
            else:
                yield child, relative


def read_script(path: Path, root: Path, max_file_bytes: int) -> bytes:
    relative = path.relative_to(root)
    if not safe_relative_file(relative.as_posix()):
        raise ValueError("unsafe source path")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError("symlink source path")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("nonregular_source")
        if metadata.st_size > max_file_bytes:
            raise ValueError("file_size_limit")
        data = handle.read(max_file_bytes + 1)
        if len(data) > max_file_bytes:
            raise ValueError("file_size_limit")
        return data


def build_catalog(script_dirs: Sequence[str], max_file_bytes: int = MAX_FILE_BYTES) -> dict:
    if max_file_bytes <= 0:
        raise ValueError("max-file-bytes must be positive")
    roots = list(dict.fromkeys(checked_path(raw, directory=True) for raw in script_dirs))
    if not roots:
        raise ValueError("at least one scripts directory is required")
    for index, root in enumerate(roots):
        if any(root in other.parents or other in root.parents for other in roots[index + 1:]):
            raise ValueError("overlapping scripts roots are not permitted")
    scans: list[dict] = []
    failed: list[dict] = []
    skipped: Counter[str] = Counter()
    root_records: list[dict] = []
    for number, root in enumerate(roots, 1):
        root_id = f"root-{number}"
        root_records.append({"root_id": root_id, "label": root.name if safe_relative_file(root.name) else root_id})
        for path, relative in iter_script_files(root, skipped):
            digest = None
            try:
                raw = read_script(path, root, max_file_bytes)
                digest = hashlib.sha256(raw).hexdigest()
                text = raw.decode("utf-8")
                scans.append(scan_source(text, relative, digest, root_id))
            except UnicodeDecodeError:
                failed.append({
                    "root_id": root_id, "relative_file": relative, "sha256": digest,
                    "status": "excluded", "reason": "invalid_utf8",
                })
            except (OSError, ValueError) as error:
                # Never serialize exception text, which may contain private paths.
                reason = str(error) if isinstance(error, ValueError) and str(error) in (
                    "file_size_limit", "nonregular_source",
                ) else "unreadable_or_unsafe_source"
                failed.append({
                    "root_id": root_id, "relative_file": relative, "sha256": digest,
                    "status": "excluded", "reason": reason,
                })
    return assemble_catalog(scans, root_records, skipped, failed, max_file_bytes)


def write_catalog(catalog: dict, output: str) -> None:
    serialized = json.dumps(catalog, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if output == "-":
        sys.stdout.write(serialized)
        return
    destination = checked_path(output, directory=False)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(destination, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(serialized)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripts-dir", action="append", required=True, help="Local JS directory; repeat for nonoverlapping public roots")
    parser.add_argument("--output", required=True, help="New .json file (never overwritten), or '-' for stdout")
    parser.add_argument("--max-file-bytes", type=int, default=MAX_FILE_BYTES, help="Per-file size limit (default: 64 MiB)")
    arguments = parser.parse_args(argv)
    try:
        if arguments.output != "-":
            checked_path(arguments.output, directory=False)
        catalog = build_catalog(arguments.scripts_dir, arguments.max_file_bytes)
        write_catalog(catalog, arguments.output)
    except (ValueError, OSError):
        parser.exit(2, "error: invalid/unreadable local input or unsafe/existing output; no external request was made\n")
    failed = catalog["coverage"]["files_failed"] or catalog["coverage"]["skipped_counts"].get("unreadable_directories", 0)
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
