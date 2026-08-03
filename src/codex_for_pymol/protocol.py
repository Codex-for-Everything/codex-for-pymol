"""Small JSON-RPC helpers independent from Qt and PyMOL."""

import codecs
import json
import re


ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ISO_8601_TIMESTAMP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\b"
)
DIAGNOSTIC_LEVEL = re.compile(r"^(?:trace|debug|info|warn|warning|error)\b\s*:?\s*", re.I)
RUST_LOG_TARGET = re.compile(
    r"^(?:[A-Za-z0-9_.-]+::)+[A-Za-z0-9_.-]+:\s*"
)


def strip_ansi(value):
    return ANSI_ESCAPE.sub("", value)


def format_diagnostic(value):
    formatted = []
    for line in strip_ansi(value).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            formatted.append(line)
            continue
        fields = record.get("fields") if isinstance(record, dict) else None
        message = fields.get("message") if isinstance(fields, dict) else None
        if message:
            level = str(record.get("level") or "diagnostic").upper()
            formatted.append("{}: {}".format(level, message))
        else:
            formatted.append(line)
    return "\n".join(formatted)


def diagnostic_fingerprint(value):
    """Normalize diagnostics for de-duplication without volatile timestamps."""
    text = ISO_8601_TIMESTAMP.sub("", strip_ansi(str(value)))
    return re.sub(r"\s+", " ", text).strip().lower()


def diagnostic_summary(value):
    """Convert a low-level stderr record into a compact user-facing summary."""
    text = ISO_8601_TIMESTAMP.sub("", strip_ansi(str(value)))
    text = re.sub(r"\s+", " ", text).strip()
    text = DIAGNOSTIC_LEVEL.sub("", text)
    text = RUST_LOG_TARGET.sub("", text).strip()
    normalized = text.lower().rstrip(".")
    if normalized == (
        "failed to refresh available models: "
        "timeout waiting for child process to exit"
    ):
        return "刷新可用模型列表超时（后台进程未按时退出）。"
    if normalized == "request timed out":
        return "请求超时。"
    if not text:
        return "Codex 后台进程报告了未提供详情的错误。"
    if len(text) > 500:
        text = text[:499].rstrip() + "…"
    return text


def is_reconnect_notice(value):
    if not isinstance(value, dict):
        return False
    info = value.get("codexErrorInfo")
    message = str(value.get("message") or "")
    return (
        isinstance(info, dict)
        and "responseStreamDisconnected" in info
        and message.lower().startswith("reconnecting")
    )


def error_will_retry(params):
    """Return whether an App Server error notification is explicitly retryable."""
    return isinstance(params, dict) and params.get("willRetry") is True


def error_message(value):
    """Extract a concise message from an App Server or JSON-RPC error."""
    if isinstance(value, dict):
        nested = value.get("error")
        if isinstance(nested, dict):
            value = nested
        message = value.get("message")
        if message:
            return str(message)
        code = value.get("code")
        if code is not None:
            return "错误代码 {}".format(code)
        return "Codex 返回了未提供详情的错误"
    text = str(value or "").strip()
    return text or "Codex 返回了未提供详情的错误"


def is_active_tool_call(params, active_thread, active_turn):
    """Validate the identity fields on a dynamic-tool request."""
    if not isinstance(params, dict):
        return False
    call_id = params.get("callId")
    thread_id = params.get("threadId")
    turn_id = params.get("turnId")
    return (
        isinstance(call_id, str)
        and bool(call_id.strip())
        and isinstance(thread_id, str)
        and bool(thread_id)
        and isinstance(turn_id, str)
        and bool(turn_id)
        and thread_id == active_thread
        and turn_id == active_turn
    )


def notification_turn_id(params):
    """Return a notification's top-level or nested turn identity."""
    if not isinstance(params, dict):
        return None
    turn_id = params.get("turnId")
    if turn_id:
        return turn_id
    turn = params.get("turn")
    return turn.get("id") if isinstance(turn, dict) else None


