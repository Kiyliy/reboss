"""Ordered query parameters, with a separate immutable raw-capture mode."""
from urllib.parse import urlencode


class Params:
    def __init__(self, pairs=(), *, raw=None):
        self._pairs = []
        self._raw = raw
        if raw is not None:
            if not isinstance(raw, str) or any(c in raw for c in "\r\n\0#"):
                raise ValueError("Invalid raw query")
            if pairs:
                raise ValueError("Cannot combine raw query and structured parameters")
        for key, value in pairs:
            self.add(key, value)

    def add(self, key, value):
        if self._raw is not None:
            raise ValueError("A captured raw query is immutable")
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("Parameter names and values must be explicit strings")
        self._pairs.append((key, value))
        return self

    def get(self):
        if self._raw is not None:
            raise ValueError("Use encode() to retain the original captured query")
        return list(self._pairs)

    def encode(self):
        return self._raw if self._raw is not None else urlencode(self._pairs)
