"""Local JSONL audit logging."""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .serializer import to_jsonable


SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|password|passwd|secret|token|api[_-]?key)",
    re.IGNORECASE,
)
SECRET_TEXT_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"""(?i)\b(api[_-]?key|token|password|secret)(\s*[:=]\s*)"""
        r"""(?:"[^"]*"|'[^']*'|[^\s,;}]+)"""
    ),
]


def _redact(value, key=None):
    if key is not None and SENSITIVE_KEY.search(str(key)):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        text = SECRET_TEXT_PATTERNS[0].sub("[REDACTED_API_KEY]", value)
        text = SECRET_TEXT_PATTERNS[1].sub("Bearer [REDACTED]", text)
        return SECRET_TEXT_PATTERNS[2].sub(r"\1\2[REDACTED]", text)
    return value


class AuditLogger:
    def __init__(
        self,
        directory,
        enabled=True,
        max_bytes=5 * 1024 * 1024,
        backups=3,
    ):
        self.enabled = enabled
        self.directory = Path(directory)
        self.path = self.directory / "audit.jsonl"
        self.max_bytes = max(1024, int(max_bytes))
        self.backups = max(0, int(backups))
        self.last_error = None

    def write(self, event, **fields):
        if not self.enabled:
            return True
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name != "nt":
                os.chmod(str(self.directory), 0o700)
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
            }
            record.update(_redact(to_jsonable(fields, max_string=50000)))
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            self._rotate_if_needed(len(line.encode("utf-8")))
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
            if os.name != "nt":
                os.chmod(str(self.path), 0o600)
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = "{}: {}".format(type(exc).__name__, exc)
            return False

    def _rotate_if_needed(self, incoming_bytes):
        if not self.path.exists():
            return
        if self.path.stat().st_size + incoming_bytes <= self.max_bytes:
            return
        if self.backups == 0:
            self.path.unlink()
            return

        oldest = self.directory / "audit.{}.jsonl".format(self.backups)
        if oldest.exists():
            oldest.unlink()
        for index in range(self.backups - 1, 0, -1):
            source = self.directory / "audit.{}.jsonl".format(index)
            if source.exists():
                source.replace(
                    self.directory / "audit.{}.jsonl".format(index + 1)
                )
        self.path.replace(self.directory / "audit.1.jsonl")
