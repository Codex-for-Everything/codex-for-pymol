import importlib
import sys
import types
import unittest
from unittest import mock

from codex_for_pymol.discovery import ProcessInvocation


class _Signal:
    def __init__(self):
        self.values = []

    def emit(self, *values):
        self.values.append(values)


class _Timer:
    callbacks = []

    @classmethod
    def singleShot(cls, milliseconds, callback):
        cls.callbacks.append((milliseconds, callback))


def _load_app_server_without_pymol():
    try:
        return importlib.import_module("codex_for_pymol.app_server")
    except ModuleNotFoundError as exc:
        if exc.name not in {"pymol", "pymol.Qt"}:
            raise

    qt_core = types.SimpleNamespace(
        QObject=object,
        QProcess=types.SimpleNamespace(NotRunning=0, NormalExit=0),
        QTimer=_Timer,
        Signal=lambda *_args: _Signal(),
        pyqtSignal=lambda *_args: _Signal(),
    )
    pymol = types.ModuleType("pymol")
    pymol_qt = types.ModuleType("pymol.Qt")
    pymol_qt.QtCore = qt_core
    pymol.Qt = pymol_qt
    with mock.patch.dict(
        sys.modules,
        {"pymol": pymol, "pymol.Qt": pymol_qt},
    ):
        return importlib.import_module("codex_for_pymol.app_server")


app_server = _load_app_server_without_pymol()


def _client(generation=1):
    client = object.__new__(app_server.AppServerClient)
    client.runtime_directory = "/temporary/pymol-session"
    client.thread_id = None
    client.turn_id = None
    client._thread_generation = generation
    client._turn_active = False
    client._interrupt_pending = False
    client._finished_turn_ids = []
    client.status = _Signal()
    client.error = _Signal()
    client.ready = _Signal()
    client.requests = mock.Mock()
    client.send_request = mock.Mock(return_value=17)
    client._stop_unusable_process = mock.Mock()
    return client


