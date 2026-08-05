"""Qt chat panel and dynamic tool dispatch."""

from collections import OrderedDict
import json
import os
import tempfile
from pathlib import Path

from pymol import cmd
import pymol
from pymol.Qt import QtCore, QtGui, QtWidgets

from .app_server import AppServerClient
from .audit import AuditLogger
from .discovery import find_codex, is_supported_launcher
from .executor import PyMOLExecutor, action_risk
from .i18n import EN, ZH_CN, get_locale, set_locale, text as tr
from .preferences import PreferenceStore
from .presentation import chat_block, chat_prefix, tool_display_name
from .protocol import (
    diagnostic_fingerprint,
    diagnostic_summary,
    is_active_tool_call,
)
from .serializer import to_jsonable


class MessageInput(QtWidgets.QPlainTextEdit):
    """Message editor with chat-style keyboard behavior."""

    send_requested = (
        QtCore.Signal() if hasattr(QtCore, "Signal") else QtCore.pyqtSignal()
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preedit_active = False

    def inputMethodEvent(self, event):
        self._preedit_active = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event):
        is_enter = event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter)
        modifiers = event.modifiers()
        if (
            is_enter
            and not self._preedit_active
            and modifiers in (QtCore.Qt.NoModifier, QtCore.Qt.KeypadModifier)
        ):
            event.accept()
            self.send_requested.emit()
            return
        if (
            is_enter
            and not self._preedit_active
            and modifiers
            in (
                QtCore.Qt.ControlModifier,
                QtCore.Qt.ShiftModifier,
                QtCore.Qt.ControlModifier | QtCore.Qt.KeypadModifier,
                QtCore.Qt.ShiftModifier | QtCore.Qt.KeypadModifier,
            )
        ):
            event.accept()
            self.insertPlainText("\n")
            return
        super().keyPressEvent(event)


