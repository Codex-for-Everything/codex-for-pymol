import json
import unittest

from codex_for_pymol.protocol import (
    JsonLineBuffer,
    RequestTracker,
    Utf8ChunkDecoder,
    diagnostic_fingerprint,
    diagnostic_summary,
    encode_message,
    error_message,
    error_will_retry,
    format_diagnostic,
    is_active_tool_call,
    is_current_notification,
    is_reconnect_notice,
    model_supports_input,
    notification_turn_id,
    validated_ephemeral_thread_id,
    strip_ansi,
)


class ProtocolTests(unittest.TestCase):
    def test_model_input_modality_uses_selected_or_default_catalog_entry(self):
        catalog = [
            {
                "model": "text-only",
                "isDefault": False,
                "inputModalities": ["text"],
            },
            {
                "model": "vision",
                "isDefault": True,
                "inputModalities": ["text", "image"],
            },
        ]
        self.assertTrue(model_supports_input(catalog, "", "image"))
        self.assertFalse(
            model_supports_input(catalog, "text-only", "image")
        )
        self.assertTrue(model_supports_input(catalog, "vision", "text"))

    def test_model_input_modality_is_unknown_without_explicit_metadata(self):
        self.assertIsNone(
            model_supports_input([{"model": "legacy", "isDefault": True}], "", "image")
        )
        self.assertIsNone(model_supports_input([], "missing", "image"))

    def test_ephemeral_thread_response_must_be_explicitly_confirmed(self):
        self.assertEqual(
            validated_ephemeral_thread_id(
                {"thread": {"id": "thread-1", "ephemeral": True}}
            ),
            "thread-1",
        )

    def test_persistent_or_ambiguous_thread_response_is_rejected(self):
        invalid_results = [
            None,
            [],
            {},
            {"thread": None},
            {"thread": []},
            {"thread": {}},
            {"thread": {"id": None, "ephemeral": True}},
            {"thread": {"id": 42, "ephemeral": True}},
            {"thread": {"id": "", "ephemeral": True}},
            {"thread": {"id": "thread-1"}},
            {"thread": {"id": "thread-1", "ephemeral": False}},
            {"thread": {"id": "thread-1", "ephemeral": 1}},
        ]
        for result in invalid_results:
            with self.subTest(result=result), self.assertRaises(ValueError):
                validated_ephemeral_thread_id(result)

    def test_partial_lines(self):
        buffer = JsonLineBuffer()
        self.assertEqual(buffer.feed('{"id":1'), [])
        self.assertEqual(buffer.feed(',"result":{}}\n'), [{"id": 1, "result": {}}])

    def test_multiple_lines(self):
        buffer = JsonLineBuffer()
        self.assertEqual(
            buffer.feed('{"id":1}\n\n{"method":"ready"}\n'),
            [{"id": 1}, {"method": "ready"}],
        )

    def test_invalid_line_does_not_drop_valid_messages(self):
        buffer = JsonLineBuffer()
        messages = buffer.feed('{"id":1}\nnot-json\n{"method":"ready"}\n')
        self.assertEqual(messages, [{"id": 1}, {"method": "ready"}])
        self.assertEqual(len(buffer.pop_errors()), 1)
        self.assertEqual(buffer.pop_errors(), [])

    def test_incomplete_message_has_a_size_limit(self):
        buffer = JsonLineBuffer(max_buffer=10)
        self.assertEqual(buffer.feed("x" * 11), [])
        self.assertEqual(len(buffer.pop_errors()), 1)
        self.assertEqual(buffer._buffer, "")

    def test_complete_message_has_a_size_limit(self):
        buffer = JsonLineBuffer(max_buffer=10)
        self.assertEqual(
            buffer.feed('{"value":"' + "x" * 20 + '"}\n'),
            [],
        )
        self.assertEqual(len(buffer.pop_errors()), 1)
        self.assertEqual(buffer._buffer, "")

    def test_request_tracker(self):
        seen = []
        tracker = RequestTracker()
        request_id = tracker.create(lambda result, error: seen.append((result, error)))
        self.assertTrue(tracker.resolve({"id": request_id, "result": {"ok": True}}))
        self.assertEqual(seen, [({"ok": True}, None)])
        self.assertFalse(tracker.resolve({"id": request_id, "result": {}}))

    def test_request_tracker_fails_all_pending_callbacks(self):
        seen = []
        tracker = RequestTracker()
        tracker.create(lambda result, error: seen.append((result, error)))
        tracker.create(lambda result, error: seen.append((result, error)))
        self.assertEqual(tracker.fail_all({"message": "stopped"}), 2)
        self.assertEqual(
            seen,
            [
                (None, {"message": "stopped"}),
                (None, {"message": "stopped"}),
            ],
        )

    def test_request_tracker_can_cancel_a_failed_write(self):
        tracker = RequestTracker()
        request_id = tracker.create(lambda _result, _error: None)
        self.assertTrue(tracker.cancel(request_id))
        self.assertFalse(tracker.cancel(request_id))

    def test_request_tracker_can_reject_a_timed_out_request(self):
        seen = []
        tracker = RequestTracker()
        request_id = tracker.create(lambda result, error: seen.append((result, error)))
        self.assertTrue(tracker.reject(request_id, {"message": "timeout"}))
        self.assertEqual(seen, [(None, {"message": "timeout"})])
        self.assertFalse(tracker.reject(request_id, {"message": "timeout"}))

    def test_request_tracker_can_clear_callbacks_during_shutdown(self):
        tracker = RequestTracker()
        tracker.create(lambda _result, _error: None)
        self.assertEqual(tracker.clear(), 1)
        self.assertEqual(tracker.clear(), 0)

    def test_encoding_is_jsonl(self):
        value = encode_message({"method": "测试"})
        self.assertTrue(value.endswith(b"\n"))
        self.assertEqual(json.loads(value.decode("utf-8")), {"method": "测试"})

    def test_utf8_decoder_preserves_a_character_split_across_chunks(self):
        encoded = '{"method":"测试"}\n'.encode("utf-8")
        split = encoded.index("测".encode("utf-8")) + 1
        decoder = Utf8ChunkDecoder()
        buffer = JsonLineBuffer()
        self.assertEqual(buffer.feed(decoder.decode(encoded[:split])), [])
        self.assertEqual(
            buffer.feed(decoder.decode(encoded[split:])),
            [{"method": "测试"}],
        )
        self.assertEqual(buffer.pop_errors(), [])

    def test_ansi_diagnostics_are_cleaned(self):
        value = "\x1b[2mcontext\x1b[0m \x1b[31mERROR\x1b[0m"
        self.assertEqual(strip_ansi(value), "context ERROR")

    def test_structured_diagnostics_show_only_the_message(self):
        value = json.dumps(
            {
                "level": "ERROR",
                "fields": {"message": "model refresh timed out"},
            }
        )
        self.assertEqual(
            format_diagnostic(value),
            "ERROR: model refresh timed out",
        )

    def test_diagnostic_fingerprint_ignores_timestamp_and_whitespace(self):
        first = (
            "2026-07-29T09:19:43.643664Z ERROR manager: "
            "failed to refresh available models"
        )
        second = (
            "2026-07-29T09:19:43.676386Z  ERROR manager:\n"
            "failed to refresh available models"
        )
        self.assertEqual(
            diagnostic_fingerprint(first),
            diagnostic_fingerprint(second),
        )

    def test_diagnostic_summary_hides_internal_log_details(self):
        value = (
            "2026-07-29T09:19:43.643664Z ERROR "
            "codex_models_manager::manager: failed to refresh available models: "
            "timeout waiting for child process to exit"
        )
        self.assertEqual(
            diagnostic_summary(value),
            "刷新可用模型列表超时（后台进程未按时退出）。",
        )

    def test_unknown_diagnostic_is_cleaned_and_bounded(self):
        value = "2026-07-29T09:19:43Z ERROR subsystem::worker: useful detail"
        self.assertEqual(diagnostic_summary(value), "useful detail")
        self.assertLessEqual(len(diagnostic_summary("ERROR " + "x" * 1000)), 500)

    def test_reconnect_notice_is_not_a_terminal_error(self):
        notice = {
            "message": "Reconnecting... 3/5",
            "codexErrorInfo": {
                "responseStreamDisconnected": {"httpStatusCode": None}
            },
            "additionalDetails": "request timed out",
        }
        self.assertTrue(is_reconnect_notice(notice))
        self.assertFalse(is_reconnect_notice({"message": "authentication failed"}))

    def test_rpc_error_is_presented_without_python_dict_syntax(self):
        self.assertEqual(
            error_message(
                {
                    "code": -32000,
                    "message": "authentication failed",
                    "internal": {"provider": "example"},
                }
            ),
            "authentication failed",
        )
        self.assertEqual(
            error_message({"error": {"message": "nested failure"}}),
            "nested failure",
        )

    def test_retry_state_uses_the_app_server_will_retry_field(self):
        self.assertTrue(error_will_retry({"willRetry": True}))
        self.assertFalse(error_will_retry({"willRetry": False}))
        self.assertFalse(error_will_retry({"error": {"message": "Reconnecting... 1/5"}}))

    def test_tool_call_requires_exact_active_identity(self):
        valid = {
            "callId": "call-1",
            "threadId": "thread-1",
            "turnId": "turn-1",
        }
        self.assertTrue(is_active_tool_call(valid, "thread-1", "turn-1"))
        for missing in ("callId", "threadId", "turnId"):
            invalid = dict(valid)
            invalid.pop(missing)
            self.assertFalse(is_active_tool_call(invalid, "thread-1", "turn-1"))
        self.assertFalse(is_active_tool_call(valid, "thread-2", "turn-1"))
        self.assertFalse(is_active_tool_call(valid, "thread-1", "turn-2"))

    def test_late_turn_notifications_are_rejected(self):
        current = {"threadId": "thread-1", "turnId": "turn-2"}
        old = {"threadId": "thread-1", "turnId": "turn-1"}

        self.assertTrue(
            is_current_notification(current, "thread-1", "turn-2", True)
        )
        self.assertFalse(
            is_current_notification(old, "thread-1", "turn-2", True)
        )
        self.assertFalse(
            is_current_notification(
                old,
                "thread-1",
                None,
                True,
                {"turn-1"},
            )
        )
        self.assertFalse(
            is_current_notification(current, "thread-1", None, False)
        )
        self.assertTrue(
            is_current_notification(current, "thread-1", None, True)
        )
        self.assertEqual(
            notification_turn_id({"turn": {"id": "nested-turn"}}),
            "nested-turn",
        )


if __name__ == "__main__":
    unittest.main()
