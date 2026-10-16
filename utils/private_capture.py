"""Value-bearing HTTP captures stay private; only fixed metadata is reportable."""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from utils.private_state import save_private

BODY_UNAVAILABLE = "<Response body not available anymore>"


class PrivateCapture:
    def __init__(self, session, directory, *, max_body_bytes=2 * 1024 * 1024):
        self.session = session
        self.directory = Path(directory)
        if self.directory.exists() or self.directory.is_symlink():
            raise ValueError("Use a new private capture directory")
        self.directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.mkdir(mode=0o700)
        self.max_body_bytes = max_body_bytes
        self.records = []
        self._hook = self._capture
        self._closed = False
        session.client.event_hooks["response"].append(self._hook)

    def _capture(self, response):
        request = response.request
        parts = urlsplit(str(request.url))
        if parts.scheme != "https" or parts.hostname != "www.zhipin.com":
            return
        response.read()
        available = len(response.content) <= self.max_body_bytes
        filename = f"request-{len(self.records) + 1:02d}.json"
        try:
            body = request.content.decode("utf-8")
        except UnicodeDecodeError:
            body = None
        save_private(self.directory / filename, {
            "provenance": "observed HTTP adapter, not browser or wire capture",
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "http_version": response.http_version,
            "networkRequest": {
                "url": str(request.url), "method": request.method,
                "requestHeaders": dict(request.headers),
                "requestBody": body, "status": str(response.status_code),
                "responseHeaders": dict(response.headers),
                "responseBody": response.text if available else BODY_UNAVAILABLE,
            },
            "requestHeaderPairs": list(request.headers.multi_items()),
            "responseHeaderPairs": list(response.headers.multi_items()),
            "body_retained": available,
        })
        self.records.append({
            "file": filename, "method": request.method, "path": parts.path,
            "status": response.status_code, "response_bytes": len(response.content),
            "body_retained": available,
        })

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.session.client.event_hooks["response"].remove(self._hook)
        save_private(self.directory / "index.json", {
            "provenance": "HTTP adapter; not browser capture",
            "captures": self.records,
        })

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
