"""Smoke-test localized widgets using PyMOL's bundled Qt runtime."""

import json
import os
from pathlib import Path
import stat
import sys

from pymol.Qt import QtCore, QtGui, QtWidgets

from codex_for_pymol import app_server as app_server_module
from codex_for_pymol import ui
from codex_for_pymol.discovery import ProcessInvocation
from codex_for_pymol.docking import create_codex_dock


class NullAuditLogger:
    last_error = None

    def __init__(self, _directory):
        pass

    def write(self, _event, **_fields):
        return True


class NullExecutor:
    def __init__(self, *_args, **_kwargs):
        pass


class RecordingExecutor:
    class Checkpoints:
        def __init__(self, directory):
            self.directory = Path(directory)
            self.paths = []
            self.create_calls = []
            self.undo_calls = 0

        def create(self, label):
            self.create_calls.append(label)
            path = self.directory / "ui-checkpoint-{}.pse".format(
                len(self.create_calls)
            )
            path.write_bytes(b"checkpoint")
            self.paths.append(path)
            return str(path)

        def has_checkpoint(self):
            return bool(self.paths)

        def undo_last(self):
            self.undo_calls += 1
            path = self.paths.pop()
            path.unlink()
            return str(path)

    def __init__(self, directory):
        self.inspect_calls = []
        self.apply_calls = []
        self.scene_revision = 0
        self.checkpoints = self.Checkpoints(directory)

    def inspect(self, arguments):
        self.inspect_calls.append(arguments)
        return {"ok": True}

    def apply(self, arguments, before_execute=None):
        if before_execute is not None:
            before_execute()
        self.apply_calls.append(arguments)
        self.scene_revision += 1
        return {
            "ok": True,
            "completed": ["show"],
            "scene_revision": self.scene_revision,
        }


class FakeClient:
    def __init__(self, thread_id=None, turn_id=None):
        self.thread_id = thread_id
        self.turn_id = turn_id
        self.sent = []
        self.python_modes = []
        self.turn_settings = []
        self.responses = []
        self.interrupt_count = 0
        self.events = []

    def start_turn(
        self,
        text,
        unrestricted_python_enabled=False,
        model="",
        effort="",
        service_tier="",
    ):
        self.sent.append(text)
        self.python_modes.append(bool(unrestricted_python_enabled))
        self.turn_settings.append((model, effort, service_tier))

    def refresh_models(self):
        pass

    def respond(self, request_id, response):
        self.responses.append((request_id, response))
        self.events.append(("respond", request_id))

    def interrupt(self):
        self.interrupt_count += 1
        self.events.append(("interrupt", self.turn_id))
        return bool(self.thread_id)

    def close(self):
        pass


class TestCodexDialog(ui.CodexDialog):
    def _connect_codex(self):
        pass


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def require_button_palette(widget, expected_palette, context):
    buttons = widget.findChildren(QtWidgets.QPushButton)
    require(buttons, "{} has no buttons to verify".format(context))
    for button in buttons:
        for group in (
            QtGui.QPalette.Active,
            QtGui.QPalette.Inactive,
            QtGui.QPalette.Disabled,
        ):
            for role in (
                QtGui.QPalette.Button,
                QtGui.QPalette.ButtonText,
            ):
                require(
                    button.palette().brush(group, role)
                    == expected_palette.brush(group, role),
                    "{} button {!r} colors do not match the platform theme policy "
                    "(group={}, role={}, actual={}, expected={})".format(
                        context,
                        button.text(),
                        int(group),
                        int(role),
                        button.palette().color(group, role).name(),
                        expected_palette.color(group, role).name(),
                    ),
                )


