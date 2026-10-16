"""Atomic private JSON writes. Never put credentials in public reports."""
import json
import os
from pathlib import Path
import tempfile


def save_private(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Refusing to replace a symlink")
    fd, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_private(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Refusing to load a symlink")
    return json.loads(path.read_text(encoding="utf-8"))
