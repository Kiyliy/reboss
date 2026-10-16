"""The two observed form serializers are deliberately kept separate."""
import math
import re
from urllib.parse import quote


class _Undefined:
    def __repr__(self):
        return "UNDEFINED"


UNDEFINED = _Undefined()


def js_scalar(value):
    if value is UNDEFINED:
        return ""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int)):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        if value.is_integer():
            return str(int(value))
        raise ValueError("Use an explicit string for non-integral numeric fields")
    raise TypeError("Only explicit scalar values are accepted")


def spa_form(data):
    """v6763 module 86344/hk: encodeURIComponent values; arrays run backwards."""
    pairs = []
    for key, value in data.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_$.-]+", key):
            raise ValueError("SPA form keys must be simple explicit field names")
        values = reversed(value) if isinstance(value, list) else [value]
        suffix = "[]" if isinstance(value, list) else ""
        for item in values:
            encoded = quote(js_scalar(item), safe="~()*!.'-")
            pairs.append(key + suffix + "=" + encoded)
    return "&".join(pairs).encode("ascii")


def sms_form(data):
    """qs default subset: RFC3986, indexed arrays, null empty, undefined omitted."""
    pairs = []

    def add(key, value):
        if value is UNDEFINED:
            return
        if isinstance(value, dict):
            for child, item in value.items():
                add(f"{key}[{child}]", item)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                add(f"{key}[{index}]", item)
        else:
            text = "" if value is None else js_scalar(value)
            pairs.append(quote(str(key), safe="~-._") + "=" + quote(text, safe="~-._"))

    for key, value in data.items():
        add(key, value)
    return "&".join(pairs).encode("ascii")
