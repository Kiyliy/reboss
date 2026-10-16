"""Source-assisted SPA v6763 traceId reconstruction, not a security token.

Reference: module 94627/r5 in vendor-1.a73b9143.js, SHA-256
1249371f6d360d9e5b693eb2962d09ad65c1e2947e4c62b49d4c624616e56367.
The browser branch uses IEEE-754 multiplication, not integer Math.imul and
not the Node-only HMAC branch found in a different published bundle.
"""
import math
import random
import re
import time

PROFILE = "geek_spa_v6763"
CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
MASK32 = (1 << 32) - 1
MAX_SAFE_INTEGER = (1 << 53) - 1
CORE_PATTERN = re.compile(r"[0-9a-f]{13}[0-9a-zA-Z]{6}\Z")
TRACE_PATTERN = re.compile(r"F-([0-9a-f]{13}[0-9a-zA-Z]{6})([0-9a-zA-Z]{3})\Z")
_RANDOM = random.SystemRandom()


def _int32(value):
    value &= MASK32
    return value - (1 << 32) if value & (1 << 31) else value


def _js_product_uint32(left, right):
    # JavaScript Number multiplication rounds before the >>> 0 conversion.
    # Python's exact integer product gives different answers for some inputs.
    return int(float(left) * float(right)) & MASK32


def _mix(value, first, second):
    value = _js_product_uint32(first, abs(_int32(value)))
    value = (value ^ (value >> 16)) & MASK32
    value = _js_product_uint32(second, value)
    value = (value ^ (value >> 13)) & MASK32
    return CHARS[value % len(CHARS)]


def trace_checksum(core):
    """Return the three-character browser checksum for a 19-character core."""
    if not isinstance(core, str) or not CORE_PATTERN.fullmatch(core):
        raise ValueError("Trace core must be 13 lowercase hex and 6 base62 characters")
    first = second = third = 0
    for char in core:
        first = _int32((first << 5) - first + ord(char))
    for index in range(len(core) - 1, -1, -1):
        second = _int32((second << 7) - second + ord(core[index]) * (index + 1))
    middle = len(core) // 2
    for index, char in enumerate(core):
        third = _int32((third << 3) - third + ord(char) * (abs(index - middle) + 1))
    return (
        _mix(first ^ second, 0x9E3779B1, 0x85EBCA6B)
        + _mix(second ^ third, 0xC2B2AE35, 0x9E3779B1)
        + _mix(third ^ first, 0x27D4EB2D, 0x85EBCA6B)
    )


def generate_trace_id(*, now_ms=None, random_values=None):
    """Generate a new request ID; never use this to alter a captured replay.

    Inject exactly six [0,1) draws to reproduce the same source-level inputs.
    Default entropy is local and does not reproduce a browser's PRNG state.
    """
    if now_ms is None:
        now_ms = time.time_ns() // 1_000_000
    if type(now_ms) is not int or not 0 <= now_ms <= MAX_SAFE_INTEGER:
        raise ValueError("now_ms must be a nonnegative JavaScript safe integer")
    draws = [_RANDOM.random() for _ in range(6)] if random_values is None else list(random_values)
    if len(draws) != 6 or any(
        type(value) not in (float, int) or not 0 <= value < 1 or not math.isfinite(value)
        for value in draws
    ):
        raise ValueError("Exactly six finite random values in [0,1) are required")
    timestamp = format(now_ms, "x").rjust(13, "0")[-13:]
    core = timestamp + "".join(CHARS[math.floor(value * len(CHARS))] for value in draws)
    return "F-" + core + trace_checksum(core)


def valid_trace_id(value):
    """Check local format/checksum, not authenticity or server acceptance."""
    if not isinstance(value, str):
        return False
    match = TRACE_PATTERN.fullmatch(value)
    return bool(match and trace_checksum(match[1]) == match[2])
