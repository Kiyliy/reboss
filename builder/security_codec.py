"""Partial, source-assisted value models for five dynamic-script helpers.

Source: https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js
SHA-256: 641c23791eddaceea84d307930bf90a2ccd2d0c93eaa07175426b085d87fa65a

These functions are NOT a stoken generator. They do not recover the input
packet, initialization, environment collection, randomness, or server policy.
The original script has not been executed for a target-runtime comparison.

The modeled domain is ordinary dense integer values, standard built-ins, and
normal completion of the reviewed branches. Inputs are copied: target array
mutation, getters, proxies, typed-array overflow, and exception suppression are
not reproduced. Type/range/size rejection is an explicit local design choice.
"""

from __future__ import annotations

import base64


MAX_ELEMENTS = 65_536
IntegerValues = list[int] | tuple[int, ...] | bytes | bytearray


class PartialCodecInputError(ValueError):
    """Input is outside the deliberately bounded, modeled domain."""


def _values(values: IntegerValues, maximum: int, label: str) -> list[int]:
    if type(values) not in (list, tuple, bytes, bytearray):
        raise PartialCodecInputError(f"{label} must be a dense integer sequence")
    if len(values) > MAX_ELEMENTS:
        raise PartialCodecInputError(f"{label} exceeds the local size limit")
    result = list(values)
    if any(type(value) is not int or not 0 <= value <= maximum for value in result):
        raise PartialCodecInputError(
            f"{label} requires integers in the range 0..{maximum}"
        )
    return result


def utf16_units_15983(text: str) -> list[int]:
    """Model the charCodeAt loop, including surrogate code units, not MD5."""
    if type(text) is not str:
        raise PartialCodecInputError("text must be a string")
    if len(text) > MAX_ELEMENTS:
        raise PartialCodecInputError("text exceeds the local size limit")
    raw = text.encode("utf-16-le", errors="surrogatepass")
    if len(raw) // 2 > MAX_ELEMENTS:
        raise PartialCodecInputError("text exceeds the UTF-16 unit limit")
    return [raw[index] | raw[index + 1] << 8 for index in range(0, len(raw), 2)]


def xor_mix_5810(values: IntegerValues, key_units: IntegerValues) -> list[int]:
    """Model (value + 3) XOR repeated key unit; intentionally no byte mask.

    Only byte-valued input and a nonempty UTF-16-unit key are modeled here.
    The source's other coercion and empty-key behaviors are outside this API.
    """
    data = _values(values, 255, "values")
    key = _values(key_units, 65_535, "key_units")
    if not key:
        raise PartialCodecInputError("key_units must not be empty")
    return [(value + 3) ^ key[index % len(key)] for index, value in enumerate(data)]


def offset_transform_10702(values: IntegerValues) -> list[int]:
    """Model the output values of XOR 1, +1, reverse, +8, reverse.

    On the supported plain-array domain this is (value XOR 1) + 9 in the
    original order. Values may exceed 255 or 65535; no truncation is added.
    """
    data = _values(values, 65_535, "values")
    return [(value ^ 1) + 9 for value in data]


def numeric_utf8_303(values: IntegerValues) -> bytes:
    """Model the 1/2/3-byte numeric encoder on the 0..65535 input domain.

    This is not a complete Unicode scalar-value encoder: surrogate units are
    emitted separately and there is no modeled four-byte branch.
    """
    data = _values(values, 65_535, "values")
    output = bytearray()
    for value in data:
        if value < 128:
            output.append(value)
        elif value < 2048:
            output.extend((value >> 6 | 192, value & 63 | 128))
        else:
            output.extend(
                (value >> 12 | 224, value >> 6 & 63 | 128, value & 63 | 128)
            )
    return bytes(output)


def base64_bytes_18580(values: IntegerValues) -> str:
    """Model only the byte-array Base64 branch; the string branch is omitted."""
    data = _values(values, 255, "values")
    return base64.b64encode(bytes(data)).decode("ascii")