def is_current_notification(
    params,
    active_thread,
    active_turn,
    turn_active,
    finished_turns=(),
):
    """Reject notifications belonging to another or already finished turn."""
    if not isinstance(params, dict):
        return False
    thread_id = params.get("threadId")
    if thread_id and thread_id != active_thread:
        return False
    turn_id = notification_turn_id(params)
    if not turn_id:
        return True
    if turn_id in finished_turns:
        return False
    if active_turn:
        return turn_id == active_turn
    return bool(turn_active)


def validated_ephemeral_thread_id(result):
    """Return a verified ephemeral thread ID or raise ``ValueError``.

    Requesting ``ephemeral`` is not enough: an older or incompatible App
    Server could ignore an unknown request field.  The response is therefore
    part of the privacy boundary and must explicitly confirm the property.
    """
    if not isinstance(result, dict):
        raise ValueError("Codex 没有返回有效的对话结果")
    thread = result.get("thread")
    if not isinstance(thread, dict):
        raise ValueError("Codex 没有返回有效的对话信息")
    thread_id = thread.get("id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("Codex 没有返回有效的对话 ID")
    if thread.get("ephemeral") is not True:
        raise ValueError("当前 Codex 未确认该对话不会保存到历史记录")
    return thread_id


class Utf8ChunkDecoder:
    """Decode arbitrarily split process output without corrupting UTF-8."""

    def __init__(self):
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def decode(self, chunk, final=False):
        return self._decoder.decode(bytes(chunk), final=final)


class JsonLineBuffer:
    """Collect arbitrary text chunks and yield complete JSON objects."""

    def __init__(self, max_buffer=8 * 1024 * 1024):
        self._buffer = ""
        self._errors = []
        self.max_buffer = int(max_buffer)

    def feed(self, chunk):
        self._buffer += chunk
        messages = []
        lines = self._buffer.split("\n")
        self._buffer = lines.pop()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if len(line.encode("utf-8", "replace")) > self.max_buffer:
                self._errors.append(
                    "Protocol message exceeded {} bytes".format(
                        self.max_buffer
                    )
                )
                continue
            try:
                message = json.loads(line)
            except (TypeError, ValueError) as exc:
                self._errors.append(str(exc))
                continue
            if not isinstance(message, dict):
                self._errors.append("Protocol message must be a JSON object")
                continue
            messages.append(message)
        if len(self._buffer.encode("utf-8", "replace")) > self.max_buffer:
            self._errors.append(
                "Incomplete protocol message exceeded {} bytes".format(
                    self.max_buffer
                )
            )
            self._buffer = ""
        return messages

    def pop_errors(self):
        errors = self._errors
        self._errors = []
        return errors


class RequestTracker:
    """Allocate request ids and correlate JSON-RPC responses."""

    def __init__(self):
        self._next_id = 1
        self._callbacks = {}

    def create(self, callback=None):
        request_id = self._next_id
        self._next_id += 1
        if callback is not None:
            self._callbacks[request_id] = callback
        return request_id

    def resolve(self, message):
        request_id = message.get("id")
        callback = self._callbacks.pop(request_id, None)
        if callback is None:
            return False
        callback(message.get("result"), message.get("error"))
        return True

    def cancel(self, request_id):
        return self._callbacks.pop(request_id, None) is not None

    def reject(self, request_id, error):
        callback = self._callbacks.pop(request_id, None)
        if callback is None:
            return False
        callback(None, error)
        return True

    def clear(self):
        count = len(self._callbacks)
        self._callbacks.clear()
        return count

    def fail_all(self, error):
        request_ids = list(self._callbacks)
        failed = 0
        for request_id in request_ids:
            try:
                failed += int(self.reject(request_id, error))
            except Exception:
                pass
        return failed


def encode_message(message):
    """Encode one App Server wire message."""
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