class AppServerThreadTests(unittest.TestCase):
    def setUp(self):
        _Timer.callbacks.clear()

    def test_feature_probe_uses_shared_timeout(self):
        client = object.__new__(app_server.AppServerClient)
        client.executable = "/opt/codex"
        client.runtime_directory = "/temporary/pymol-session"
        client.process = mock.Mock()
        client.process.state.return_value = app_server.QtCore.QProcess.NotRunning
        client.feature_process = mock.Mock()
        client.feature_process.state.return_value = (
            app_server.QtCore.QProcess.NotRunning
        )
        client.status = _Signal()
        client._closing = True
        client._process_abort_pending = True
        client._feature_probe_active = False
        client._feature_probe_generation = 0

        with mock.patch.object(
            app_server,
            "feature_invocation",
            return_value=ProcessInvocation(
                "/opt/codex",
                ["features", "list"],
                {},
            ),
        ):
            client.start()

        client.feature_process.start.assert_called_once_with(
            "/opt/codex",
            ["features", "list"],
        )
        self.assertEqual(len(_Timer.callbacks), 1)
        self.assertEqual(
            _Timer.callbacks[0][0],
            app_server.FEATURE_DISCOVERY_TIMEOUT_SECONDS * 1000,
        )

    def test_feature_probe_failure_names_launcher_and_bounded_stderr(self):
        client = object.__new__(app_server.AppServerClient)
        client.executable = "C:\\Users\\Test\\AppData\\Roaming\\npm\\codex.cmd"
        client._closing = False
        client._feature_probe_active = True
        client._feature_probe_generation = 1
        client.feature_process = mock.Mock()
        client.feature_process.state.return_value = (
            app_server.QtCore.QProcess.NotRunning
        )
        client.feature_process.readAllStandardError.return_value = (
            b"npm launcher failed\n" + b"x" * 2000
        )
        client.error = _Signal()
        client.stopped = _Signal()

        client._feature_process_finished(
            1,
            app_server.QtCore.QProcess.NormalExit,
        )

        error = client.error.values[0][0]
        self.assertIn(client.executable, error)
        self.assertIn("npm launcher failed", error)
        self.assertLess(len(error), 1400)
        self.assertEqual(client.stopped.values, [()])

    def test_new_thread_requests_an_ephemeral_least_privilege_session(self):
        client = _client(generation=8)
        client.thread_id = "old-thread"
        client.turn_id = "old-turn"
        client._turn_active = True
        client._interrupt_pending = True
        client._finished_turn_ids = ["old-turn"]

        client.new_thread()

        method, params, callback = client.send_request.call_args.args
        self.assertEqual(method, "thread/start")
        self.assertEqual(params["cwd"], client.runtime_directory)
        self.assertEqual(params["sandbox"], "read-only")
        self.assertEqual(params["approvalPolicy"], "never")
        self.assertEqual(params["environments"], [])
        self.assertIs(params["ephemeral"], True)
        self.assertEqual(params["serviceName"], "codex_for_pymol")
        self.assertIsInstance(params["dynamicTools"], list)
        self.assertTrue(params["developerInstructions"])
        self.assertNotIn("threadId", params)
        self.assertEqual(client._thread_generation, 9)
        self.assertIsNone(client.thread_id)
        self.assertIsNone(client.turn_id)
        self.assertFalse(client._turn_active)
        self.assertFalse(client._interrupt_pending)
        self.assertEqual(client._finished_turn_ids, [])

        callback(
            {"thread": {"id": "thread-9", "ephemeral": True}},
            None,
        )
        self.assertEqual(client.thread_id, "thread-9")
        self.assertEqual(client.ready.values, [("thread-9",)])

    def test_explicitly_ephemeral_response_is_the_only_accepted_form(self):
        client = _client(generation=3)

        client._thread_started(
            {"thread": {"id": "safe-thread", "ephemeral": True}},
            None,
            3,
        )

        self.assertEqual(client.thread_id, "safe-thread")
        self.assertEqual(client.status.values[-1], ("就绪",))
        self.assertEqual(client.ready.values, [("safe-thread",)])
        client.send_request.assert_not_called()
        client._stop_unusable_process.assert_not_called()

    def test_persistent_response_is_deleted_before_current_session_stops(self):
        client = _client(generation=4)

        client._thread_started(
            {"thread": {"id": "persistent-thread", "ephemeral": False}},
            None,
            4,
        )

        method, params, callback = client.send_request.call_args.args
        self.assertEqual(method, "thread/delete")
        self.assertEqual(params, {"threadId": "persistent-thread"})
        self.assertIsNone(client.thread_id)
        self.assertEqual(client.ready.values, [])
        self.assertIn("不会保存到历史记录", client.error.values[0][0])
        client._stop_unusable_process.assert_not_called()
        self.assertEqual(len(_Timer.callbacks), 1)
        timeout_ms, timeout_callback = _Timer.callbacks[0]
        self.assertEqual(timeout_ms, 1000)
        timeout_callback()
        client.requests.reject.assert_called_once_with(
            17,
            {
                "code": -32001,
                "message": "等待 thread/delete 响应超时",
            },
        )

        callback({}, None)
        client._stop_unusable_process.assert_called_once_with()

    def test_cleanup_failure_names_the_record_and_manual_recovery(self):
        client = _client(generation=5)
        client._accept_thread(
            {"thread": {"id": "unexpected-thread", "ephemeral": False}},
            5,
        )
        callback = client.send_request.call_args.args[2]

        callback(None, {"message": "delete rejected"})

        self.assertIn("unexpected-thread", client.error.values[-1][0])
        self.assertIn("delete rejected", client.error.values[-1][0])
        self.assertIn("手动删除", client.error.values[-1][0])
        client._stop_unusable_process.assert_called_once_with()

    def test_cleanup_write_failure_is_reported_and_stops(self):
        client = _client(generation=6)
        client.send_request.side_effect = RuntimeError("pipe closed")

        client._accept_thread(
            {"thread": {"id": "unexpected-thread", "ephemeral": False}},
            6,
        )

        self.assertIn("pipe closed", client.error.values[-1][0])
        self.assertIn("手动删除", client.error.values[-1][0])
        client._stop_unusable_process.assert_called_once_with()

    def test_old_cleanup_callback_cannot_stop_a_newer_conversation(self):
        client = _client(generation=10)
        client._accept_thread(
            {"thread": {"id": "old-persistent", "ephemeral": False}},
            10,
        )
        callback = client.send_request.call_args.args[2]
        client._thread_generation = 11
        client.thread_id = "new-ephemeral"

        callback(None, {"message": "old cleanup failed"})

        client._stop_unusable_process.assert_not_called()
        self.assertEqual(client.thread_id, "new-ephemeral")
        self.assertIn("手动删除", client.error.values[-1][0])

    def test_stale_start_response_cannot_replace_current_thread(self):
        client = _client(generation=12)
        client.thread_id = "current-thread"

        client._thread_started(
            {"thread": {"id": "stale-thread", "ephemeral": True}},
            None,
            11,
        )

        self.assertEqual(client.thread_id, "current-thread")
        self.assertEqual(client.ready.values, [])
        client.send_request.assert_not_called()
        client._stop_unusable_process.assert_not_called()

    def test_malformed_response_fails_closed_without_deleting_unknown_data(self):
        invalid = [None, {}, {"thread": {}}, {"thread": {"ephemeral": True}}]
        for result in invalid:
            with self.subTest(result=result):
                client = _client(generation=13)
                client._thread_started(result, None, 13)
                self.assertIsNone(client.thread_id)
                self.assertEqual(client.ready.values, [])
                client.send_request.assert_not_called()
                client._stop_unusable_process.assert_called_once_with()

    def test_thread_start_error_stops_without_attempting_cleanup(self):
        client = _client(generation=14)

        client._thread_started(
            None,
            {"message": "unsupported parameter"},
            14,
        )

        self.assertIn("unsupported parameter", client.error.values[-1][0])
        client.send_request.assert_not_called()
        client._stop_unusable_process.assert_called_once_with()

    def test_turns_reuse_the_verified_thread(self):
        client = _client(generation=15)
        client.thread_id = "verified-thread"

        client.start_turn("show 1FPU", model="gpt-test", effort="high")

        method, params, callback = client.send_request.call_args.args
        self.assertEqual(method, "turn/start")
        self.assertEqual(params["threadId"], "verified-thread")
        self.assertEqual(params["input"], [{"type": "text", "text": "show 1FPU"}])
        self.assertEqual(params["model"], "gpt-test")
        self.assertEqual(params["effort"], "high")
        self.assertNotIn("serviceTier", params)
        self.assertTrue(client._turn_active)
        self.assertTrue(callable(callback))


if __name__ == "__main__":
    unittest.main()