class PythonApprovalDialog(QtWidgets.QDialog):
    """Approval dialog that keeps the complete code visibly reviewable."""

    def __init__(self, code, reason, parent=None):
        super().__init__(parent)
        self.setObjectName("codex_python_approval_dialog")
        self.setWindowTitle(tr("dialog.python.title"))
        self.resize(760, 620)
        layout = QtWidgets.QVBoxLayout(self)

        warning = QtWidgets.QLabel(tr("dialog.python.warning"))
        warning.setWordWrap(True)
        layout.addWidget(warning)
        reason_label = QtWidgets.QLabel(
            tr(
                "dialog.python.reason",
                reason=reason or tr("dialog.python.no_reason"),
            )
        )
        reason_label.setWordWrap(True)
        layout.addWidget(reason_label)

        code_view = QtWidgets.QPlainTextEdit()
        code_view.setReadOnly(True)
        code_view.setPlainText(code)
        code_view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        layout.addWidget(code_view, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Yes | QtWidgets.QDialogButtonBox.No
        )
        buttons.button(QtWidgets.QDialogButtonBox.Yes).setText(
            tr("button.execute_code")
        )
        buttons.button(QtWidgets.QDialogButtonBox.No).setText(
            tr("button.cancel")
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if parent is not None:
            self.apply_host_palette(parent.palette())

    def apply_host_palette(self, palette):
        """Use the same complete palette as the embedded PyMOL console."""
        palette = QtGui.QPalette(palette)
        self.setPalette(palette)
        foreground = palette.color(
            QtGui.QPalette.Active,
            QtGui.QPalette.WindowText,
        )
        self.setStyleSheet(
            "QDialog#codex_python_approval_dialog QLabel {{"
            "color: rgba({red}, {green}, {blue}, {alpha});"
            "background: transparent;"
            "}}".format(
                red=foreground.red(),
                green=foreground.green(),
                blue=foreground.blue(),
                alpha=foreground.alpha(),
            )
        )
        for widget in self.findChildren(QtWidgets.QWidget):
            widget.setPalette(palette)


def reasoning_effort_label(value):
    value = str(value or "")
    translated = tr("effort." + value) if value in {
        "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"
    } else ""
    return tr("effort.display", label=translated, value=value) if translated else value


class ModelSettingsDialog(QtWidgets.QDialog):
    """Model, reasoning, and service-tier settings from Codex's catalog."""

    refresh_requested = (
        QtCore.Signal() if hasattr(QtCore, "Signal") else QtCore.pyqtSignal()
    )

    def __init__(
        self,
        catalog,
        model="",
        effort="",
        service_tier="",
        catalog_error="",
        language=ZH_CN,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.setObjectName("codex_model_settings_dialog")
        self.resize(560, 230)
        self.setAutoFillBackground(True)
        self._catalog = []
        self._models_by_value = {}
        self._initial_settings = (
            str(model or ""),
            str(effort or ""),
            str(service_tier or ""),
        )

        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(tr("settings.intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QtWidgets.QFormLayout()
        self.language_combo = QtWidgets.QComboBox()
        self.language_combo.addItem(tr("language.chinese"), ZH_CN)
        self.language_combo.addItem(tr("language.english"), EN)
        language_index = self.language_combo.findData(language)
        self.language_combo.setCurrentIndex(max(0, language_index))
        form.addRow(tr("settings.language"), self.language_combo)

        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.model_combo.setMinimumContentsLength(20)
        form.addRow(tr("settings.model"), self.model_combo)

        self.effort_combo = QtWidgets.QComboBox()
        form.addRow(tr("settings.effort"), self.effort_combo)

        self.service_tier_combo = QtWidgets.QComboBox()
        form.addRow(tr("settings.speed"), self.service_tier_combo)
        layout.addLayout(form)

        self.details_label = QtWidgets.QLabel()
        self.details_label.setWordWrap(True)
        self.details_label.setTextFormat(QtCore.Qt.PlainText)
        self.details_label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
        )
        self.details_label.hide()
        layout.addWidget(self.details_label, 1)

        actions = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton(tr("settings.refresh"))
        self.refresh_button.setMinimumWidth(
            self.refresh_button.sizeHint().width()
        )
        self.refresh_button.clicked.connect(self._request_refresh)
        actions.addWidget(self.refresh_button)
        actions.addStretch(1)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save
            | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Save).setText(tr("button.save"))
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText(tr("button.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        actions.addWidget(buttons)
        layout.addLayout(actions)

        self.model_combo.currentIndexChanged.connect(
            self._model_selection_changed
        )
        if parent is not None:
            self.apply_host_palette(parent.palette())
        self.set_catalog(catalog, catalog_error)

    def apply_host_palette(self, palette):
        """Apply a complete host palette, including native macOS labels."""
        palette = QtGui.QPalette(palette)
        self.setPalette(palette)
        foreground = palette.color(
            QtGui.QPalette.Active,
            QtGui.QPalette.WindowText,
        )
        self.setStyleSheet(
            "QDialog#codex_model_settings_dialog QLabel {{"
            "color: rgba({red}, {green}, {blue}, {alpha});"
            "background: transparent;"
            "}}".format(
                red=foreground.red(),
                green=foreground.green(),
                blue=foreground.blue(),
                alpha=foreground.alpha(),
            )
        )
        for widget in self.findChildren(QtWidgets.QWidget):
            widget.setPalette(palette)

    def _request_refresh(self):
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText(tr("settings.refreshing"))
        self.refresh_requested.emit()

    def _set_status_text(self, text=""):
        self.details_label.setText(str(text or ""))
        self.details_label.setVisible(bool(text))

    def set_catalog(self, catalog, error=""):
        new_catalog = [
            item for item in (catalog or []) if isinstance(item, dict)
        ]
        catalog_changed = new_catalog != self._catalog
        if not catalog_changed:
            # Do not suspend and resume painting for the normal refresh case.
            # Re-enabling updates can itself trigger a full native-window
            # repaint on macOS even when none of the catalog controls changed.
            self.refresh_button.setText(tr("settings.refresh"))
            self.refresh_button.setEnabled(True)
            if error:
                self._set_status_text(error)
            elif not self._models_by_value:
                self._set_status_text(
                    tr("settings.catalog_unavailable")
                )
            else:
                self._set_status_text()
            return

        if self.model_combo.count():
            selected = self.current_settings()
        else:
            selected = self._initial_settings
        # Keep the last meaningful selection while a refresh temporarily has
        # no usable catalog. Saving a language-only change must not erase the
        # user's previously validated model preferences.
        self._initial_settings = selected

        # Rebuilding native combo boxes one item at a time makes a visible
        # modal dialog repaint and recalculate its layout repeatedly on macOS.
        # Skip identical catalogs and expose only the final state when a real
        # catalog change must be applied.
        self.setUpdatesEnabled(False)
        try:
            self._catalog = new_catalog
            self._models_by_value = {}
            self.model_combo.blockSignals(True)
            try:
                self.model_combo.clear()

                seen = set()
                default_model_index = -1
                for item in self._catalog:
                    value = str(item.get("model") or item.get("id") or "")
                    if not value or value in seen:
                        continue
                    seen.add(value)
                    self._models_by_value[value] = item
                    label = str(item.get("displayName") or value)[:120]
                    if item.get("isDefault"):
                        label += tr("settings.default_suffix")
                        if default_model_index < 0:
                            default_model_index = self.model_combo.count()
                    self.model_combo.addItem(label, value)

                model, effort, service_tier = selected
                index = self.model_combo.findData(model)
                if index < 0:
                    index = default_model_index
                if index < 0 and self.model_combo.count():
                    index = 0
                self.model_combo.setCurrentIndex(index)
                self.model_combo.setEnabled(
                    self.model_combo.count() > 0
                )
            finally:
                self.model_combo.blockSignals(False)
            self._populate_model_options(effort, service_tier)
            if self._models_by_value:
                self._initial_settings = (
                    str(self.model_combo.currentData() or ""),
                    str(self.effort_combo.currentData() or ""),
                    str(self.service_tier_combo.currentData() or ""),
                )

            self.refresh_button.setText(tr("settings.refresh"))
            self.refresh_button.setEnabled(True)
            if error:
                self._set_status_text(error)
            elif not self._models_by_value:
                self._set_status_text(
                    tr("settings.catalog_unavailable")
                )
            else:
                self._set_status_text()
        finally:
            self.setUpdatesEnabled(True)

    def _selected_model(self):
        value = str(self.model_combo.currentData() or "")
        return self._models_by_value.get(value)

    def _model_selection_changed(self, _index):
        self._populate_model_options("", "")

    def _populate_model_options(self, effort, service_tier):
        model = self._selected_model()
        default_effort = str(
            (model or {}).get("defaultReasoningEffort") or ""
        )

        self.effort_combo.blockSignals(True)
        self.effort_combo.clear()
        effort_index = -1
        default_effort_index = -1
        seen_efforts = set()
        for option in (model or {}).get("supportedReasoningEfforts") or []:
            if not isinstance(option, dict):
                continue
            value = str(option.get("reasoningEffort") or "")
            if not value or value in seen_efforts:
                continue
            seen_efforts.add(value)
            label = reasoning_effort_label(value)
            if value == default_effort:
                label += tr("settings.default_suffix")
                default_effort_index = self.effort_combo.count()
            self.effort_combo.addItem(label, value)
            if value == effort:
                effort_index = self.effort_combo.count() - 1
            description = str(option.get("description") or "")[:500]
            if description:
                self.effort_combo.setItemData(
                    self.effort_combo.count() - 1,
                    description,
                    QtCore.Qt.ToolTipRole,
                )
        if effort_index < 0:
            effort_index = default_effort_index
        if effort_index < 0 and self.effort_combo.count():
            effort_index = 0
        self.effort_combo.setCurrentIndex(effort_index)
        self.effort_combo.setEnabled(self.effort_combo.count() > 1)
        self.effort_combo.blockSignals(False)

        tiers = [
            tier
            for tier in ((model or {}).get("serviceTiers") or [])
            if isinstance(tier, dict) and tier.get("id")
        ]
        default_tier = str(
            (model or {}).get("defaultServiceTier") or ""
        )

        self.service_tier_combo.blockSignals(True)
        self.service_tier_combo.clear()
        tier_index = -1
        default_tier_index = -1
        seen_tiers = set()
        if not default_tier:
            # Current Codex catalogs represent baseline/standard speed by
            # omitting the serviceTier override. Only additional speed tiers
            # may therefore appear in serviceTiers.
            self.service_tier_combo.addItem(tr("settings.standard_default"), "")
            default_tier_index = 0
            if not service_tier:
                tier_index = 0
        for tier in tiers:
            value = str(tier.get("id"))
            if value in seen_tiers:
                continue
            seen_tiers.add(value)
            name = str(tier.get("name") or value)[:80]
            if value == default_tier:
                name += tr("settings.default_suffix")
                default_tier_index = self.service_tier_combo.count()
            self.service_tier_combo.addItem(name, value)
            if value == service_tier:
                tier_index = self.service_tier_combo.count() - 1
            description = str(tier.get("description") or "")[:500]
            if description:
                self.service_tier_combo.setItemData(
                    self.service_tier_combo.count() - 1,
                    description,
                    QtCore.Qt.ToolTipRole,
                )
        if tier_index < 0:
            tier_index = default_tier_index
        if tier_index < 0 and self.service_tier_combo.count():
            tier_index = 0
        self.service_tier_combo.setCurrentIndex(tier_index)
        self.service_tier_combo.setEnabled(
            self.service_tier_combo.count() > 1
        )
        self.service_tier_combo.blockSignals(False)

    def current_settings(self):
        if not self._models_by_value:
            return self._initial_settings
        return (
            str(self.model_combo.currentData() or ""),
            str(self.effort_combo.currentData() or ""),
            str(self.service_tier_combo.currentData() or ""),
        )

    def selected_language(self):
        return str(self.language_combo.currentData() or ZH_CN)


class CodexDialog(QtWidgets.QDialog):
    language_changed = (
        QtCore.Signal(str) if hasattr(QtCore, "Signal") else QtCore.pyqtSignal(str)
    )

    def __init__(self, parent=None):
        if parent is None:
            parent = QtWidgets.QApplication.activeWindow()
        super().__init__(parent)
        self.settings = QtCore.QSettings(
            "CodexForPyMOL",
            "CodexForPyMOL",
        )
        system_locale = QtCore.QLocale.system().name()
        self.preferences = PreferenceStore(self.settings, system_locale)
        set_locale(self.preferences.language())
        self.setWindowTitle(tr("app.window_title"))
        self.resize(720, 760)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setAutoFillBackground(True)
        self._runtime_temporary_directory = tempfile.TemporaryDirectory(
            prefix="codex-for-pymol-runtime-"
        )
        self.runtime_directory = Path(
            self._runtime_temporary_directory.name
        )
        if os.name != "nt":
            try:
                self.runtime_directory.chmod(0o700)
            except OSError:
                pass
        app_data = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.AppLocalDataLocation
        ) or tempfile.gettempdir()
        self.audit = AuditLogger(Path(app_data) / "codex-for-pymol" / "logs")
        self.executor = PyMOLExecutor(
            cmd,
            pymol_module=pymol,
            cache_directory=QtCore.QStandardPaths.writableLocation(
                QtCore.QStandardPaths.CacheLocation
            )
            or tempfile.gettempdir(),
            checkpoint_directory=(
                self.runtime_directory / "checkpoints"
            ),
        )
        self.client = None
        self.full_python_enabled = False
        self._assistant_streaming = False
        self._audit_warning_shown = False
        self._tool_response_cache = OrderedDict()
        self._last_diagnostic = None
        self._last_diagnostic_fingerprint = None
        self._displayed_diagnostic_fingerprint = None
        self._model_catalog = []
        self._model_catalog_validated = False
        self._model_catalog_error = ""
        self._model_catalog_error_key = ""
        self._model_settings_dialog = None
        self._codex_selector_retry = False
        self._turn_checkpoint_key = None
        self._turn_checkpoint_path = None
        self._ready = False

        self._build_ui()
        QtCore.QTimer.singleShot(0, self._connect_codex)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        # Match PyMOL's own bottom console container.  Its bottom_layout uses
        # a one-pixel inset and no gap around the feedback browser.
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        self.transcript = QtWidgets.QPlainTextEdit()
        self.transcript.setObjectName("codex_for_pymol_transcript")
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText(tr("transcript.placeholder"))
        self.transcript.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.transcript.setMinimumHeight(0)
        self.transcript.verticalScrollBar().setObjectName("pymol_scroll_bar")
        layout.addWidget(self.transcript, 1)

        self.footer_widget = QtWidgets.QWidget()
        self.footer_widget.setObjectName("codex_for_pymol_footer")
        self.footer_widget.setAutoFillBackground(True)
        self.footer_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed,
        )
        footer_layout = QtWidgets.QVBoxLayout(self.footer_widget)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(4)

        self.status_separator = QtWidgets.QFrame()
        self.status_separator.setObjectName("codex_for_pymol_status_separator")
        self.status_separator.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.status_separator.setFixedHeight(1)
        footer_layout.addWidget(self.status_separator)

        self.status_row = QtWidgets.QHBoxLayout()
        self.status_row.setSpacing(6)
        self.status_label = QtWidgets.QLabel(tr("status.disconnected"))
        self.status_label.setWordWrap(False)
        self.status_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed,
        )
        self.status_row.addWidget(self.status_label, 1)
        self.choose_button = QtWidgets.QPushButton(tr("button.select_codex"))
        self.choose_button.clicked.connect(self._choose_codex)
        self.status_row.addWidget(self.choose_button)
        footer_layout.addLayout(self.status_row)

        self.input = MessageInput()
        self.input.setObjectName("codex_for_pymol_input")
        self.input.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarAsNeeded
        )
        self.input.verticalScrollBar().setObjectName("pymol_scroll_bar")
        self.input.setPlaceholderText(tr("input.placeholder"))
        self._sync_input_height()
        self.input.send_requested.connect(self._send)
        footer_layout.addWidget(self.input)

        self.action_row = QtWidgets.QHBoxLayout()
        self.action_row.setContentsMargins(0, 0, 0, 0)
        self.action_row.setSpacing(6)
        self.send_button = QtWidgets.QPushButton(tr("button.send"))
        self.send_button.setDefault(True)
        self.send_button.clicked.connect(self._send)
        self.action_row.addWidget(self.send_button)
        self.stop_button = QtWidgets.QPushButton(tr("button.stop"))
        self.stop_button.clicked.connect(self._stop)
        self.action_row.addWidget(self.stop_button)
        self.new_button = QtWidgets.QPushButton(tr("button.new_chat"))
        self.new_button.clicked.connect(self._new_thread)
        self.action_row.addWidget(self.new_button)
        self.model_settings_button = QtWidgets.QPushButton(tr("button.settings"))
        self.model_settings_button.clicked.connect(
            self._open_model_settings
        )
        self.action_row.addWidget(self.model_settings_button)
        self.action_row.addStretch(1)
        self.python_checkbox = QtWidgets.QCheckBox(tr("python.enable"))
        self.python_checkbox.toggled.connect(self._toggle_python)
        self.action_row.addWidget(self.python_checkbox)
        self.undo_button = QtWidgets.QPushButton(tr("button.undo"))
        self.undo_button.setToolTip(tr("undo.tooltip"))
        self.undo_button.clicked.connect(
            self._undo_last_instruction
        )
        self.action_row.addWidget(self.undo_button)
        footer_layout.addLayout(self.action_row)
        layout.addWidget(self.footer_widget)
        self._sync_status_margins(
            self.transcript.document().documentMargin()
        )
        self._sync_status_separator()
        self.footer_widget.setFixedHeight(self.footer_widget.sizeHint().height())
        self._update_model_settings_button()
        self._set_ready(False)

    def _sync_input_height(self):
        input_height = (
            self.input.fontMetrics().lineSpacing() * 2
            + int(self.input.document().documentMargin() * 2)
            + self.input.frameWidth() * 2
            + 2
        )
        self.input.setFixedHeight(input_height)

    def _sync_status_margins(self, document_margin):
        text_inset = max(0, int(round(document_margin)))
        self.status_row.setContentsMargins(
            text_inset,
            0,
            text_inset,
            0,
        )

    def _sync_status_separator(self):
        foreground = self.palette().color(
            QtGui.QPalette.Active,
            QtGui.QPalette.WindowText,
        )
        self.status_separator.setStyleSheet(
            "QFrame#codex_for_pymol_status_separator {{"
            "border: 0;"
            "background-color: rgba({red}, {green}, {blue}, 72);"
            "}}".format(
                red=foreground.red(),
                green=foreground.green(),
                blue=foreground.blue(),
            )
        )

    def preferred_transcript_height(self, transcript_lines=4):
        """Return the editor height needed for the requested chat lines."""
        line_count = max(1, int(transcript_lines))
        return (
            self.transcript.fontMetrics().lineSpacing() * line_count
            + int(round(self.transcript.document().documentMargin() * 2))
            + self.transcript.frameWidth() * 2
        )

    def preferred_dock_height(self, transcript_lines=4):
        """Return a compact initial height with the requested chat lines."""
        margins = self.layout().contentsMargins()
        return (
            self.preferred_transcript_height(transcript_lines)
            + self.footer_widget.height()
            + margins.top()
            + margins.bottom()
        )

    def apply_console_appearance(self, source):
        """Mirror the visible text-area details of PyMOL's console."""
        if not isinstance(
            source,
            (QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit),
        ):
            return

        source_font = source.font()
        source_margin = source.document().documentMargin()
        source_scrollbar = source.verticalScrollBar()

        for editor in (self.transcript, self.input):
            editor.setFont(source_font)
            editor.document().setDocumentMargin(source_margin)
            scrollbar = editor.verticalScrollBar()
            scrollbar.setObjectName(
                source_scrollbar.objectName() or "pymol_scroll_bar"
            )
            scrollbar.setStyleSheet(source_scrollbar.styleSheet())
            scrollbar.setStyle(source_scrollbar.style())

        self._sync_status_margins(source_margin)
        self._sync_status_separator()
        self._sync_input_height()
        if self._model_settings_dialog is not None:
            self._model_settings_dialog.apply_host_palette(self.palette())
        footer_layout = self.footer_widget.layout()
        if footer_layout is not None:
            footer_layout.activate()
            self.footer_widget.setFixedHeight(footer_layout.sizeHint().height())

    def _configured_codex(self):
        configured = self.preferences.codex_executable()
        return find_codex(configured)

    def _connect_codex(self):
        # A new executable/process is a new trust boundary. Never carry the
        # high-risk in-process Python grant across that boundary.
        self.lock_unrestricted_python()
        executable = self._configured_codex()
        if not executable:
            self._set_codex_selector_visible(True)
            self.status_label.setText(tr("error.codex_not_found"))
            return
        self._set_codex_selector_visible(False)
        if self.client:
            self.client.close()
        self._tool_response_cache.clear()
        self._turn_checkpoint_key = None
        self._turn_checkpoint_path = None
        self._last_diagnostic = None
        self._last_diagnostic_fingerprint = None
        self._displayed_diagnostic_fingerprint = None
        self.client = AppServerClient(executable, self.runtime_directory, self)
        self.client.status.connect(self.status_label.setText)
        self.client.error.connect(self._show_error)
        self.client.diagnostic.connect(self._show_diagnostic)
        self.client.ready.connect(self._client_ready)
        self.client.message.connect(self._protocol_message)
        self.client.tool_call.connect(self._tool_call)
        self.client.user_input.connect(self._request_user_input)
        self.client.turn_failed.connect(self._turn_failed)
        self.client.stopped.connect(self._client_stopped)
        self.client.model_catalog.connect(self._set_model_catalog)
        self.client.model_catalog_error.connect(
            self._backend_model_catalog_failed
        )
        self._model_catalog = []
        self._model_catalog_validated = False
        self._model_catalog_error_key = "settings.fetching"
        self._model_catalog_error = tr("settings.fetching")
        self.client.start()

    def _choose_codex(self):
        if hasattr(QtWidgets.QFileDialog, "getOpenFileName"):
            file_filter = (
                tr("file.codex_filter_windows")
                if os.name == "nt"
                else tr("file.all")
            )
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                tr("file.codex_title"),
                str(Path.home()),
                file_filter,
            )
        else:
            path = ""
        if path:
            if not is_supported_launcher(path):
                self._show_error(
                    tr("error.invalid_windows_launcher")
                )
                return
            self.preferences.set_codex_executable(path)
            self._connect_codex()

    def _client_ready(self, thread_id):
        self._set_codex_selector_visible(False)
        self._set_ready(True)
        self._append_system(tr("system.connected"))

    def _set_codex_selector_visible(self, visible, retry=False):
        self._codex_selector_retry = bool(retry)
        self.choose_button.setText(
            tr("button.reselect_codex")
            if retry
            else tr("button.select_codex")
        )
        self.choose_button.setVisible(visible)

    def _set_ready(self, ready):
        self._ready = bool(ready)
        self.send_button.setEnabled(ready)
        self.stop_button.setEnabled(False)
        self.new_button.setEnabled(ready)
        self.model_settings_button.setEnabled(ready)
        self._update_undo_button()

    def _set_turn_active(self):
        self.send_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.new_button.setEnabled(False)
        self.model_settings_button.setEnabled(False)
        self.undo_button.setEnabled(False)

    def _finish_turn_ui(self):
        self._set_ready(
            bool(self.client is not None and self.client.thread_id)
        )

    def _send(self):
        text = self.input.toPlainText().strip()
        if (
            not text
            or not self.send_button.isEnabled()
            or not self.client
            or not self.client.thread_id
            or self.client.turn_id
        ):
            return
        try:
            model, effort, service_tier = self._effective_model_settings()
            self.client.start_turn(
                text,
                self.full_python_enabled,
                model,
                effort,
                service_tier,
            )
        except Exception as exc:
            self._show_error(str(exc))
            return
        self.input.clear()
        self._append_block(tr("role.user"), text)
        self._audit(
            "user_instruction",
            text=text,
            thread_id=self.client.thread_id,
        )
        self._assistant_streaming = False
        self._set_turn_active()

    def _stop(self):
        if not self.client:
            return
        try:
            requested = self.client.interrupt()
        except Exception as exc:
            self._show_error(tr("error.stop_turn", detail=exc))
            return
        if requested:
            self._append_system(
                tr("system.stop_requested")
            )

    def _new_thread(self):
        if not self.client:
            return
        try:
            if self.client.turn_id:
                self.client.interrupt()
            self.client.new_thread()
        except Exception as exc:
            self._set_ready(False)
            self._show_error(
                tr("backend.new_thread_failed", detail=exc)
            )
            return
        self._set_ready(False)
        self._tool_response_cache.clear()
        self._turn_checkpoint_key = None
        self._turn_checkpoint_path = None
        self.transcript.clear()

    def _saved_model_settings(self):
        return self.preferences.model_settings()

    def _save_model_settings(self, model, effort, service_tier):
        self.preferences.set_model_settings(model, effort, service_tier)
        self._update_model_settings_button()

    def _effective_model_settings(self):
        """Return overrides validated by this connection's live catalog."""
        if not self._model_catalog_validated or not self._model_catalog:
            return "", "", ""
        return self._saved_model_settings()

    def _set_model_catalog(self, catalog):
        self._model_catalog = [
            item for item in (catalog or []) if isinstance(item, dict)
        ]
        self._model_catalog_validated = True
        self._model_catalog_error = ""
        self._model_catalog_error_key = ""
        self._normalize_saved_model_settings()
        self._update_model_settings_button()
        if self._model_settings_dialog is not None:
            self._model_settings_dialog.set_catalog(
                self._model_catalog,
                "",
            )

    def _backend_model_catalog_failed(self, message):
        self._model_catalog_failed(message, "backend.model_failed")

    def _model_catalog_failed(self, message, translation_key=""):
        self._model_catalog_error = str(message)
        self._model_catalog_error_key = str(translation_key)
        if self._model_settings_dialog is not None:
            self._model_settings_dialog.set_catalog(
                self._model_catalog,
                self._model_catalog_error,
            )

    def _normalize_saved_model_settings(self):
        if not self._model_catalog:
            return
        model, effort, service_tier = self._saved_model_settings()
        by_value = {
            str(item.get("model") or item.get("id") or ""): item
            for item in self._model_catalog
        }
        selected = by_value.get(model) if model else next(
            (
                item
                for item in self._model_catalog
                if item.get("isDefault")
            ),
            None,
        )

        changed = False
        if model and selected is None:
            model = ""
            effort = ""
            service_tier = ""
            changed = True
        elif selected is not None:
            allowed_efforts = {
                str(option.get("reasoningEffort"))
                for option in (
                    selected.get("supportedReasoningEfforts") or []
                )
                if isinstance(option, dict)
                and option.get("reasoningEffort")
            }
            allowed_tiers = {
                str(tier.get("id"))
                for tier in (selected.get("serviceTiers") or [])
                if isinstance(tier, dict) and tier.get("id")
            }
            if effort and effort not in allowed_efforts:
                effort = ""
                changed = True
            if service_tier and service_tier not in allowed_tiers:
                service_tier = ""
                changed = True
        if changed:
            self._save_model_settings(model, effort, service_tier)
            self._append_system(tr("system.model_reset"))

    def _refresh_model_catalog(self):
        if self.client is None:
            self._model_catalog_failed(
                tr("settings.not_connected"),
                "settings.not_connected",
            )
            return
        try:
            self.client.refresh_models()
        except Exception:
            self._model_catalog_failed(
                tr("settings.refresh_failed"),
                "settings.refresh_failed",
            )

    def _open_model_settings(self):
        model, effort, service_tier = self._saved_model_settings()
        dialog = ModelSettingsDialog(
            self._model_catalog,
            model,
            effort,
            service_tier,
            self._model_catalog_error,
            get_locale(),
            self,
        )
        dialog.refresh_requested.connect(self._refresh_model_catalog)
        self._model_settings_dialog = dialog
        try:
            if dialog.exec_() == QtWidgets.QDialog.Accepted:
                model, effort, service_tier = dialog.current_settings()
                language = self.preferences.set_language(
                    dialog.selected_language()
                )
                language_changed = language != get_locale()
                set_locale(language)
                self._save_model_settings(
                    model,
                    effort,
                    service_tier,
                )
                if language_changed:
                    self._retranslate_ui()
                    self.language_changed.emit(tr("app.dock_title"))
                self.status_label.setText(tr("settings.saved"))
        finally:
            self._model_settings_dialog = None
            dialog.deleteLater()

    def _update_model_settings_button(self):
        model, effort, service_tier = self._saved_model_settings()
        model_name = tr("settings.codex_default")
        tier_name = service_tier or tr("settings.standard_default")
        for item in self._model_catalog:
            value = str(item.get("model") or item.get("id") or "")
            if model and value == model:
                model_name = str(item.get("displayName") or model)[:120]
            elif not model and item.get("isDefault"):
                default_name = str(
                    item.get("displayName") or value
                )[:120]
                if default_name:
                    model_name = tr(
                        "settings.codex_default_named", name=default_name
                    )
            selected_model = (
                value == model
                if model
                else bool(item.get("isDefault"))
            )
            if selected_model and service_tier:
                tier_name = next(
                    (
                        str(tier.get("name") or service_tier)
                        for tier in (item.get("serviceTiers") or [])
                        if isinstance(tier, dict)
                        and str(tier.get("id")) == service_tier
                    ),
                    service_tier,
                )[:80]
        effort_name = (
            reasoning_effort_label(effort)
            if effort
            else tr("settings.model_default")
        )
        self.model_settings_button.setToolTip(
            tr(
                "settings.tooltip",
                model=model_name,
                effort=effort_name,
                speed=tier_name,
            )
        )

    def _retranslate_ui(self):
        """Refresh every persistent control after a language change."""
        if self._model_catalog_error_key:
            self._model_catalog_error = tr(
                self._model_catalog_error_key
            )
        self.setWindowTitle(tr("app.window_title"))
        self.transcript.setPlaceholderText(tr("transcript.placeholder"))
        self.input.setPlaceholderText(tr("input.placeholder"))
        self.send_button.setText(tr("button.send"))
        self.stop_button.setText(tr("button.stop"))
        self.new_button.setText(tr("button.new_chat"))
        self.model_settings_button.setText(tr("button.settings"))
        self.python_checkbox.setText(tr("python.enable"))
        self.undo_button.setText(tr("button.undo"))
        self.undo_button.setToolTip(tr("undo.tooltip"))
        self.status_label.setText(
            tr("status.ready") if self._ready else tr("status.disconnected")
        )
        self._set_codex_selector_visible(
            not self.choose_button.isHidden(),
            retry=self._codex_selector_retry,
        )
        self._update_model_settings_button()

    def _protocol_message(self, message):
        method = message.get("method")
        params = message.get("params") or {}
        if method == "item/agentMessage/delta":
            delta = params.get("delta", "")
            if delta:
                if not self._assistant_streaming:
                    self._append_transcript_block(chat_prefix("Codex"))
                    self._assistant_streaming = True
                cursor = self.transcript.textCursor()
                cursor.movePosition(cursor.End)
                cursor.insertText(delta)
                self.transcript.setTextCursor(cursor)
                self.transcript.ensureCursorVisible()
        elif method == "turn/completed":
            self._assistant_streaming = False
            self._finish_turn_ui()
        elif method == "item/started":
            item = params.get("item") or {}
            if item.get("type") == "dynamicToolCall":
                tool = item.get("tool")
                if (
                    tool == "pymol_python_exec"
                    and not self.full_python_enabled
                ):
                    return
                self._append_system(
                    tr("tool.running", tool=tool_display_name(tool))
                )

    def _tool_call(self, request_id, params):
        tool = params.get("tool")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        call_id = params.get("callId")
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")

        active_thread = self.client.thread_id if self.client else None
        active_turn = self.client.turn_id if self.client else None
        if not is_active_tool_call(params, active_thread, active_turn):
            response = self._tool_response(
                False,
                {
                    "error": (
                        "Rejected a tool call with missing or inactive "
                        "conversation identity"
                    ),
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                },
            )
            self._audit(
                "invalid_tool_call_rejected",
                call_id=call_id,
                tool=tool,
                thread_id=thread_id,
                turn_id=turn_id,
            )
            self._respond_to_tool(request_id, response)
            return

        cache_key = (thread_id, turn_id, call_id)
        if cache_key in self._tool_response_cache:
            response = self._tool_response_cache[cache_key]
            self._tool_response_cache.move_to_end(cache_key)
            self._audit(
                "tool_call_replayed",
                call_id=call_id,
                tool=tool,
                thread_id=thread_id,
                turn_id=turn_id,
            )
            self._respond_to_tool(request_id, response)
            return

        self._audit(
            "tool_call",
            call_id=call_id,
            tool=tool,
            arguments=arguments,
            thread_id=thread_id,
            turn_id=turn_id,
        )
        python_blocked = (
            tool == "pymol_python_exec"
            and not self.full_python_enabled
        )
        try:
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be a JSON object")
            if tool == "pymol_inspect":
                result = self.executor.inspect(arguments)
                response = self._tool_response(True, result)
            elif tool == "pymol_apply":
                operations = arguments.get("operations") or []
                risk = action_risk(operations)
                if risk and not self._approve_risky_action(risk, operations):
                    self._audit(
                        "controlled_action_approval",
                        call_id=call_id,
                        risk=risk,
                        approved=False,
                    )
                    response = self._tool_response(False, {"error": "User declined"})
                else:
                    if risk:
                        self._audit(
                            "controlled_action_approval",
                            call_id=call_id,
                            risk=risk,
                            approved=True,
                        )
                    result = self.executor.apply(
                        arguments,
                        before_execute=lambda: self._ensure_turn_checkpoint(
                            thread_id,
                            turn_id,
                        ),
                    )
                    response = self._tool_response(bool(result.get("ok")), result)
                    if result.get("ok") and arguments.get("include_snapshot", True):
                        try:
                            snapshot = self.executor.snapshot({})
                            response["contentItems"].append(
                                {
                                    "type": "inputImage",
                                    "imageUrl": snapshot["image_url"],
                                }
                            )
                        except Exception as exc:
                            warning = {
                                "warning": "PyMOL changes succeeded, but the snapshot failed",
                                "snapshot_error": "{}: {}".format(
                                    type(exc).__name__, exc
                                ),
                            }
                            response["contentItems"].append(
                                {
                                    "type": "inputText",
                                    "text": json.dumps(
                                        warning,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    ),
                                }
                            )
            elif tool == "pymol_snapshot":
                snapshot = self.executor.snapshot(arguments)
                response = self._tool_response(
                    True,
                    {
                        "width": snapshot["width"],
                        "height": snapshot["height"],
                        "ray": snapshot["ray"],
                        "scene_revision": self.executor.scene_revision,
                    },
                )
                response["contentItems"].append(
                    {"type": "inputImage", "imageUrl": snapshot["image_url"]}
                )
            elif tool == "pymol_python_exec":
                response = self._handle_python(
                    arguments,
                    call_id,
                    thread_id,
                    turn_id,
                )
            else:
                response = self._tool_response(
                    False, {"error": "Unknown PyMOL tool: {}".format(tool)}
                )
        except BaseException as exc:
            response = self._tool_response(
                False,
                {"error": "{}: {}".format(type(exc).__name__, exc)},
            )

        self._audit(
            "tool_result",
            call_id=call_id,
            tool=tool,
            success=response.get("success"),
            content=to_jsonable(response.get("contentItems"), max_string=10000),
        )
        self._cache_tool_response(cache_key, response)
        self._respond_to_tool(request_id, response)
        if python_blocked:
            self._stop_for_disabled_python(arguments, call_id)

    def _respond_to_tool(self, request_id, response):
        try:
            self.client.respond(request_id, response)
        except Exception as exc:
            self._show_error(tr("error.return_tool_result", detail=exc))

    def _cache_tool_response(self, key, response):
        self._tool_response_cache[key] = response
        self._tool_response_cache.move_to_end(key)
        while len(self._tool_response_cache) > 8:
            self._tool_response_cache.popitem(last=False)

    @staticmethod
    def _tool_response(success, result):
        text = json.dumps(to_jsonable(result), ensure_ascii=False, separators=(",", ":"))
        return {
            "success": bool(success),
            "contentItems": [{"type": "inputText", "text": text}],
        }

    def _ensure_turn_checkpoint(self, thread_id, turn_id):
        key = (thread_id, turn_id)
        if (
            self._turn_checkpoint_key == key
            and self._turn_checkpoint_path
            and Path(self._turn_checkpoint_path).is_file()
        ):
            return self._turn_checkpoint_path
        path = self.executor.checkpoints.create(
            "instruction-{}".format(turn_id)
        )
        self._turn_checkpoint_key = key
        self._turn_checkpoint_path = path
        self._audit(
            "instruction_checkpoint_created",
            thread_id=thread_id,
            turn_id=turn_id,
            path=path,
        )
        return path

    def _handle_python(
        self,
        arguments,
        call_id,
        thread_id,
        turn_id,
    ):
        if not self.full_python_enabled:
            return self._tool_response(
                False,
                {
                    "error": "Unrestricted Python is disabled.",
                    "error_code": "unrestricted_python_disabled",
                    "requires_user_action": True,
                    "required_action": tr("python.required_action"),
                    "turn_will_stop": True,
                },
            )
        code = str(arguments.get("code", ""))
        reason = str(arguments.get("reason", ""))
        dialog = PythonApprovalDialog(code, reason, self)
        approved = dialog.exec_() == QtWidgets.QDialog.Accepted
        self._audit(
            "python_execution_approval",
            call_id=call_id,
            approved=approved,
            reason=reason,
        )
        if not approved:
            return self._tool_response(False, {"error": "User declined Python execution"})
        checkpoint = self._ensure_turn_checkpoint(
            thread_id,
            turn_id,
        )
        result = self.executor.execute_python(
            code,
            call_id,
            checkpoint=checkpoint,
        )
        return self._tool_response(bool(result.get("ok")), result)

    def _stop_for_disabled_python(self, arguments, call_id):
        reason = ""
        if isinstance(arguments, dict):
            reason = " ".join(str(arguments.get("reason") or "").split())
            reason = reason[:300]

        message = tr("system.python_blocked")
        if reason:
            message += tr("system.python_reason", reason=reason)
        self._append_system(message)
        self.status_label.setText(tr("status.python_stopping"))

        stop_requested = False
        try:
            stop_requested = bool(
                self.client and self.client.interrupt()
            )
        except Exception as exc:
            self._show_error(tr("error.stop_turn", detail=exc))
        self._audit(
            "unrestricted_python_blocked",
            call_id=call_id,
            reason=reason,
            stop_requested=stop_requested,
        )

    def _approve_risky_action(self, risk, operations):
        message = QtWidgets.QMessageBox(self)
        message.setIcon(QtWidgets.QMessageBox.Warning)
        message.setWindowTitle(tr("dialog.external.title"))
        message.setText(tr("dialog.external.request", risk=risk))
        message.setInformativeText(tr("dialog.external.detail"))
        message.setDetailedText(json.dumps(operations, ensure_ascii=False, indent=2))
        message.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        message.setDefaultButton(QtWidgets.QMessageBox.No)
        message.button(QtWidgets.QMessageBox.Yes).setText(tr("button.allow"))
        message.button(QtWidgets.QMessageBox.No).setText(tr("button.deny"))
        return message.exec_() == QtWidgets.QMessageBox.Yes

    def _request_user_input(self, request_id, params):
        answers = {}
        cancelled = False
        questions = params.get("questions") or []
        if not isinstance(questions, list):
            questions = []
        for question in questions[:3]:
            if not isinstance(question, dict):
                continue
            question_id = question.get("id")
            if not isinstance(question_id, str) or not question_id:
                continue
            prompt = str(question.get("question") or question.get("prompt") or "")
            options = question.get("options") or []
            if isinstance(options, list) and options:
                lines = []
                for option in options[:20]:
                    if isinstance(option, dict):
                        label = str(option.get("label", ""))
                        description = str(option.get("description", ""))
                        lines.append(
                            "- {}{}".format(
                                label,
                                ": " + description if description else "",
                            )
                        )
                    else:
                        lines.append("- " + str(option))
                prompt += "\n\n" + tr("input.options") + "\n" + "\n".join(lines)
            if question.get("isSecret"):
                prompt += "\n\n" + tr("input.secret_warning")
            dialog = QtWidgets.QInputDialog(self)
            dialog.setWindowTitle(
                str(question.get("header") or tr("input.more_info"))[:100]
            )
            dialog.setLabelText(prompt[:4000])
            dialog.setInputMode(QtWidgets.QInputDialog.TextInput)
            if question.get("isSecret"):
                dialog.setTextEchoMode(QtWidgets.QLineEdit.Password)
            dialog.setOkButtonText(tr("button.ok"))
            dialog.setCancelButtonText(tr("button.cancel"))
            accepted = dialog.exec_() == QtWidgets.QDialog.Accepted
            value = dialog.textValue()
            if not accepted:
                cancelled = True
                answers[question_id] = {"answers": []}
                break
            answers[question_id] = {"answers": [str(value)]}

        for question in questions[3:]:
            if not isinstance(question, dict):
                continue
            question_id = question.get("id")
            if isinstance(question_id, str) and question_id:
                answers[question_id] = {"answers": []}

        self._audit(
            "user_input_response",
            request_id=request_id,
            cancelled=cancelled,
            question_ids=list(answers),
        )
        try:
            self.client.respond(request_id, {"answers": answers})
        except Exception as exc:
            self._show_error(tr("error.return_user_input", detail=exc))

    def _toggle_python(self, checked):
        if checked:
            approved = self._confirm(
                tr("python.confirm_title"),
                tr("python.confirm_text"),
                accept_text=tr("button.enable"),
            )
            if not approved:
                self.python_checkbox.blockSignals(True)
                self.python_checkbox.setChecked(False)
                self.python_checkbox.blockSignals(False)
                self.full_python_enabled = False
                return
        self.full_python_enabled = checked
        self._audit("unrestricted_python_mode", enabled=checked)

    def _has_undo_checkpoint(self):
        checkpoints = getattr(self.executor, "checkpoints", None)
        has_checkpoint = getattr(checkpoints, "has_checkpoint", None)
        if not callable(has_checkpoint):
            return False
        try:
            return bool(has_checkpoint())
        except OSError:
            return False

    def _update_undo_button(self):
        self.undo_button.setEnabled(
            not self.stop_button.isEnabled()
            and self._has_undo_checkpoint()
        )

    def _undo_last_instruction(self):
        approved = self._confirm(
            tr("undo.confirm_title"),
            tr("undo.confirm_text"),
            accept_text=tr("button.undo_changes"),
        )
        if not approved:
            return
        try:
            path = self.executor.checkpoints.undo_last()
            self.executor.scene_revision += 1
            self._turn_checkpoint_key = None
            self._turn_checkpoint_path = None
            self._append_system(tr("system.undo_done"))
            self._audit("instruction_changes_undone", path=path)
        except Exception as exc:
            self._show_error(str(exc))
        finally:
            self._update_undo_button()

    def _audit(self, event, **fields):
        if self.audit.write(event, **fields):
            return
        if not self._audit_warning_shown:
            self._audit_warning_shown = True
            self._append_system(
                tr(
                    "error.audit_unavailable",
                    detail=self.audit.last_error or tr("error.unknown"),
                )
            )

    def _confirm(self, title, text, accept_text=None):
        message = QtWidgets.QMessageBox(self)
        message.setIcon(QtWidgets.QMessageBox.Warning)
        message.setWindowTitle(title)
        message.setText(text)
        message.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        message.setDefaultButton(QtWidgets.QMessageBox.No)
        message.button(QtWidgets.QMessageBox.Yes).setText(
            accept_text or tr("button.confirm")
        )
        message.button(QtWidgets.QMessageBox.No).setText(tr("button.cancel"))
        return message.exec_() == QtWidgets.QMessageBox.Yes

    def _turn_failed(self, _message):
        self._assistant_streaming = False
        self._finish_turn_ui()

    def _client_stopped(self):
        self._assistant_streaming = False
        self.lock_unrestricted_python()
        self._set_ready(False)
        self._set_codex_selector_visible(True, retry=True)
        self._append_pending_diagnostic()

    def _append_block(self, role, text):
        self._append_transcript_block(chat_block(role, text))

    def _append_transcript_block(self, text):
        """Append one block, inserting a separator only when it is needed."""
        cursor = self.transcript.textCursor()
        cursor.movePosition(cursor.End)
        document = self.transcript.document()
        if not document.isEmpty():
            previous = QtGui.QTextCursor(cursor)
            previous.movePosition(
                previous.PreviousCharacter,
                previous.KeepAnchor,
            )
            if previous.selectedText() not in {"\n", "\u2029"}:
                cursor.insertText("\n")
        cursor.insertText(str(text))
        self.transcript.setTextCursor(cursor)
        self.transcript.ensureCursorVisible()

    def _append_system(self, text):
        self._append_transcript_block("[{}] ".format(text))

    def _show_error(self, text):
        self.status_label.setText(text)
        self._append_system(tr("error.prefix", detail=text))
        if self.client is not None and not self.client.thread_id:
            self._set_ready(False)
            self._set_codex_selector_visible(True, retry=True)
            self._append_pending_diagnostic()

    def _show_diagnostic(self, text):
        fingerprint = diagnostic_fingerprint(text)
        if not fingerprint or fingerprint == self._last_diagnostic_fingerprint:
            return
        self._last_diagnostic = text
        self._last_diagnostic_fingerprint = fingerprint

    def _append_pending_diagnostic(self):
        if (
            not self._last_diagnostic
            or self._last_diagnostic_fingerprint
            == self._displayed_diagnostic_fingerprint
        ):
            return
        self._append_system(
            tr(
                "diagnostic.startup",
                detail=diagnostic_summary(self._last_diagnostic),
            )
        )
        self._displayed_diagnostic_fingerprint = self._last_diagnostic_fingerprint

    def lock_unrestricted_python(self):
        """Disable the session-scoped high-risk execution mode."""
        was_enabled = self.full_python_enabled
        self.full_python_enabled = False
        self.python_checkbox.blockSignals(True)
        self.python_checkbox.setChecked(False)
        self.python_checkbox.blockSignals(False)
        if was_enabled:
            self._audit("unrestricted_python_mode", enabled=False)

    def shutdown(self):
        """Stop session-scoped capabilities and the Codex child process."""
        self.lock_unrestricted_python()
        theme_follower = getattr(self, "_theme_follower", None)
        if theme_follower is not None:
            theme_follower.stop()
        if self.client:
            self.client.close()

    def closeEvent(self, event):
        self.shutdown()
        event.accept()

    def reject(self):
        """Keep Escape from hiding the persistent main plugin panel.

        ``QDialog`` maps Escape to ``reject()`` even after the dialog has been
        embedded as a dock widget. Actual approval and settings dialogs retain
        the normal QDialog Escape behavior.
        """
        return None

    def hideEvent(self, event):
        self.lock_unrestricted_python()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if (
            self.client is not None
            and self.client.process.state() == QtCore.QProcess.NotRunning
        ):
            QtCore.QTimer.singleShot(0, self._connect_codex)
