"""Qt/QProcess Codex App Server client."""

from pathlib import Path

from pymol.Qt import QtCore

from .discovery import (
    CodexFeatureDiscoveryError,
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
)
from .tool_specs import (
    DEVELOPER_INSTRUCTIONS,
    dynamic_tools,
    python_mode_context,
)
from .version import __version__


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

    def start(self):
        if (
            self.process.state() != QtCore.QProcess.NotRunning
            or self.feature_process.state() != QtCore.QProcess.NotRunning
            or self._feature_probe_active
        ):
            return
        self._closing = False
        self._feature_probe_active = True
        self._feature_probe_generation += 1
        generation = self._feature_probe_generation
        program, arguments = feature_invocation(self.executable)
        self.feature_process.setWorkingDirectory(self.runtime_directory)
        self.status.emit("正在检查当前 Codex 的安全功能…")
        self.feature_process.start(program, arguments)
        QtCore.QTimer.singleShot(
            3000,
            lambda: self._feature_probe_timeout(generation),
        )

    def _feature_probe_timeout(self, generation):
        if (
            generation != self._feature_probe_generation
            or not self._feature_probe_active
        ):
            return
        self._feature_probe_failed(
            "读取 Codex 功能列表超时。请在终端确认 "
            "“codex features list”可以正常完成。"
        )

    def _feature_process_error(self, _error):
        if self._closing or not self._feature_probe_active:
            return
        self._feature_probe_failed(
            "无法运行当前选择的 Codex：{}".format(
                self.feature_process.errorString()
            )
        )

    def _feature_process_finished(self, exit_code, exit_status):
        if self._closing or not self._feature_probe_active:
            return
        if (
            exit_status != QtCore.QProcess.NormalExit
            or exit_code != 0
        ):
            self._feature_probe_failed(
                "当前 Codex 无法提供功能列表（退出码 {}）。请确认该版本"
                "支持“codex features list”，或升级后重新选择 Codex。".format(
                    exit_code
                )
            )
            return
        raw = bytes(
            self.feature_process.readAllStandardOutput()
        ).decode("utf-8", "replace")
        self._feature_probe_active = False
        self._start_app_server(parse_feature_list(raw))

    def _feature_probe_failed(self, detail):
        if not self._feature_probe_active:
            return
        self._feature_probe_active = False
        self._feature_probe_generation += 1
        if self.feature_process.state() != QtCore.QProcess.NotRunning:
            self.feature_process.kill()
        error = CodexFeatureDiscoveryError(
            "{} 已停止启动，以免意外开放命令行等无关能力。".format(
                detail
            )
        )
        self.error.emit(str(error))
        self.stopped.emit()

    def _start_app_server(self, available_features):
        if self._closing:
            return
        program, arguments = process_invocation(
            self.executable,
            available_features,
        )
        self.process.setWorkingDirectory(self.runtime_directory)
        self.status.emit("正在启动 Codex 后台服务…")
        self.process.start(program, arguments)

    def _initialize(self):
        params = {
            "clientInfo": {
                "name": "pymol_codex",
                "title": "PyMOL Codex 助手",
                "version": __version__,
            },
            "capabilities": {"experimentalApi": True},
        }
        self.send_request("initialize", params, self._initialized)

    def _initialized(self, result, error):
        if error:
            self.error.emit(
                "Codex 初始化失败：{}".format(error_message(error))
            )
            return
        self.send_notification("initialized", {})
        try:
            self.refresh_models()
        except Exception:
            self.model_catalog_error.emit(
                "无法获取模型列表；可以继续使用 Codex 默认设置，"
                "稍后重试。"
            )
        self.new_thread()

    def new_thread(self):
        self._thread_generation += 1
        generation = self._thread_generation
        self.thread_id = None
        self.turn_id = None
        self._turn_active = False
        self._interrupt_pending = False
        self.status.emit("正在新建 Codex 对话…")
        self.send_request(
            "thread/start",
            {
                "cwd": self.runtime_directory,
                "sandbox": "read-only",
                "approvalPolicy": "on-request",
                "developerInstructions": DEVELOPER_INSTRUCTIONS,
                "dynamicTools": dynamic_tools(),
                "serviceName": "pymol_codex",
            },
            lambda result, error: self._thread_started(
                result, error, generation
            ),
        )

    def _thread_started(self, result, error, generation):
        if generation != self._thread_generation:
            return
        if error:
            self.error.emit(
                "无法创建 Codex 对话：{}".format(error_message(error))
            )
            return
        self._accept_thread(result)

    def _accept_thread(self, result):
        thread = (result or {}).get("thread") or {}
        self.thread_id = thread.get("id")
        if not self.thread_id:
            self.error.emit("Codex 没有返回对话 ID")
            return
        self.status.emit("就绪")
        self.ready.emit(self.thread_id)

    def start_turn(
        self,
        text,
        unrestricted_python_enabled=False,
        model="",
        effort="",
        service_tier="",
    ):
        if not self.thread_id:
            raise RuntimeError("Codex 对话尚未就绪")
        self.status.emit("Codex 正在处理…")
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
            self.status.emit("就绪")
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
            self.model_catalog_error.emit(
                "无法获取模型列表；可以继续使用 Codex 默认设置，"
                "稍后重试。"
            )
            return

        result = result if isinstance(result, dict) else {}
        data = result.get("data")
        if isinstance(data, list):
            models.extend(
                item for item in data if isinstance(item, dict)
            )

        cursor = result.get("nextCursor")
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
        if error:
            message = "无法发送消息：{}".format(error_message(error))
            self.turn_id = None
            self._turn_active = False
            self._interrupt_pending = False
            self.status.emit("就绪")
            self.error.emit(message)
            self.turn_failed.emit(message)
            return
        turn = (result or {}).get("turn") or {}
        self.turn_id = turn.get("id") or self.turn_id
        self._flush_pending_interrupt()

    def interrupt(self):
        if not self.thread_id:
            return False
        if not self.turn_id:
            self._interrupt_pending = True
            self.status.emit("停止请求已排队，等待 Codex 接收当前任务…")
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
                        "message": "等待 {} 响应超时".format(method),
                    },
                ),
            )
        return request_id

    def send_notification(self, method, params=None):
        self._write({"method": method, "params": params or {}})

    def _write(self, message):
        if self.process.state() == QtCore.QProcess.NotRunning:
            raise RuntimeError("Codex 后台服务未运行")
        if self.process.write(encode_message(message)) < 0:
            raise RuntimeError("无法向 Codex 后台服务发送数据")

    def _read_stdout(self):
        raw = self._stdout_decoder.decode(self.process.readAllStandardOutput())
        try:
            messages = self.buffer.feed(raw)
        except Exception as exc:
            self.error.emit("收到无效的 Codex 协议消息：{}".format(exc))
            return
        for error in self.buffer.pop_errors():
            self.error.emit("收到无效的 Codex 协议消息：{}".format(error))
        for message in messages:
            self._handle(message)

    def _read_stderr(self):
        raw = self._stderr_decoder.decode(self.process.readAllStandardError())
        raw = format_diagnostic(raw)
        # App Server may emit non-fatal loader warnings on stderr. Keep those
        # away from the primary status line; fatal process errors have their own
        # QProcess signals.
        if raw and ("ERROR" in raw.upper() or raw.lower().startswith("error:")):
            self.diagnostic.emit(raw[-1000:])

    def _handle(self, message):
        if "method" not in message and "id" in message:
            self.requests.resolve(message)
            return

        method = message.get("method", "")
        params = message.get("params") or {}
        if method == "item/tool/call" and "id" in message:
            self.tool_call.emit(message["id"], params)
            return
        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        } and "id" in message:
            # The PyMOL integration should use dynamic tools rather than shell/file edits.
            self.respond(message["id"], {"decision": "decline"})
            self.status.emit("已拒绝超出范围的文件系统或命令行请求")
            return
        if method == "item/permissions/requestApproval" and "id" in message:
            self.respond(message["id"], {"permissions": {}})
            self.status.emit("已拒绝超出范围的权限请求")
            return
        if method == "item/tool/requestUserInput" and "id" in message:
            if (
                params.get("threadId") != self.thread_id
                or params.get("turnId") != self.turn_id
            ):
                self.respond(message["id"], {"answers": {}})
                self.status.emit("已拒绝过期的 Codex 用户输入请求")
                return
            self.user_input.emit(message["id"], params)
            return
        if "id" in message:
            self.respond(
                message["id"],
                error={"code": -32601, "message": "Unsupported client request: " + method},
            )
            self.status.emit("不支持的 Codex 客户端请求：" + method)
            return
        notification_thread_id = params.get("threadId")
        if notification_thread_id and notification_thread_id != self.thread_id:
            return
        if method == "turn/started":
            self.turn_id = (params.get("turn") or {}).get("id") or self.turn_id
            self._flush_pending_interrupt()
        elif method == "turn/completed":
            self.turn_id = None
            self._turn_active = False
            self._interrupt_pending = False
            self.status.emit("就绪")
        elif method == "error":
            error = params.get("error") or params
            if error_will_retry(params):
                message = str(error.get("message") or "")
                if is_reconnect_notice(error):
                    progress = message.rsplit(" ", 1)[-1] if "/" in message else ""
                    suffix = "（{}）".format(progress) if progress else ""
                    self.status.emit("Codex 连接中断，正在重连{}…".format(suffix))
                else:
                    self.status.emit("Codex 遇到暂时性错误，正在重试…")
            else:
                failure = "Codex 错误：{}".format(
                    error_message(error)
                )
                had_active_turn = self._turn_active
                self.turn_id = None
                self._turn_active = False
                self._interrupt_pending = False
                self.error.emit(failure)
                if had_active_turn:
                    self.turn_failed.emit(failure)
        self.message.emit(message)

    def _process_error(self, _error):
        if self._closing:
            return
        self.error.emit("Codex 进程错误：{}".format(self.process.errorString()))

    def _process_finished(self, exit_code, _status):
        self.thread_id = None
        self.turn_id = None
        self._turn_active = False
        self._interrupt_pending = False
        if self._closing:
            self.requests.clear()
            return
        self.requests.fail_all(
            {"code": -32000, "message": "Codex App Server stopped"}
        )
        self.status.emit("Codex 已停止（退出码 {}）".format(exit_code))
        self.stopped.emit()

    def close(self):
        self._closing = True
        self._feature_probe_active = False
        self._feature_probe_generation += 1
        self.thread_id = None
        self.turn_id = None
        self._turn_active = False
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