def require_combo_palette(widget, expected_palette, context):
    combos = widget.findChildren(QtWidgets.QComboBox)
    require(combos, "{} has no combo boxes to verify".format(context))
    for combo in combos:
        for group in (
            QtGui.QPalette.Active,
            QtGui.QPalette.Inactive,
            QtGui.QPalette.Disabled,
        ):
            for role in (
                QtGui.QPalette.Base,
                QtGui.QPalette.Text,
                QtGui.QPalette.Button,
                QtGui.QPalette.ButtonText,
                QtGui.QPalette.Highlight,
                QtGui.QPalette.HighlightedText,
            ):
                require(
                    combo.palette().brush(group, role)
                    == expected_palette.brush(group, role),
                    "{} combo colors do not match the native control palette "
                    "(group={}, role={}, actual={}, expected={})".format(
                        context,
                        int(group),
                        int(role),
                        combo.palette().color(group, role).name(),
                        expected_palette.color(group, role).name(),
                    ),
                )


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    ui.AuditLogger = NullAuditLogger
    ui.PyMOLExecutor = NullExecutor

    dialog = TestCodexDialog()
    dialog.settings = QtCore.QSettings(
        str(dialog.runtime_directory / "pymol-ui-smoke-settings.ini"),
        QtCore.QSettings.IniFormat,
    )
    dialog.settings.clear()
    dialog.preferences = ui.PreferenceStore(dialog.settings, "zh_CN")
    dialog.preferences.set_language(ui.ZH_CN)
    ui.set_locale(ui.ZH_CN)
    dialog._retranslate_ui()
    require(dialog.windowTitle() == "PyMOL Codex 助手", "window title is not localized")
    require(dialog.status_label.text() == "尚未连接", "status is not localized")
    require(dialog.choose_button.text() == "选择 Codex…", "chooser is not localized")
    dialog._set_codex_selector_visible(False)
    require(dialog.choose_button.isHidden(), "chooser remains visible when Codex is found")
    dialog._set_codex_selector_visible(True, retry=True)
    require(not dialog.choose_button.isHidden(), "chooser is unavailable after a failure")
    require(
        dialog.choose_button.text() == "重新选择 Codex…",
        "retry chooser is not localized",
    )
    require(dialog.send_button.text() == "发送", "send button is not localized")
    require(dialog.stop_button.text() == "停止", "stop button is not localized")
    require(dialog.new_button.text() == "新建对话", "new button is not localized")
    require(
        dialog.model_settings_button.text() == "设置…",
        "settings button is not localized",
    )
    require(
        dialog.undo_button.text() == "撤销最新一轮的修改",
        "instruction undo button is not localized",
    )
    require(
        not dialog.undo_button.isEnabled(),
        "instruction undo is enabled without a checkpoint",
    )
    require(
        dialog.python_checkbox.text() == "启用不受限 Python（高风险）",
        "Python warning is not localized",
    )
    dialog._model_catalog_failed(
        ui.tr("backend.model_failed"),
        "backend.model_failed",
    )
    dialog.preferences.set_language(ui.EN)
    ui.set_locale(ui.EN)
    dialog._retranslate_ui()
    require(
        dialog.windowTitle() == "Codex for PyMOL"
        and dialog.status_label.text() == "Not connected"
        and dialog.choose_button.text() == "Choose another Codex…"
        and dialog.send_button.text() == "Send"
        and dialog.model_settings_button.text() == "Settings…"
        and dialog.python_checkbox.text()
        == "Enable unrestricted Python (high risk)",
        "switching to English did not retranslate persistent controls",
    )
    require(
        dialog._model_catalog_error
        == ui.tr("backend.model_failed"),
        "switching languages left a stale localized model-list error",
    )
    dialog.preferences.set_language(ui.ZH_CN)
    ui.set_locale(ui.ZH_CN)
    dialog._retranslate_ui()
    python_warning = []
    original_confirm = dialog._confirm
    dialog._confirm = (
        lambda title, text, accept_text="确认": python_warning.append(
            (title, text, accept_text)
        )
        and False
    )
    dialog._toggle_python(True)
    dialog._confirm = original_confirm
    require(
        python_warning
        and "切换离开 Codex 标签" in python_warning[-1][1]
        and "Codex 插件面板" in python_warning[-1][1]
        and "退出 PyMOL" in python_warning[-1][1],
        "unrestricted-Python warning does not name the exact auto-lock triggers",
    )
    dialog.show()
    app.processEvents(QtCore.QEventLoop.AllEvents)
    dialog.full_python_enabled = True
    dialog.python_checkbox.blockSignals(True)
    dialog.python_checkbox.setChecked(True)
    dialog.python_checkbox.blockSignals(False)
    dialog.input.setFocus()
    escape = QtGui.QKeyEvent(
        QtCore.QEvent.KeyPress,
        QtCore.Qt.Key_Escape,
        QtCore.Qt.NoModifier,
    )
    QtWidgets.QApplication.sendEvent(dialog.input, escape)
    app.processEvents(QtCore.QEventLoop.AllEvents)
    require(
        dialog.isVisible() and dialog.full_python_enabled,
        "Escape hid the main plugin panel or disabled unrestricted Python",
    )
    dialog.full_python_enabled = True
    dialog.hide()
    app.processEvents(QtCore.QEventLoop.AllEvents)
    require(
        not dialog.full_python_enabled,
        "hiding a standalone fallback panel did not lock unrestricted Python",
    )
    dialog.show()
    app.processEvents(QtCore.QEventLoop.AllEvents)
    require(
        dialog.runtime_directory.name.startswith(
            "codex-for-pymol-runtime-"
        ),
        "runtime directory is not uniquely allocated",
    )
    if os.name != "nt":
        require(
            stat.S_IMODE(dialog.runtime_directory.stat().st_mode)
            == 0o700,
            "runtime directory is not private",
        )
    else:
        launcher_directory = dialog.runtime_directory / "Codex & Tools (100%)"
        launcher_directory.mkdir()
        launcher = launcher_directory / "codex.cmd"
        launcher.write_text(
            "@echo off\n"
            "if /I not \"%~1\"==\"features\" exit /b 7\n"
            "if /I not \"%~2\"==\"list\" exit /b 8\n"
            "echo shell_tool stable true\n",
            encoding="utf-8",
        )
        invocation = app_server_module.feature_invocation(
            str(launcher)
        )
        launcher_process = QtCore.QProcess(dialog)
        app_server_module._start_process(launcher_process, invocation)
        require(
            launcher_process.waitForFinished(5000)
            and launcher_process.exitCode() == 0
            and b"shell_tool stable true"
            in bytes(launcher_process.readAllStandardOutput()),
            "PyMOL QProcess could not run a Windows Codex launcher with spaces",
        )

    protocol_client = ui.AppServerClient(
        "codex",
        dialog.runtime_directory,
        dialog,
    )
    original_feature_invocation = app_server_module.feature_invocation
    feature_probe_errors = []
    feature_probe_stops = []
    failed_probe_client = ui.AppServerClient(
        "missing-codex",
        dialog.runtime_directory,
        dialog,
    )
    failed_probe_client.error.connect(feature_probe_errors.append)
    failed_probe_client.stopped.connect(
        lambda: feature_probe_stops.append(True)
    )
    try:
        app_server_module.feature_invocation = lambda _executable: (
            ProcessInvocation(
                str(dialog.runtime_directory / "missing-codex-executable"),
                [],
                {},
            )
        )
        failed_probe_client.start()
        probe_wait = QtCore.QEventLoop()
        failed_probe_client.stopped.connect(probe_wait.quit)
        QtCore.QTimer.singleShot(2000, probe_wait.quit)
        probe_wait.exec_()
    finally:
        app_server_module.feature_invocation = original_feature_invocation
        failed_probe_client.close()
    require(
        feature_probe_errors
        and feature_probe_stops
        and "已停止启动" in feature_probe_errors[-1],
        "feature discovery failure did not stop App Server startup safely",
    )

    successful_probe_client = ui.AppServerClient(
        "fake-codex",
        dialog.runtime_directory,
        dialog,
    )
    captured_features = []
    original_process_invocation = app_server_module.process_invocation
    try:
        app_server_module.feature_invocation = lambda _executable: (
            ProcessInvocation(
                sys.executable,
                ["-c", "print('shell_tool stable true')"],
                {},
            )
        )

        def fake_app_server_invocation(_executable, available_features):
            captured_features.append(set(available_features))
            return ProcessInvocation(
                sys.executable,
                ["-c", "import time; time.sleep(5)"],
                {},
            )

        app_server_module.process_invocation = fake_app_server_invocation
        successful_probe_client.start()
        successful_probe_wait = QtCore.QEventLoop()
        successful_probe_client.process.started.connect(
            successful_probe_wait.quit
        )
        QtCore.QTimer.singleShot(2000, successful_probe_wait.quit)
        successful_probe_wait.exec_()
    finally:
        app_server_module.feature_invocation = original_feature_invocation
        app_server_module.process_invocation = original_process_invocation
        successful_probe_client.close()
    require(
        captured_features == [{"shell_tool"}],
        "asynchronous feature discovery did not feed the live catalog "
        "into App Server argument generation",
    )

    startup_failure_client = ui.AppServerClient(
        "fake-codex",
        dialog.runtime_directory,
        dialog,
    )
    startup_errors = []
    startup_stops = []
    startup_failure_client.error.connect(startup_errors.append)
    startup_failure_client.stopped.connect(
        lambda: startup_stops.append(True)
    )
    startup_failure_client.process.setWorkingDirectory(
        str(dialog.runtime_directory)
    )
    startup_failure_client.process.start(
        sys.executable,
        ["-c", "import time; time.sleep(5)"],
    )
    require(
        startup_failure_client.process.waitForStarted(2000),
        "startup-failure test process did not start",
    )
    # The real initialize response has already consumed its callback before
    # _initialized runs. Mirror that state without needing a fake JSON-RPC
    # server for this lifecycle check.
    startup_failure_client.requests.clear()
    startup_failure_client._initialized(
        None,
        {"message": "initialize rejected"},
    )
    startup_stop_wait = QtCore.QEventLoop()
    startup_failure_client.stopped.connect(startup_stop_wait.quit)
    QtCore.QTimer.singleShot(2500, startup_stop_wait.quit)
    startup_stop_wait.exec_()
    require(
        startup_errors == ["Codex 初始化失败：initialize rejected"]
        and startup_stops == [True]
        and startup_failure_client.process.state()
        == QtCore.QProcess.NotRunning,
        "an initialization failure left an App Server process running: "
        "errors={!r}, stops={!r}, state={!r}".format(
            startup_errors,
            startup_stops,
            startup_failure_client.process.state(),
        ),
    )
    startup_failure_client.close()

    protocol_client.thread_id = "stale-thread"
    split_diagnostics = []
    protocol_client.diagnostic.connect(split_diagnostics.append)
    protocol_client._consume_stderr(
        "2026-07-29T09:19:43Z ERROR codex_models_manager::manager: "
        "failed to refresh available "
    )
    require(
        not split_diagnostics,
        "an incomplete stderr line was exposed as a diagnostic",
    )
    protocol_client._consume_stderr(
        "models: timeout waiting for child process to exit\n"
    )
    require(
        split_diagnostics
        and split_diagnostics[-1].endswith(
            "timeout waiting for child process to exit"
        ),
        "a split stderr diagnostic was not reconstructed",
    )
    protocol_client._process_finished(1, QtCore.QProcess.NormalExit)
    require(
        protocol_client.thread_id is None,
        "a stopped App Server retained a stale conversation identity",
    )
    terminal_turn_failures = []
    protocol_client.turn_failed.connect(
        terminal_turn_failures.append
    )
    protocol_client._handle(
        {
            "method": "error",
            "params": {
                "error": {
                    "code": -32000,
                    "message": "startup failed cleanly",
                    "internal": {"provider": "hidden"},
                },
                "willRetry": False,
            },
        }
    )
    require(
        not terminal_turn_failures,
        "a startup error was incorrectly reported as a failed user turn",
    )
    protocol_client.thread_id = "context-thread"
    protocol_client.turn_id = "turn-error"
    protocol_client._turn_active = True
    protocol_client._handle(
        {
            "method": "error",
            "params": {
                "error": {
                    "code": -32000,
                    "message": "turn failed cleanly",
                    "internal": {"provider": "hidden"},
                },
                "willRetry": False,
            },
        }
    )
    require(
        terminal_turn_failures == [
            "Codex 错误：turn failed cleanly"
        ],
        "a terminal turn error was not classified or formatted cleanly",
    )
    protocol_client.thread_id = "context-thread"
    turn_requests = []
    protocol_client.send_request = (
        lambda method, params=None, callback=None: turn_requests.append(
            (method, params, callback)
        )
    )
    protocol_client.send_notification = lambda method, params=None: None
    protocol_client._initialized({}, None)
    require(
        any(entry[0] == "thread/start" for entry in turn_requests)
        and not any(entry[0] == "thread/resume" for entry in turn_requests),
        "a new PyMOL launch still resumes a previous Codex conversation",
    )
    thread_start = next(
        entry[1] for entry in turn_requests if entry[0] == "thread/start"
    )
    require(
        thread_start["approvalPolicy"] == "never"
        and thread_start["sandbox"] == "read-only"
        and thread_start["environments"] == []
        and thread_start["ephemeral"] is True,
        "thread/start does not enforce the ephemeral least-privilege policy",
    )

    validation_client = ui.AppServerClient(
        "codex",
        dialog.runtime_directory,
        dialog,
    )
    validated_threads = []
    validation_errors = []
    validation_stops = []
    cleanup_requests = []
    validation_client.ready.connect(validated_threads.append)
    validation_client.error.connect(validation_errors.append)
    validation_client._stop_unusable_process = (
        lambda: validation_stops.append(True)
    )

    def capture_cleanup(method, params=None, callback=None):
        cleanup_requests.append((method, params, callback))
        return 9001

    validation_client.send_request = capture_cleanup
    validation_client._accept_thread(
        {"thread": {"id": "ephemeral-thread", "ephemeral": True}}
    )
    require(
        validated_threads == ["ephemeral-thread"]
        and validation_client.thread_id == "ephemeral-thread"
        and not validation_errors
        and not cleanup_requests,
        "an explicitly ephemeral thread response was not accepted",
    )
    validation_client._accept_thread(
        {"thread": {"id": "persistent-thread", "ephemeral": False}}
    )
    require(
        validation_client.thread_id is None
        and validated_threads == ["ephemeral-thread"]
        and validation_errors
        and "不会保存到历史记录" in validation_errors[-1]
        and cleanup_requests[-1][0] == "thread/delete"
        and cleanup_requests[-1][1]
        == {"threadId": "persistent-thread"}
        and not validation_stops,
        "a persistent thread response was accepted or not cleaned up",
    )
    cleanup_requests[-1][2](None, {"message": "cleanup unsupported"})
    require(
        validation_stops == [True],
        "a rejected thread cleanup failure did not stop the session",
    )
    validation_stops.clear()
    cleanup_count = len(cleanup_requests)
    validation_client._accept_thread({"thread": {"ephemeral": True}})
    require(
        validation_stops == [True]
        and len(cleanup_requests) == cleanup_count
        and validated_threads == ["ephemeral-thread"],
        "a malformed thread response remained usable",
    )
    validation_client.close()

    turn_requests.clear()
    protocol_client.thread_id = "context-thread"
    catalog_seen = []
    catalog_errors = []
    protocol_client.model_catalog.connect(
        lambda catalog: catalog_seen.append(catalog)
    )
    protocol_client.model_catalog_error.connect(
        lambda message: catalog_errors.append(message)
    )
    protocol_client.start_turn("disabled", False)
    protocol_client.start_turn(
        "enabled",
        True,
        "gpt-test",
        "high",
        "priority",
    )
    turn_entries = [
        entry for entry in turn_requests if entry[0] == "turn/start"
    ]
    disabled_context = turn_entries[0][1]["additionalContext"][
        "codex_for_pymol_python_mode"
    ]
    enabled_context = turn_entries[1][1]["additionalContext"][
        "codex_for_pymol_python_mode"
    ]
    require(
        turn_entries[0][0] == "turn/start"
        and disabled_context["kind"] == "application"
        and "DISABLED" in disabled_context["value"]
        and "ENABLED" in enabled_context["value"],
        "turn/start does not carry the live unrestricted-Python state",
    )
    require(
        "model" not in turn_entries[0][1]
        and "effort" not in turn_entries[0][1]
        and "serviceTier" not in turn_entries[0][1],
        "default turn/start sends version-specific null overrides",
    )
    require(
        turn_entries[1][1]["model"] == "gpt-test"
        and turn_entries[1][1]["effort"] == "high"
        and turn_entries[1][1]["serviceTier"] == "priority",
        "turn/start does not carry model, effort, and service-tier settings",
    )
    require(
        not any(entry[0] == "thread/start" for entry in turn_requests),
        "messages in one PyMOL conversation created separate Codex threads",
    )

    turn_requests.clear()
    protocol_client.thread_id = "old-thread"
    protocol_client.turn_id = "old-turn"
    protocol_client._turn_active = True
    protocol_client.new_thread()
    first_new_thread = turn_requests[-1]
    protocol_client.new_thread()
    second_new_thread = turn_requests[-1]
    first_new_thread[2](
        {"thread": {"id": "stale-new-thread", "ephemeral": True}},
        None,
    )
    require(
        protocol_client.thread_id is None,
        "a stale thread/start response replaced the newer conversation",
    )
    second_new_thread[2](
        {"thread": {"id": "fresh-new-thread", "ephemeral": True}},
        None,
    )
    require(
        protocol_client.thread_id == "fresh-new-thread"
        and protocol_client.turn_id is None
        and not protocol_client._turn_active
        and sum(entry[0] == "thread/start" for entry in turn_requests) == 2,
        "new-conversation generation isolation is incorrect",
    )

    ambiguous_turn_aborts = []
    protocol_client._stop_unusable_process = (
        lambda: ambiguous_turn_aborts.append(True)
    )
    protocol_client._turn_active = True
    protocol_client._turn_accepted(
        None,
        {"code": -32001, "message": "waiting for turn/start timed out"},
    )
    require(
        ambiguous_turn_aborts == [True]
        and not protocol_client._turn_active,
        "an ambiguous turn/start timeout left the App Server session reusable",
    )

    first_model = {
        "id": "gpt-test",
        "model": "gpt-test",
        "displayName": "GPT Test",
        "description": "测试模型",
        "hidden": False,
        "isDefault": True,
        "defaultReasoningEffort": "medium",
        "supportedReasoningEfforts": [
            {
                "reasoningEffort": "medium",
                "description": "平衡",
            },
            {
                "reasoningEffort": "high",
                "description": "更深入",
            },
        ],
        "defaultServiceTier": "standard",
        "serviceTiers": [
            {
                "id": "standard",
                "name": "标准",
                "description": "标准速度",
            },
            {
                "id": "priority",
                "name": "快速",
                "description": "更快响应",
            },
        ],
    }
    second_model = {
        "id": "gpt-other",
        "model": "gpt-other",
        "displayName": "GPT Other",
        "description": "另一个模型",
        "hidden": False,
        "isDefault": False,
        "defaultReasoningEffort": "low",
        "supportedReasoningEfforts": [
            {
                "reasoningEffort": "low",
                "description": "较快",
            }
        ],
        "serviceTiers": [],
    }
    implicit_default_model = dict(first_model)
    implicit_default_model["defaultServiceTier"] = None
    implicit_default_model["serviceTiers"] = [
        {
            "id": "priority",
            "name": "Fast",
            "description": "1.5x speed, increased usage",
        }
    ]
    protocol_client.refresh_models()
    model_entries = [
        entry for entry in turn_requests if entry[0] == "model/list"
    ]
    require(
        model_entries[0][1]
        == {"limit": 100, "includeHidden": False},
        "model catalog request has unexpected parameters",
    )
    model_entries[0][2](
        {"data": [first_model], "nextCursor": "page-2"},
        None,
    )
    model_entries = [
        entry for entry in turn_requests if entry[0] == "model/list"
    ]
    require(
        model_entries[1][1]["cursor"] == "page-2",
        "model catalog pagination cursor was not followed",
    )
    model_entries[1][2](
        {"data": [second_model], "nextCursor": None},
        None,
    )
    require(
        catalog_seen
        and [item["model"] for item in catalog_seen[-1]]
        == ["gpt-test", "gpt-other"],
        "paginated model catalog was not emitted",
    )
    protocol_client.refresh_models()
    latest_model_request = [
        entry for entry in turn_requests if entry[0] == "model/list"
    ][-1]
    latest_model_request[2](
        None,
        {"message": "raw provider details must stay hidden"},
    )
    require(
        catalog_errors
        and "可以继续使用 Codex 默认设置" in catalog_errors[-1]
        and "provider" not in catalog_errors[-1],
        "model catalog failures are not converted to a friendly fallback",
    )

    class TrackingModelSettingsDialog(ui.ModelSettingsDialog):
        def __init__(self, *args, **kwargs):
            self.update_transitions = []
            super().__init__(*args, **kwargs)

        def setUpdatesEnabled(self, enabled):
            self.update_transitions.append(bool(enabled))
            super().setUpdatesEnabled(enabled)

    model_dialog = TrackingModelSettingsDialog(
        catalog_seen[-1],
        "gpt-test",
        "high",
        "priority",
        parent=dialog,
    )
    require(
        model_dialog.current_settings()
        == ("gpt-test", "high", "priority"),
        "saved model settings were not restored in the picker",
    )
    require(
        model_dialog.effort_combo.findData("medium") >= 0
        and model_dialog.effort_combo.findData("high") >= 0
        and model_dialog.service_tier_combo.findData("priority") >= 0,
        "model-specific effort or speed options were not populated",
    )
    model_dialog.show()
    app.processEvents(QtCore.QEventLoop.AllEvents)
    initial_dialog_size = model_dialog.size()
    initial_refresh_width = model_dialog.refresh_button.width()
    initial_first_item = model_dialog.model_combo.model().item(0)
    model_dialog.update_transitions.clear()
    model_dialog._request_refresh()
    app.processEvents(QtCore.QEventLoop.AllEvents)
    require(
        not model_dialog.refresh_button.isEnabled()
        and model_dialog.refresh_button.text() == "正在刷新…"
        and model_dialog.details_label.isHidden()
        and model_dialog.size() == initial_dialog_size
        and model_dialog.refresh_button.width() == initial_refresh_width,
        "starting a model refresh changed the dialog layout",
    )
    equivalent_catalog = json.loads(
        json.dumps(catalog_seen[-1], ensure_ascii=False)
    )
    model_dialog.set_catalog(equivalent_catalog)
    app.processEvents(QtCore.QEventLoop.AllEvents)
    require(
        model_dialog.refresh_button.isEnabled()
        and model_dialog.refresh_button.text() == "刷新模型列表"
        and model_dialog.model_combo.model().item(0)
        is initial_first_item
        and model_dialog.size() == initial_dialog_size,
        "an unchanged model refresh rebuilt controls or resized the dialog",
    )
    require(
        model_dialog.update_transitions == [],
        "an unchanged model refresh still suspended whole-dialog painting",
    )
    default_model_dialog = ui.ModelSettingsDialog(
        catalog_seen[-1],
        parent=dialog,
    )
    require(
        default_model_dialog.model_combo.currentData() == "gpt-test"
        and "默认" in default_model_dialog.model_combo.currentText()
        and default_model_dialog.effort_combo.currentData() == "medium"
        and "默认" in default_model_dialog.effort_combo.currentText()
        and default_model_dialog.service_tier_combo.currentData()
        == "standard"
        and "默认"
        in default_model_dialog.service_tier_combo.currentText(),
        "real default options are not selected and marked",
    )
    implicit_tier_dialog = ui.ModelSettingsDialog(
        [implicit_default_model],
        parent=dialog,
    )
    require(
        implicit_tier_dialog.service_tier_combo.count() == 2
        and implicit_tier_dialog.service_tier_combo.itemData(0) == ""
        and implicit_tier_dialog.service_tier_combo.itemText(0)
        == "标准（默认）"
        and implicit_tier_dialog.service_tier_combo.itemData(1)
        == "priority"
        and implicit_tier_dialog.service_tier_combo.itemText(1)
        == "Fast"
        and implicit_tier_dialog.service_tier_combo.currentData() == ""
        and implicit_tier_dialog.service_tier_combo.isEnabled(),
        "an implicit standard service tier was not exposed alongside Fast",
    )
    implicit_tier_dialog.service_tier_combo.setCurrentIndex(1)
    require(
        implicit_tier_dialog.current_settings()[2] == "priority",
        "the explicit Fast service tier cannot be selected",
    )
    implicit_tier_dialog.deleteLater()
    dialog._model_catalog = [implicit_default_model]
    dialog._save_model_settings("gpt-test", "medium", "")
    require(
        "响应速度：标准（默认）"
        in dialog.model_settings_button.toolTip(),
        "the implicit standard tier is mislabeled in the settings tooltip",
    )
    require(
        default_model_dialog.details_label.isHidden()
        and all(
            default_model_dialog.model_combo.itemData(
                index,
                QtCore.Qt.ToolTipRole,
            )
            is None
            for index in range(default_model_dialog.model_combo.count())
        ),
        "dynamic model description remains visible in the settings dialog",
    )
    require(
        all(
            combo.findData("") < 0
            for combo in (
                default_model_dialog.model_combo,
                default_model_dialog.effort_combo,
                default_model_dialog.service_tier_combo,
            )
        )
        and all(
            "自动" not in combo.itemText(index)
            and "模型默认" not in combo.itemText(index)
            for combo in (
                default_model_dialog.model_combo,
                default_model_dialog.effort_combo,
                default_model_dialog.service_tier_combo,
            )
            for index in range(combo.count())
        ),
        "model settings still contain synthetic automatic/default options",
    )
    other_index = default_model_dialog.model_combo.findData("gpt-other")
    default_model_dialog.model_combo.setCurrentIndex(other_index)
    require(
        default_model_dialog.effort_combo.currentData() == "low"
        and default_model_dialog.effort_combo.count() == 1
        and default_model_dialog.service_tier_combo.count() == 1
        and default_model_dialog.service_tier_combo.currentData() == ""
        and default_model_dialog.service_tier_combo.currentText()
        == "标准（默认）"
        and not default_model_dialog.service_tier_combo.isEnabled(),
        "a model without additional tiers does not expose its standard default",
    )
    default_model_dialog.deleteLater()
    failed_model_dialog = ui.ModelSettingsDialog(
        [],
        model="gpt-saved",
        effort="high",
        service_tier="priority",
        catalog_error="无法获取模型列表。",
        parent=dialog,
    )
    require(
        not failed_model_dialog.details_label.isHidden()
        and failed_model_dialog.details_label.text()
        == "无法获取模型列表。",
        "catalog errors were hidden together with the model description",
    )
    require(
        failed_model_dialog.current_settings()
        == ("gpt-saved", "high", "priority"),
        "an unavailable model catalog erased saved settings",
    )
    failed_model_dialog.deleteLater()
    dialog._save_model_settings("gpt-test", "high", "priority")
    require(
        dialog._saved_model_settings()
        == ("gpt-test", "high", "priority"),
        "model settings were not persisted",
    )
    dialog._model_catalog_validated = False
    require(
        dialog._effective_model_settings() == ("", "", ""),
        "unvalidated settings from a previous Codex session remain active",
    )
    dialog._set_model_catalog([first_model, second_model])
    require(
        dialog._effective_model_settings()
        == ("gpt-test", "high", "priority"),
        "live-catalog-validated model settings are not active",
    )

    send_requests = []
    dialog.input.send_requested.connect(lambda: send_requests.append(True))
    enter = QtGui.QKeyEvent(
        QtCore.QEvent.KeyPress,
        QtCore.Qt.Key_Return,
        QtCore.Qt.NoModifier,
    )
    dialog.input.keyPressEvent(enter)
    require(len(send_requests) == 1, "Enter did not request message sending")
    shift_enter = QtGui.QKeyEvent(
        QtCore.QEvent.KeyPress,
        QtCore.Qt.Key_Return,
        QtCore.Qt.ShiftModifier,
    )
    dialog.input.keyPressEvent(shift_enter)
    require(len(send_requests) == 1, "Shift+Enter incorrectly requested sending")
    require(dialog.input.toPlainText() == "\n", "Shift+Enter did not insert a line break")
    control_enter = QtGui.QKeyEvent(
        QtCore.QEvent.KeyPress,
        QtCore.Qt.Key_Return,
        QtCore.Qt.ControlModifier,
    )
    dialog.input.keyPressEvent(control_enter)
    require(len(send_requests) == 1, "Ctrl+Enter incorrectly requested sending")
    require(
        dialog.input.toPlainText() == "\n\n",
        "Ctrl+Enter did not insert a line break",
    )
    dialog.input._preedit_active = True
    dialog.input.keyPressEvent(enter)
    require(len(send_requests) == 1, "IME confirmation incorrectly requested sending")
    dialog.input._preedit_active = False

    client = FakeClient()
    dialog.client = client
    dialog.input.setPlainText("尚未就绪")
    transcript_before = dialog.transcript.toPlainText()
    dialog._send()
    require(
        dialog.input.toPlainText() == "尚未就绪",
        "message was lost before the Codex thread was ready",
    )
    require(
        dialog.transcript.toPlainText() == transcript_before,
        "unsent message was added to the transcript",
    )

    client.thread_id = "thread-1"
    dialog._set_ready(True)
    require(
        dialog.model_settings_button.isEnabled(),
        "model settings are unavailable while Codex is ready",
    )
    dialog.input.setPlainText("可以发送")
    dialog._send()
    require(client.sent == ["可以发送"], "ready message was not sent")
    require(
        client.python_modes == [False],
        "the live unrestricted-Python state was not supplied with the turn",
    )
    require(
        client.turn_settings == [("gpt-test", "high", "priority")],
        "model settings were not supplied with the user turn",
    )
    require(not dialog.input.toPlainText(), "sent input was not cleared")
    require(not dialog.send_button.isEnabled(), "turn UI did not become active")
    require(
        not dialog.model_settings_button.isEnabled(),
        "model settings remain enabled during an active turn",
    )
    dialog._finish_turn_ui()
    require(
        dialog.model_settings_button.isEnabled(),
        "model settings were not restored after the turn",
    )
    client.thread_id = None
    dialog._finish_turn_ui()
    require(
        not dialog.send_button.isEnabled()
        and not dialog.model_settings_button.isEnabled(),
        "turn cleanup re-enabled controls after the conversation disconnected",
    )
    client.thread_id = "thread-1"
    dialog._set_ready(True)
    dialog._set_turn_active()

    secret_echo_modes = []

    def answer_secret_question():
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QInputDialog):
                secret_echo_modes.append(widget.textEchoMode())
                widget.setTextValue("example-secret")
                widget.accept()
                return

    QtCore.QTimer.singleShot(0, answer_secret_question)
    dialog._request_user_input(
        61,
        {
            "questions": [
                {
                    "id": "secret_value",
                    "header": "敏感输入",
                    "question": "请输入测试值",
                    "isSecret": True,
                }
            ]
        },
    )
    require(
        secret_echo_modes == [QtWidgets.QLineEdit.Password]
        and client.responses[-1]
        == (
            61,
            {
                "answers": {
                    "secret_value": {"answers": ["example-secret"]}
                }
            },
        ),
        "secret user input was not masked or returned correctly",
    )

    executor = RecordingExecutor(dialog.runtime_directory)
    dialog.executor = executor
    client.turn_id = "turn-1"
    dialog._tool_call(
        7,
        {
            "tool": "pymol_inspect",
            "arguments": {},
            "callId": "call-1",
        },
    )
    require(
        not executor.inspect_calls,
        "tool request without conversation identity reached PyMOL",
    )
    require(
        client.responses[-1][1]["success"] is False,
        "invalid tool request was not rejected",
    )
    dialog._tool_call(
        8,
        {
            "tool": "pymol_inspect",
            "arguments": {},
            "callId": "call-1",
            "threadId": "thread-1",
            "turnId": "turn-1",
        },
    )
    require(len(executor.inspect_calls) == 1, "active tool request was not executed")
    require(
        client.responses[-1][1]["success"] is True,
        "active tool request did not return success",
    )
    for request_id, call_id in (
        (81, "apply-1"),
        (82, "apply-2"),
    ):
        dialog._tool_call(
            request_id,
            {
                "tool": "pymol_apply",
                "arguments": {
                    "operations": [
                        {
                            "action": "show",
                            "representation": "cartoon",
                        }
                    ],
                    "include_snapshot": False,
                },
                "callId": call_id,
                "threadId": "thread-1",
                "turnId": "turn-1",
            },
        )
    require(
        len(executor.apply_calls) == 2
        and len(executor.checkpoints.create_calls) == 1,
        "one instruction did not reuse a single pre-mutation checkpoint",
    )
    require(
        not dialog.undo_button.isEnabled(),
        "instruction undo became enabled during an active turn",
    )
    client.turn_id = None
    dialog._finish_turn_ui()
    require(
        dialog.undo_button.isEnabled(),
        "instruction undo was not enabled after a modifying turn",
    )
    original_confirm = dialog._confirm
    dialog._confirm = lambda *_args, **_kwargs: True
    dialog._undo_last_instruction()
    dialog._confirm = original_confirm
    require(
        executor.checkpoints.undo_calls == 1
        and not dialog.undo_button.isEnabled()
        and "已撤销最新一轮对 PyMOL 会话的修改"
        in dialog.transcript.toPlainText(),
        "instruction undo did not consume and restore its checkpoint",
    )
    client.turn_id = "turn-1"
    dialog._set_turn_active()
    blocked_call = {
        "tool": "pymol_python_exec",
        "arguments": {
            "code": "print('should not run')",
            "reason": "需要调用尚未受控的 PyMOL API",
        },
        "callId": "call-python-disabled",
        "threadId": "thread-1",
        "turnId": "turn-1",
    }
    transcript_before_block = dialog.transcript.toPlainText()
    dialog._protocol_message(
        {
            "method": "item/started",
            "params": {
                "item": {
                    "type": "dynamicToolCall",
                    "tool": "pymol_python_exec",
                }
            },
        }
    )
    require(
        dialog.transcript.toPlainText() == transcript_before_block,
        "disabled Python was misleadingly shown as executing",
    )
    dialog._tool_call(9, blocked_call)
    blocked_response = client.responses[-1][1]
    blocked_result = json.loads(
        blocked_response["contentItems"][0]["text"]
    )
    require(
        blocked_response["success"] is False
        and blocked_result["error_code"]
        == "unrestricted_python_disabled"
        and blocked_result["turn_will_stop"] is True,
        "disabled unrestricted Python did not return a structured hard gate",
    )
    require(
        client.events[-2:] == [
            ("respond", 9),
            ("interrupt", "turn-1"),
        ],
        "the blocked tool was not answered before the turn was interrupted",
    )
    require(
        client.interrupt_count == 1
        and "已阻止不受限 Python"
        in dialog.transcript.toPlainText()
        and "需要启用不受限 Python"
        in dialog.status_label.text(),
        "disabled unrestricted Python did not stop with a user-facing prompt",
    )
    blocked_notice_count = dialog.transcript.toPlainText().count(
        "已阻止不受限 Python"
    )
    dialog._tool_call(10, blocked_call)
    require(
        client.interrupt_count == 1
        and dialog.transcript.toPlainText().count("已阻止不受限 Python")
        == blocked_notice_count,
        "a replayed blocked Python call interrupted or notified twice",
    )

    dialog._set_codex_selector_visible(False)
    client.thread_id = None
    client.turn_id = None
    diagnostic_before = dialog.transcript.toPlainText()
    dialog._show_diagnostic(
        "2026-07-29T09:19:43.643664Z ERROR codex_models_manager::manager: "
        "failed to refresh available models: timeout waiting for child process to exit"
    )
    dialog._show_diagnostic(
        "2026-07-29T09:19:43.676386Z ERROR codex_models_manager::manager: "
        "failed to refresh available models: timeout waiting for child process to exit"
    )
    require(
        dialog.transcript.toPlainText() == diagnostic_before,
        "non-fatal stderr diagnostic polluted the chat transcript",
    )
    dialog._show_error("初始化失败")
    require(
        not dialog.choose_button.isHidden(),
        "Codex chooser was not restored after initialization failure",
    )
    require(
        dialog.transcript.toPlainText().count("Codex 启动诊断：") == 1,
        "startup diagnostics were not shown exactly once on a real failure",
    )
    require(
        "刷新可用模型列表超时（后台进程未按时退出）。"
        in dialog.transcript.toPlainText()
        and "codex_models_manager" not in dialog.transcript.toPlainText(),
        "startup diagnostic was not converted to a clean user-facing summary",
    )
    dialog._show_error("初始化仍失败")
    require(
        dialog.transcript.toPlainText().count("Codex 启动诊断：") == 1,
        "duplicate startup diagnostic was shown more than once",
    )

    dialog.transcript.clear()
    dialog._append_block("你", "你好。")
    dialog._protocol_message(
        {"method": "item/agentMessage/delta", "params": {"delta": "收到。"}}
    )
    transcript = dialog.transcript.toPlainText()
    require("你：你好。" in transcript, "user content is not rendered inline")
    require("Codex：收到。" in transcript, "Codex content is not rendered inline")
    require("你：\n" not in transcript, "user content still has a forced line break")
    dialog._protocol_message(
        {"method": "turn/completed", "params": {}}
    )
    require(
        not dialog.transcript.toPlainText().endswith("\n"),
        "a completed reply still leaves a trailing line break",
    )
    dialog._append_block("你", "下一句。")
    require(
        dialog.transcript.toPlainText()
        == "你：你好。\nCodex：收到。\n你：下一句。",
        "the next message was not separated by exactly one lazy line break: "
        + repr(dialog.transcript.toPlainText()),
    )

    dialog.transcript.clear()
    dialog._assistant_streaming = True
    dialog._append_system("正在执行：修改 PyMOL 场景")
    dialog._protocol_message(
        {
            "method": "item/agentMessage/delta",
            "params": {"delta": "结构正在下载。"},
        }
    )
    require(
        "[正在执行：修改 PyMOL 场景] 结构正在下载。"
        in dialog.transcript.toPlainText(),
        "streaming text is still attached directly to a system marker",
    )

    approval = ui.PythonApprovalDialog("print('ok')", "", dialog)
    require(
        approval.windowTitle() == "批准执行不受限 Python",
        "Python approval title is not localized",
    )
    button_box = approval.findChild(QtWidgets.QDialogButtonBox)
    require(
        button_box.button(QtWidgets.QDialogButtonBox.Yes).text() == "执行代码",
        "Python approval button is not localized",
    )
    require(
        button_box.button(QtWidgets.QDialogButtonBox.No).text() == "取消",
        "Python cancel button is not localized",
    )

    main_window = QtWidgets.QMainWindow()
    main_window.resize(1000, 800)
    main_window.setCentralWidget(QtWidgets.QWidget())
    console_dock = QtWidgets.QDockWidget("External GUI", main_window)
    console_editor = QtWidgets.QPlainTextEdit()
    console_editor.verticalScrollBar().setObjectName("pymol_scroll_bar")
    console_scrollbar_style = (
        "QScrollBar:vertical { width: 13px; }"
        "QScrollBar::handle:vertical { min-height: 17px; }"
    )
    console_editor.verticalScrollBar().setStyleSheet(
        console_scrollbar_style
    )
    console_font = QtGui.QFontDatabase.systemFont(
        QtGui.QFontDatabase.FixedFont
    )
    console_font.setPointSize(13)
    console_editor.setFont(console_font)
    console_editor.document().setDocumentMargin(3.0)
    dark_palette = console_editor.palette()
    for group in (
        QtGui.QPalette.Active,
        QtGui.QPalette.Inactive,
        QtGui.QPalette.Disabled,
    ):
        # PyMOL's dark console palette can carry a light ButtonText role even
        # though the Windows style paints a light native button surface.
        dark_palette.setColor(
            group,
            QtGui.QPalette.Button,
            QtGui.QColor("#f0f0f0"),
        )
        dark_palette.setColor(
            group,
            QtGui.QPalette.ButtonText,
            QtGui.QColor("#e8e8e8"),
        )
    dark_palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#222222"))
    dark_palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#e8e8e8"))
    console_editor.setPalette(dark_palette)
    console_dock.setWidget(console_editor)
    main_window.dockWidget = console_dock
    main_window.addDockWidget(QtCore.Qt.BottomDockWidgetArea, console_dock)
    codex_dock, docked_dialog = create_codex_dock(
        main_window,
        dialog_class=TestCodexDialog,
    )
    main_window.show()
    release_wait = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(150, release_wait.quit)
    release_wait.exec_()
    app.processEvents(QtCore.QEventLoop.AllEvents)
    require(
        main_window.dockWidgetArea(codex_dock) == QtCore.Qt.BottomDockWidgetArea,
        "Codex is not docked at the bottom",
    )
    require(
        codex_dock in main_window.tabifiedDockWidgets(console_dock),
        "Codex is not tabified with the PyMOL console",
    )
    require(
        console_dock.windowTitle() == "External GUI",
        "creating the Codex dock unexpectedly renamed the native console tab",
    )
    require(
        not (codex_dock.features() & QtWidgets.QDockWidget.DockWidgetFloatable),
        "Codex dock can unexpectedly become a floating window",
    )
    require(
        not (codex_dock.features() & QtWidgets.QDockWidget.DockWidgetClosable),
        "Codex dock still exposes a close button",
    )
    require(
        codex_dock.titleBarWidget() is not None
        and codex_dock.titleBarWidget().height() == 0,
        "Codex dock title bar is still visible",
    )
    require(
        docked_dialog.transcript.palette().color(QtGui.QPalette.Base)
        == QtGui.QColor("#222222"),
        "Codex transcript did not inherit the console background",
    )
    require(
        docked_dialog.status_label.palette().color(QtGui.QPalette.WindowText)
        == QtGui.QColor("#e8e8e8"),
        "Codex controls did not inherit the console foreground",
    )
    if os.name == "nt":
        expected_button_palette = app.style().standardPalette()
    else:
        expected_button_palette = QtGui.QPalette(dark_palette)
        for group in (
            QtGui.QPalette.Active,
            QtGui.QPalette.Inactive,
            QtGui.QPalette.Disabled,
        ):
            expected_button_palette.setColor(
                group, QtGui.QPalette.Button, QtGui.QColor("#222222")
            )
            expected_button_palette.setColor(
                group, QtGui.QPalette.ButtonText, QtGui.QColor("#e8e8e8")
            )
    require_button_palette(
        docked_dialog,
        expected_button_palette,
        "Codex panel",
    )
    require(
        docked_dialog.status_separator.height() == 1
        and "rgba(232, 232, 232, 72)"
        in docked_dialog.status_separator.styleSheet(),
        "status separator does not follow the dark console foreground",
    )
    require(
        not docked_dialog.status_label.wordWrap()
        and docked_dialog.status_label.height()
        <= docked_dialog.status_label.fontMetrics().height() + 2,
        "status row is taller than its single line of text",
    )
    initial_line_height = docked_dialog.transcript.fontMetrics().lineSpacing()
    initial_text_height = (
        docked_dialog.transcript.viewport().height()
        - int(
            round(
                docked_dialog.transcript.document().documentMargin() * 2
            )
        )
    )
    require(
        initial_line_height * 4 - 2
        <= initial_text_height
        <= initial_line_height * 4 + 2,
        "initial transcript height is not four text lines: "
        "{}px text at {}px/line".format(
            initial_text_height,
            initial_line_height,
        )
        + " preferred={} dock={} dialog={} footer={} transcript={}".format(
            docked_dialog.preferred_dock_height(4),
            codex_dock.height(),
            docked_dialog.height(),
            docked_dialog.footer_widget.height(),
            docked_dialog.transcript.height(),
        ),
    )
    themed_model_dialog = ui.ModelSettingsDialog(
        [first_model, second_model],
        parent=docked_dialog,
    )
    docked_dialog._model_settings_dialog = themed_model_dialog
    themed_model_dialog.apply_host_palette(docked_dialog.palette())
    require(
        "rgba(232, 232, 232, 255)"
        in themed_model_dialog.styleSheet(),
        "model dialog labels do not explicitly follow the dark foreground",
    )
    require(
        themed_model_dialog.details_label.palette().color(
            QtGui.QPalette.WindowText
        )
        == QtGui.QColor("#e8e8e8"),
        "model details text does not inherit the dark foreground",
    )
    require_button_palette(
        themed_model_dialog,
        expected_button_palette,
        "model settings dialog",
    )
    require_combo_palette(
        themed_model_dialog,
        app.style().standardPalette(),
        "model settings dialog",
    )
    themed_approval = ui.PythonApprovalDialog(
        "print('ok')",
        "UI theme test",
        docked_dialog,
    )
    require_button_palette(
        themed_approval,
        expected_button_palette,
        "Python approval dialog",
    )
    themed_approval.close()
    root_margins = docked_dialog.layout().contentsMargins()
    require(
        (
            root_margins.left(),
            root_margins.top(),
            root_margins.right(),
            root_margins.bottom(),
        )
        == (1, 1, 1, 1)
        and docked_dialog.layout().spacing() == 0,
        "Codex root layout does not match PyMOL's borderless console layout",
    )
    require(
        docked_dialog.transcript.font() == console_editor.font()
        and docked_dialog.input.font() == console_editor.font(),
        "Codex text widgets do not use the PyMOL console font",
    )
    require(
        docked_dialog.transcript.document().documentMargin()
        == console_editor.document().documentMargin(),
        "Codex transcript does not use the console text inset",
    )
    status_margins = docked_dialog.status_row.contentsMargins()
    expected_text_inset = int(
        round(console_editor.document().documentMargin())
    )
    require(
        (
            status_margins.left(),
            status_margins.top(),
            status_margins.right(),
            status_margins.bottom(),
        )
        == (expected_text_inset, 0, expected_text_inset, 0),
        "Codex status row does not align with the transcript text inset",
    )
    for editor in (docked_dialog.transcript, docked_dialog.input):
        require(
            editor.verticalScrollBar().objectName() == "pymol_scroll_bar",
            "Codex editor does not use PyMOL's scrollbar style hook",
        )
        require(
            editor.verticalScrollBar().styleSheet()
            == console_scrollbar_style,
            "Codex editor did not inherit the console scrollbar stylesheet",
        )
    light_palette = console_editor.palette()
    light_palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#fafafa"))
    light_palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#202020"))
    console_editor.setPalette(light_palette)
    app.processEvents(QtCore.QEventLoop.AllEvents)
    require(
        docked_dialog.transcript.palette().color(QtGui.QPalette.Base)
        == QtGui.QColor("#fafafa"),
        "Codex background did not follow a console palette change",
    )
    require(
        docked_dialog.status_label.palette().color(QtGui.QPalette.WindowText)
        == QtGui.QColor("#202020"),
        "Codex foreground did not follow a console palette change",
    )
    require(
        "rgba(32, 32, 32, 255)"
        in themed_model_dialog.styleSheet(),
        "open model dialog did not follow the light foreground",
    )
    require(
        "rgba(32, 32, 32, 72)"
        in docked_dialog.status_separator.styleSheet(),
        "status separator did not follow the light console foreground",
    )
    docked_dialog._model_settings_dialog = None
    themed_model_dialog.close()
    themed_model_dialog.deleteLater()
    changed_font = QtGui.QFont(console_editor.font())
    changed_font.setPointSize(changed_font.pointSize() + 1)
    changed_scrollbar_style = (
        "QScrollBar:vertical { width: 11px; }"
        "QScrollBar::handle:vertical { min-height: 19px; }"
    )
    console_editor.setFont(changed_font)
    console_editor.verticalScrollBar().setStyleSheet(
        changed_scrollbar_style
    )
    app.processEvents(QtCore.QEventLoop.AllEvents)
    require(
        docked_dialog.transcript.font() == changed_font
        and docked_dialog.input.font() == changed_font,
        "Codex text widgets did not follow a console font change",
    )
    require(
        docked_dialog.transcript.verticalScrollBar().styleSheet()
        == changed_scrollbar_style,
        "Codex scrollbar did not follow a console style change",
    )
    console_editor.setPalette(dark_palette)
    app.processEvents(QtCore.QEventLoop.AllEvents)
    require(
        docked_dialog.autoFillBackground()
        and docked_dialog.footer_widget.autoFillBackground(),
        "Codex transparent containers do not paint the console background",
    )
    require(
        docked_dialog.footer_widget.palette().color(QtGui.QPalette.Window)
        == QtGui.QColor("#222222"),
        "Codex footer does not use the console background",
    )
    footer_pixmap = docked_dialog.footer_widget.grab()
    footer_image = footer_pixmap.toImage()
    device_pixel_ratio = max(1.0, float(footer_pixmap.devicePixelRatio()))
    background_sample_y = int(
        round(
            (docked_dialog.status_separator.geometry().bottom() + 2)
            * device_pixel_ratio
        )
    )
    require(
        footer_image.pixelColor(1, background_sample_y)
        == QtGui.QColor("#222222"),
        "Codex footer does not render the console background",
    )
    require(
        docked_dialog.status_label.palette().color(QtGui.QPalette.WindowText)
        == QtGui.QColor("#e8e8e8")
        and docked_dialog.python_checkbox.palette().color(
            QtGui.QPalette.WindowText
        )
        == QtGui.QColor("#e8e8e8"),
        "status or Python text does not use the console foreground",
    )
    transcript_bottom = (
        docked_dialog.transcript.mapTo(
            docked_dialog, QtCore.QPoint(0, 0)
        ).y()
        + docked_dialog.transcript.height()
    )
    status_top = docked_dialog.status_label.mapTo(
        docked_dialog, QtCore.QPoint(0, 0)
    ).y()
    status_bottom = status_top + docked_dialog.status_label.height()
    input_top = docked_dialog.input.mapTo(
        docked_dialog, QtCore.QPoint(0, 0)
    ).y()
    require(
        transcript_bottom <= status_top <= status_bottom <= input_top,
        "status line is not between the transcript and message editor",
    )
    transcript_text_left = (
        docked_dialog.transcript.viewport().mapTo(
            docked_dialog, QtCore.QPoint(0, 0)
        ).x()
        + expected_text_inset
    )
    status_text_left = docked_dialog.status_label.mapTo(
        docked_dialog, QtCore.QPoint(0, 0)
    ).x()
    require(
        abs(transcript_text_left - status_text_left) <= 1,
        "status text is not horizontally aligned with transcript text",
    )
    line_height = docked_dialog.input.fontMetrics().lineSpacing()
    text_area_height = (
        docked_dialog.input.viewport().height()
        - int(docked_dialog.input.document().documentMargin() * 2)
    )
    require(
        line_height * 2 <= text_area_height <= line_height * 2 + 4,
        "message editor is not approximately two lines high",
    )
    require(
        docked_dialog.input.verticalScrollBarPolicy()
        == QtCore.Qt.ScrollBarAsNeeded,
        "message editor scrollbar is not configured to appear as needed",
    )
    docked_dialog.input.setPlainText("第一行\n第二行\n第三行")
    app.processEvents(QtCore.QEventLoop.AllEvents)
    require(
        docked_dialog.input.verticalScrollBar().maximum() > 0
        and docked_dialog.input.verticalScrollBar().styleSheet()
        == docked_dialog.transcript.verticalScrollBar().styleSheet(),
        "overflowing message input does not show the transcript-style scrollbar",
    )
    docked_dialog.input.clear()
    send_center = docked_dialog.send_button.mapTo(
        docked_dialog, docked_dialog.send_button.rect().center()
    ).y()
    python_center = docked_dialog.python_checkbox.mapTo(
        docked_dialog, docked_dialog.python_checkbox.rect().center()
    ).y()
    undo_center = docked_dialog.undo_button.mapTo(
        docked_dialog, docked_dialog.undo_button.rect().center()
    ).y()
    model_settings_center = docked_dialog.model_settings_button.mapTo(
        docked_dialog,
        docked_dialog.model_settings_button.rect().center(),
    ).y()
    require(
        abs(send_center - python_center) <= 2
        and abs(send_center - model_settings_center) <= 2
        and abs(send_center - undo_center) <= 2,
        "model, Python, or checkpoint controls do not share the action row",
    )
    require(
        docked_dialog.action_row.spacing() == 6
        and docked_dialog.action_row.indexOf(docked_dialog.send_button) == 0
        and docked_dialog.action_row.indexOf(docked_dialog.stop_button) == 1
        and docked_dialog.action_row.indexOf(docked_dialog.new_button) == 2
        and docked_dialog.action_row.indexOf(
            docked_dialog.model_settings_button
        )
        == 3
        and docked_dialog.action_row.indexOf(
            docked_dialog.python_checkbox
        )
        == 5
        and docked_dialog.action_row.indexOf(docked_dialog.undo_button) == 6,
        "action controls do not have the requested breathing room",
    )
    require(
        docked_dialog.transcript.frameShape() == QtWidgets.QFrame.NoFrame,
        "Codex transcript still has a visible frame",
    )
    footer_margins = docked_dialog.footer_widget.layout().contentsMargins()
    require(
        (
            footer_margins.left(),
            footer_margins.top(),
            footer_margins.right(),
            footer_margins.bottom(),
        )
        == (0, 0, 0, 0)
        and docked_dialog.footer_widget.layout().spacing() == 4,
        "Codex footer still wastes space on non-native padding",
    )
    docked_dialog.transcript.setPlainText(
        "\n".join("message {}".format(index) for index in range(100))
    )
    main_window.resizeDocks([codex_dock], [220], QtCore.Qt.Vertical)
    app.processEvents(QtCore.QEventLoop.AllEvents)
    compact_transcript_height = docked_dialog.transcript.height()
    compact_footer_height = docked_dialog.footer_widget.height()
    compact_footer_gap = (
        docked_dialog.height() - docked_dialog.footer_widget.geometry().bottom()
    )
    require(
        docked_dialog.transcript.verticalScrollBar().maximum() > 0,
        "compact transcript does not expose its vertical scrollbar",
    )
    main_window.resizeDocks([codex_dock], [520], QtCore.Qt.Vertical)
    app.processEvents(QtCore.QEventLoop.AllEvents)
    require(
        docked_dialog.footer_widget.height() == compact_footer_height,
        "footer height changed while resizing the dock",
    )
    require(
        abs(
            docked_dialog.height()
            - docked_dialog.footer_widget.geometry().bottom()
            - compact_footer_gap
        )
        <= 1,
        "footer did not remain anchored to the bottom",
    )
    require(
        docked_dialog.transcript.height() > compact_transcript_height,
        "extra dock height was not assigned to the transcript",
    )
    docked_dialog.full_python_enabled = True
    console_dock.raise_()
    app.processEvents(QtCore.QEventLoop.AllEvents)
    require(
        not docked_dialog.full_python_enabled,
        "switching away from Codex did not lock unrestricted Python",
    )
    codex_dock.raise_()
    app.processEvents(QtCore.QEventLoop.AllEvents)
    docked_dialog.full_python_enabled = True
    codex_dock.close()
    require(codex_dock.isHidden(), "Codex dock did not close")
    require(
        not docked_dialog.full_python_enabled,
        "closing the dock did not lock unrestricted Python",
    )
    codex_dock.show()
    codex_dock.raise_()
    require(not codex_dock.isHidden(), "Codex dock cannot be reopened")

    dialog.full_python_enabled = True
    dialog.python_checkbox.blockSignals(True)
    dialog.python_checkbox.setChecked(True)
    dialog.python_checkbox.blockSignals(False)
    dialog._client_stopped()
    require(
        not dialog.full_python_enabled
        and not dialog.python_checkbox.isChecked(),
        "a stopped Codex process retained unrestricted Python permission",
    )

    approval.close()
    model_dialog.close()
    protocol_client.close()
    dialog.settings.clear()
    dialog.close()
    docked_dialog.shutdown()
    main_window.close()
    app.processEvents(QtCore.QEventLoop.AllEvents)
    print("PyMOL Qt UI smoke test passed")


if __name__ == "__main__":
    main()
