"""Qt/QProcess Codex App Server client."""

from pathlib import Path

from pymol.Qt import QtCore

from .i18n import text as tr
from .discovery import (
    CodexFeatureDiscoveryError,
    FEATURE_DISCOVERY_TIMEOUT_SECONDS,
    feature_invocation,
    parse_feature_list,
    process_invocation,
)
from .protocol import (
    JsonLineBuffer,
    RequestTracker,
    Utf8ChunkDecoder,
    encode_message,
    error_message,
    error_will_retry,
    format_diagnostic,
    is_reconnect_notice,
    is_current_notification,
    notification_turn_id,
    validated_ephemeral_thread_id,
)
from .tool_specs import (
    DEVELOPER_INSTRUCTIONS,
    dynamic_tools,
    python_mode_context,
)
from .version import __version__


def _start_process(process, invocation):
    if invocation.environment:
        environment = QtCore.QProcessEnvironment.systemEnvironment()
        for name, value in invocation.environment.items():
            environment.insert(name, value)
        process.setProcessEnvironment(environment)
    process.start(invocation.program, invocation.arguments)


class AppServerClient(QtCore.QObject):
    message = QtCore.Signal(dict) if hasattr(QtCore, "Signal") else QtCore.pyqtSignal(dict)
    status = QtCore.Signal(str) if hasattr(QtCore, "Signal") else QtCore.pyqtSignal(str)
    error = QtCore.Signal(str) if hasattr(QtCore, "Signal") else QtCore.pyqtSignal(str)
    diagnostic = (
        QtCore.Signal(str) if hasattr(QtCore, "Signal") else QtCore.pyqtSignal(str)
    )
    ready = QtCore.Signal(str) if hasattr(QtCore, "Signal") else QtCore.pyqtSignal(str)
    stopped = QtCore.Signal() if hasattr(QtCore, "Signal") else QtCore.pyqtSignal()
    turn_failed = (
        QtCore.Signal(str) if hasattr(QtCore, "Signal") else QtCore.pyqtSignal(str)
    )
    tool_call = (
        QtCore.Signal(object, dict)
        if hasattr(QtCore, "Signal")
        else QtCore.pyqtSignal(object, dict)
    )
    user_input = (
        QtCore.Signal(object, dict)
        if hasattr(QtCore, "Signal")
        else QtCore.pyqtSignal(object, dict)
    )
    model_catalog = (
        QtCore.Signal(object)
        if hasattr(QtCore, "Signal")
        else QtCore.pyqtSignal(object)
    )
    model_catalog_error = (
        QtCore.Signal(str) if hasattr(QtCore, "Signal") else QtCore.pyqtSignal(str)
    )

    def __init__(self, executable, runtime_directory, parent=None):
        super().__init__(parent)
        self.executable = executable
        self.runtime_directory = str(Path(runtime_directory))
        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.SeparateChannels)
        self.process.started.connect(self._initialize)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(self._process_finished)
        self.feature_process = QtCore.QProcess(self)
        self.feature_process.setProcessChannelMode(
            QtCore.QProcess.SeparateChannels
        )
        self.feature_process.errorOccurred.connect(
            self._feature_process_error
        )
        self.feature_process.finished.connect(
            self._feature_process_finished
        )
        self.buffer = JsonLineBuffer()
        self._stdout_decoder = Utf8ChunkDecoder()
        self._stderr_decoder = Utf8ChunkDecoder()
        self._stderr_text_buffer = ""
        self.requests = RequestTracker()
        self.thread_id = None
        self.turn_id = None
        self._interrupt_pending = False
        self._thread_generation = 0
        self._model_request_generation = 0
        self._closing = False
        self._feature_probe_active = False
        self._feature_probe_generation = 0
        self._turn_active = False
        self._finished_turn_ids = []
        self._process_abort_pending = False

    def start(self):
        if (
            self.process.state() != QtCore.QProcess.NotRunning
            or self.feature_process.state() != QtCore.QProcess.NotRunning
            or self._feature_probe_active
        ):
            return
        self._closing = False
        self._process_abort_pending = False
        self._feature_probe_active = True
        self._feature_probe_generation += 1
        generation = self._feature_probe_generation
        invocation = feature_invocation(self.executable)
        self.feature_process.setWorkingDirectory(self.runtime_directory)
        self.status.emit(tr("backend.checking_features"))
        _start_process(self.feature_process, invocation)
        QtCore.QTimer.singleShot(
            FEATURE_DISCOVERY_TIMEOUT_SECONDS * 1000,
            lambda: self._feature_probe_timeout(generation),
        )

    def _feature_probe_timeout(self, generation):
        if (
            generation != self._feature_probe_generation
            or not self._feature_probe_active
        ):
            return
        self._feature_probe_failed(tr("backend.feature_timeout", path=self.executable))

    def _feature_process_error(self, _error):
        if self._closing or not self._feature_probe_active:
            return
        self._feature_probe_failed(tr(
            "backend.feature_start_failed",
            path=self.executable,
            detail=self.feature_process.errorString(),
        ))

    def _feature_process_finished(self, exit_code, exit_status):
        if self._closing or not self._feature_probe_active:
            return
        if (
            exit_status != QtCore.QProcess.NormalExit
            or exit_code != 0
        ):
            stderr = bytes(
                self.feature_process.readAllStandardError()
            ).decode("utf-8", "replace")
            stderr = " ".join(stderr.split())[:1000]
            detail = ""
            if stderr:
                detail = tr("backend.feature_detail", detail=stderr)
            self._feature_probe_failed(
                tr(
                    "backend.feature_exit",
                    path=self.executable,
                    code=exit_code,
                ) + detail
            )
            return
        raw = bytes(
            self.feature_process.readAllStandardOutput()
        ).decode("utf-8", "replace")
        available_features = parse_feature_list(raw)
        if not available_features:
            self._feature_probe_failed(tr("backend.feature_empty"))
            return
        self._start_app_server(available_features)

    def _feature_probe_failed(self, detail):
        if not self._feature_probe_active:
            return
        self._feature_probe_active = False
        self._feature_probe_generation += 1
        if self.feature_process.state() != QtCore.QProcess.NotRunning:
            self.feature_process.kill()
        error = CodexFeatureDiscoveryError(tr("backend.start_aborted", detail=detail))
        self.error.emit(str(error))
        self.stopped.emit()

    def _start_app_server(self, available_features):
        if self._closing:
            return
        try:
            invocation = process_invocation(
                self.executable,
                available_features,
            )
        except Exception as exc:
            self._feature_probe_failed(tr("backend.safe_args_failed", detail=exc))
            return
        self._feature_probe_active = False
        self.process.setWorkingDirectory(self.runtime_directory)
        self.status.emit(tr("backend.starting"))
        _start_process(self.process, invocation)

    def _initialize(self):
        params = {
            "clientInfo": {
                "name": "codex_for_pymol",
                "title": tr("backend.client_title"),
                "version": __version__,
            },
            "capabilities": {"experimentalApi": True},
        }
        self.send_request("initialize", params, self._initialized)

    def _initialized(self, result, error):
        if error:
            self.error.emit(tr("backend.init_failed", detail=error_message(error)))
            self._stop_unusable_process()
            return
        self.send_notification("initialized", {})
        try:
            self.refresh_models()
        except Exception:
            self.model_catalog_error.emit(tr("backend.model_failed"))
        self.new_thread()

    def new_thread(self):
        self._thread_generation += 1
        generation = self._thread_generation
        self.thread_id = None
        self.turn_id = None
        self._turn_active = False
        self._interrupt_pending = False
        self._finished_turn_ids = []
        self.status.emit(tr("backend.new_thread"))
        self.send_request(
            "thread/start",
            {
                "cwd": self.runtime_directory,
                "sandbox": "read-only",
                "approvalPolicy": "never",
                "developerInstructions": DEVELOPER_INSTRUCTIONS,
                "dynamicTools": dynamic_tools(),
                "environments": [],
                "ephemeral": True,
                "serviceName": "codex_for_pymol",
            },
            lambda result, error: self._thread_started(
                result, error, generation
            ),
        )

    def _thread_started(self, result, error, generation):
        if generation != self._thread_generation:
            return
        if error:
            self.error.emit(tr("backend.new_thread_failed", detail=error_message(error)))
            self._stop_unusable_process()
            return
        self._accept_thread(result, generation)

    def _accept_thread(self, result, generation=None):
        if generation is None:
            generation = self._thread_generation
        if generation != self._thread_generation:
            return
        try:
            self.thread_id = validated_ephemeral_thread_id(result)
        except ValueError as exc:
            self.thread_id = None
            thread = result.get("thread") if isinstance(result, dict) else None
            rejected_id = thread.get("id") if isinstance(thread, dict) else None
            self.error.emit(tr("backend.unsafe_thread", detail=exc))
            if isinstance(rejected_id, str) and rejected_id.strip():
                def cleanup_finished(cleanup_result, cleanup_error):
                    self._rejected_thread_deleted(
                        cleanup_result,
                        cleanup_error,
                        generation,
                        rejected_id,
                    )

                try:
                    request_id = self.send_request(
                        "thread/delete",
                        {"threadId": rejected_id},
                        cleanup_finished,
                    )
                except Exception as cleanup_error:
                    self.error.emit(tr(
                        "backend.cleanup_thread",
                        thread_id=rejected_id,
                        detail=cleanup_error,
                    ))
                    self._stop_unusable_process()
                else:
                    QtCore.QTimer.singleShot(
                        1000,
                        lambda: self.requests.reject(
                            request_id,
                            {
                                "code": -32001,
                                "message": tr("backend.request_timeout", method="thread/delete"),
                            },
                        ),
                    )
            else:
                self._stop_unusable_process()
            return
        self.status.emit(tr("status.ready"))
        self.ready.emit(self.thread_id)

    def _rejected_thread_deleted(
        self,
        _result,
        error,
        generation,
        rejected_id,
    ):
        """Finish cleanup without letting an old callback stop a new thread."""
        if error:
            self.error.emit(tr(
                "backend.cleanup_thread",
                thread_id=rejected_id,
                detail=error_message(error),
            ))
        if generation == self._thread_generation:
            self._stop_unusable_process()

    def start_turn(
        self,
        text,
        unrestricted_python_enabled=False,
        model="",
        effort="",
        service_tier="",
    ):
        if not self.thread_id:
            raise RuntimeError(tr("backend.thread_not_ready"))
        self.status.emit(tr("backend.processing"))
        params = {
            "threadId": self.thread_id,
            "input": [{"type": "text", "text": text}],
            "additionalContext": python_mode_context(
                unrestricted_python_enabled
            ),
        }
        if model:
            params["model"] = model
        if effort:
            params["effort"] = effort
        if service_tier:
            params["serviceTier"] = service_tier
        self._turn_active = True
        try:
            self.send_request(
                "turn/start",
                params,
                self._turn_accepted,
            )
        except Exception:
            self._turn_active = False
            self.status.emit(tr("status.ready"))
            raise

    def refresh_models(self):
        self._model_request_generation += 1
        generation = self._model_request_generation
        self._request_model_page(generation, None, [], 0)

    def _request_model_page(
        self,
        generation,
        cursor,
        models,
        page_count,
    ):
        params = {"limit": 100, "includeHidden": False}
        if cursor:
            params["cursor"] = cursor
        self.send_request(
            "model/list",
            params,
            lambda result, error: self._model_page_received(
                generation,
                result,
                error,
                models,
                page_count,
            ),
        )

    def _model_page_received(
        self,
        generation,
        result,
        error,
        models,
        page_count,
    ):
        if generation != self._model_request_generation:
            return
        if error:
            self.model_catalog_error.emit(tr("backend.model_failed"))
            return

        if not isinstance(result, dict) or not isinstance(
            result.get("data"), list
        ):
            self.model_catalog_error.emit(tr("backend.model_failed"))
            return

        data = result["data"]
        cursor = result.get("nextCursor")
        if cursor is not None and not isinstance(cursor, str):
            self.model_catalog_error.emit(tr("backend.model_failed"))
            return
        models.extend(item for item in data if isinstance(item, dict))

        if cursor and page_count < 9 and len(models) < 1000:
            self._request_model_page(
                generation,
                cursor,
                models,
                page_count + 1,
            )
            return
        self.model_catalog.emit(models[:1000])

    def _turn_accepted(self, result, error):
        if not self._turn_active:
            return
        if error:
            message = tr("backend.send_failed", detail=error_message(error))
            response_timed_out = (
                isinstance(error, dict)
                and error.get("code") == -32001
            )
            self.turn_id = None
            self._turn_active = False
            self._interrupt_pending = False
            if response_timed_out:
                # Do not let the UI become ready again while this ambiguous
                # session is being terminated.
                self.thread_id = None
            self.status.emit(tr("status.ready"))
            self.error.emit(message)
            self.turn_failed.emit(message)
            if response_timed_out:
                # The server may have accepted the turn even though its reply
                # was lost. Stop the ambiguous session so a later message
                # cannot overlap with an invisible, still-running turn.
                self._stop_unusable_process()
            return
        turn = (result or {}).get("turn") or {}
        self.turn_id = turn.get("id") or self.turn_id
        self._flush_pending_interrupt()

    def interrupt(self):
        if not self.thread_id:
            return False
        if not self.turn_id:
            self._interrupt_pending = True
            self.status.emit(tr("backend.stop_queued"))
            return True
        self._send_interrupt()
        return True

    def _send_interrupt(self):
        self._interrupt_pending = False
        self.send_request(
            "turn/interrupt",
            {"threadId": self.thread_id, "turnId": self.turn_id},
        )

    def _flush_pending_interrupt(self):
        if self._interrupt_pending and self.thread_id and self.turn_id:
            self._send_interrupt()

    def respond(self, request_id, result=None, error=None):
        message = {"id": request_id}
        if error is not None:
            message["error"] = error
        else:
            message["result"] = result
        self._write(message)

    def send_request(self, method, params=None, callback=None):
        request_id = self.requests.create(callback)
        try:
            self._write({"method": method, "id": request_id, "params": params or {}})
        except Exception:
            self.requests.cancel(request_id)
            raise
        if callback is not None:
            QtCore.QTimer.singleShot(
                30000,
                lambda: self.requests.reject(
                    request_id,
                    {
                        "code": -32001,
                        "message": tr("backend.request_timeout", method=method),
                    },
                ),
            )
        return request_id

    def send_notification(self, method, params=None):
        self._write({"method": method, "params": params or {}})

    def _write(self, message):
        if self.process.state() == QtCore.QProcess.NotRunning:
            raise RuntimeError(tr("backend.not_running"))
        if self.process.write(encode_message(message)) < 0:
            raise RuntimeError(tr("backend.write_failed"))

    def _read_stdout(self):
        raw = self._stdout_decoder.decode(self.process.readAllStandardOutput())
        try:
            messages = self.buffer.feed(raw)
        except Exception as exc:
            self.error.emit(tr("backend.invalid_message", detail=exc))
            return
        for error in self.buffer.pop_errors():
            self.error.emit(tr("backend.invalid_message", detail=error))
        for message in messages:
            self._handle(message)

    def _read_stderr(self):
        raw = self._stderr_decoder.decode(self.process.readAllStandardError())
        self._consume_stderr(raw)

    def _consume_stderr(self, raw, final=False):
        """Emit only complete diagnostic lines from arbitrary process chunks."""
        self._stderr_text_buffer += str(raw or "")
        lines = self._stderr_text_buffer.split("\n")
        self._stderr_text_buffer = lines.pop()
        if final and self._stderr_text_buffer:
            lines.append(self._stderr_text_buffer)
            self._stderr_text_buffer = ""
        elif len(self._stderr_text_buffer) > 65536:
            # A malformed process that never terminates a line must not grow
            # the PyMOL process indefinitely. Preserve its most useful tail.
            lines.append(self._stderr_text_buffer[-65536:])
            self._stderr_text_buffer = ""

        # App Server may emit non-fatal loader warnings on stderr. Keep those
        # away from the primary status line; fatal process errors have their own
        # QProcess signals.
        for line in lines:
            formatted = format_diagnostic(line)
            if formatted and (
                "ERROR" in formatted.upper()
                or formatted.lower().startswith("error:")
            ):
                self.diagnostic.emit(formatted[-1000:])

    def _handle(self, message):
        if "method" not in message and "id" in message:
            self.requests.resolve(message)
            return

        method = message.get("method", "")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            if "id" in message:
                self.respond(
                    message["id"],
                    error={"code": -32602, "message": "Invalid request params"},
                )
            else:
                self.error.emit(tr("backend.invalid_params"))
            return
        if method == "item/tool/call" and "id" in message:
            self.tool_call.emit(message["id"], params)
            return
        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        } and "id" in message:
            # The PyMOL integration should use dynamic tools rather than shell/file edits.
            self.respond(message["id"], {"decision": "decline"})
            self.status.emit(tr("backend.rejected_scope"))
            return
        if method == "item/permissions/requestApproval" and "id" in message:
            self.respond(message["id"], {"permissions": {}})
            self.status.emit(tr("backend.rejected_permission"))
            return
        if method == "item/tool/requestUserInput" and "id" in message:
            if (
                params.get("threadId") != self.thread_id
                or params.get("turnId") != self.turn_id
            ):
                self.respond(message["id"], {"answers": {}})
                self.status.emit(tr("backend.rejected_stale_input"))
                return
            self.user_input.emit(message["id"], params)
            return
        if "id" in message:
            self.respond(
                message["id"],
                error={"code": -32601, "message": "Unsupported client request: " + method},
            )
            self.status.emit(tr("backend.unsupported_request", method=method))
            return
        if not is_current_notification(
            params,
            self.thread_id,
            self.turn_id,
            self._turn_active,
            self._finished_turn_ids,
        ):
            return
        if method == "turn/started":
            self.turn_id = (params.get("turn") or {}).get("id") or self.turn_id
            self._flush_pending_interrupt()
        elif method == "turn/completed":
            self._remember_finished_turn(
                notification_turn_id(params) or self.turn_id
            )
            self.turn_id = None
            self._turn_active = False
            self._interrupt_pending = False
            self.status.emit(tr("status.ready"))
        elif method == "error":
            error = params.get("error") or params
            if error_will_retry(params):
                message = error_message(error)
                if is_reconnect_notice(error):
                    progress = message.rsplit(" ", 1)[-1] if "/" in message else ""
                    suffix = tr("backend.progress_suffix", progress=progress) if progress else ""
                    self.status.emit(tr("backend.reconnecting", suffix=suffix))
                else:
                    self.status.emit(tr("backend.retrying"))
            else:
                failure = tr("backend.codex_error", detail=error_message(error))
                had_active_turn = self._turn_active
                self._remember_finished_turn(
                    notification_turn_id(params) or self.turn_id
                )
                self.turn_id = None
                self._turn_active = False
                self._interrupt_pending = False
                self.error.emit(failure)
                if had_active_turn:
                    self.turn_failed.emit(failure)
        self.message.emit(message)

    def _remember_finished_turn(self, turn_id):
        if not turn_id or turn_id in self._finished_turn_ids:
            return
        self._finished_turn_ids.append(turn_id)
        del self._finished_turn_ids[:-32]

    def _process_error(self, _error):
        if self._closing or self._process_abort_pending:
            return
        self.error.emit(tr("backend.process_error", detail=self.process.errorString()))

    def _stop_unusable_process(self):
        """Stop an unusable App Server without blocking the Qt event loop."""
        if self.process.state() == QtCore.QProcess.NotRunning:
            return
        self._process_abort_pending = True
        self.process.terminate()
        QtCore.QTimer.singleShot(1000, self._kill_unresponsive_process)

    def _kill_unresponsive_process(self):
        if (
            not self._closing
            and self._process_abort_pending
            and self.process.state() != QtCore.QProcess.NotRunning
        ):
            self.process.kill()

    def _process_finished(self, exit_code, _status):
        pending_stderr = (
            self.process.readAllStandardError()
            if self.process.isOpen()
            else b""
        )
        stderr_tail = self._stderr_decoder.decode(
            pending_stderr,
            final=True,
        )
        self._consume_stderr(stderr_tail, final=True)
        self._process_abort_pending = False
        self.thread_id = None
        self.turn_id = None
        self._turn_active = False
        self._interrupt_pending = False
        self._finished_turn_ids = []
        if self._closing:
            self.requests.clear()
            return
        self.requests.fail_all(
            {"code": -32000, "message": "Codex App Server stopped"}
        )
        self.status.emit(tr("backend.stopped", code=exit_code))
        self.stopped.emit()

    def close(self):
        self._closing = True
        self._feature_probe_active = False
        self._feature_probe_generation += 1
        self.thread_id = None
        self.turn_id = None
        self._turn_active = False
        self._finished_turn_ids = []
        self.requests.clear()
        if self.feature_process.state() != QtCore.QProcess.NotRunning:
            self.feature_process.terminate()
            if not self.feature_process.waitForFinished(500):
                self.feature_process.kill()
                self.feature_process.waitForFinished(500)
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(1500):
                self.process.kill()
                self.process.waitForFinished(1000)
