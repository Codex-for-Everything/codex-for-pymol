"""Integration with PyMOL's Qt main-window docking area."""

from pymol.Qt import QtCore, QtGui, QtWidgets

from .ui import CodexDialog


DOCK_OBJECT_NAME = "pymol_codex_dock"


def find_console_theme_source(main_window, console_dock=None):
    """Find the console widget that carries PyMOL's active text palette."""
    feedback = main_window.findChild(QtWidgets.QWidget, "feedback_browser")
    if feedback is not None:
        return feedback
    if console_dock is not None:
        widget = console_dock.widget()
        if isinstance(widget, QtWidgets.QPlainTextEdit):
            return widget
        if widget is not None:
            editors = widget.findChildren(QtWidgets.QPlainTextEdit)
            if editors:
                return editors[0]
            return widget
    return main_window


def console_palette(source):
    """Build a complete widget palette from the console's base/text colors."""
    source_palette = source.palette()
    palette = QtGui.QPalette(source_palette)
    groups = (
        QtGui.QPalette.Active,
        QtGui.QPalette.Inactive,
        QtGui.QPalette.Disabled,
    )
    background_roles = (
        QtGui.QPalette.Window,
        QtGui.QPalette.Base,
        QtGui.QPalette.AlternateBase,
        QtGui.QPalette.Button,
        QtGui.QPalette.ToolTipBase,
    )
    foreground_roles = (
        QtGui.QPalette.WindowText,
        QtGui.QPalette.Text,
        QtGui.QPalette.ButtonText,
        QtGui.QPalette.ToolTipText,
    )
    for group in groups:
        background = source_palette.color(group, QtGui.QPalette.Base)
        foreground = source_palette.color(group, QtGui.QPalette.Text)
        for role in background_roles:
            palette.setColor(group, role, background)
        for role in foreground_roles:
            palette.setColor(group, role, foreground)
        if hasattr(QtGui.QPalette, "PlaceholderText"):
            placeholder = QtGui.QColor(foreground)
            placeholder.setAlphaF(0.6)
            palette.setColor(group, QtGui.QPalette.PlaceholderText, placeholder)
    return palette


class ConsoleThemeFollower(QtCore.QObject):
    """Keep plugin widgets synchronized with PyMOL's console palette."""

    def __init__(self, source, target, main_window, parent=None):
        super().__init__(parent)
        self.source = source
        self.target = target
        self._active = True
        self._pending = False
        self._event_types = {
            QtCore.QEvent.PaletteChange,
            QtCore.QEvent.StyleChange,
            QtCore.QEvent.FontChange,
        }
        for name in ("ApplicationPaletteChange", "ThemeChange"):
            event_type = getattr(QtCore.QEvent, name, None)
            if event_type is not None:
                self._event_types.add(event_type)
        self._watched = [source, main_window]
        vertical_scrollbar = getattr(source, "verticalScrollBar", None)
        if vertical_scrollbar is not None:
            scrollbar = vertical_scrollbar()
            if scrollbar is not None:
                self._watched.append(scrollbar)
        application = QtWidgets.QApplication.instance()
        if application is not None:
            self._watched.append(application)
        for watched in self._watched:
            watched.installEventFilter(self)
        self.sync()

    def eventFilter(self, watched, event):
        if (
            self._active
            and watched in self._watched
            and event.type() in self._event_types
        ):
            if not self._pending:
                self._pending = True
                QtCore.QTimer.singleShot(0, self._deferred_sync)
        return False

    def _deferred_sync(self):
        self._pending = False
        if self._active:
            self.sync()

    def sync(self):
        if not self._active:
            return
        palette = console_palette(self.source)
        self.target.setPalette(palette)
        for widget in self.target.findChildren(QtWidgets.QWidget):
            widget.setPalette(palette)
        apply_appearance = getattr(
            self.target, "apply_console_appearance", None
        )
        if apply_appearance is not None:
            apply_appearance(self.source)

    def stop(self):
        if not self._active:
            return
        self._active = False
        self._pending = False
        for watched in self._watched:
            try:
                watched.removeEventFilter(self)
            except RuntimeError:
                pass
        self._watched = []


def find_console_dock(main_window):
    """Find PyMOL's bottom console dock across supported Qt GUI versions."""
    candidate = getattr(main_window, "dockWidget", None)
    if isinstance(candidate, QtWidgets.QDockWidget):
        return candidate

    feedback = main_window.findChild(QtWidgets.QWidget, "feedback_browser")
    current = feedback
    while current is not None:
        if isinstance(current, QtWidgets.QDockWidget):
            return current
        current = current.parentWidget()
    return None


def create_codex_dock(main_window, dialog_class=CodexDialog):
    """Create and select a Codex dock tab in PyMOL's bottom console area."""
    existing = main_window.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)
    if existing is not None:
        existing.show()
        existing.raise_()
        return existing, existing.widget()

    dock = QtWidgets.QDockWidget("Codex 助手", main_window)
    dock.setObjectName(DOCK_OBJECT_NAME)
    dock.setAllowedAreas(QtCore.Qt.BottomDockWidgetArea)
    dock.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
    hidden_title_bar = QtWidgets.QWidget(dock)
    hidden_title_bar.setObjectName("pymol_codex_hidden_title_bar")
    hidden_title_bar.setFixedHeight(0)
    dock.setTitleBarWidget(hidden_title_bar)

    dialog = dialog_class(dock)
    dialog.setWindowFlags(QtCore.Qt.Widget)
    dialog.setSizePolicy(
        QtWidgets.QSizePolicy.Expanding,
        QtWidgets.QSizePolicy.Expanding,
    )
    dock.setWidget(dialog)

    def lock_python_when_hidden(visible):
        if not visible:
            dialog.lock_unrestricted_python()

    dock.visibilityChanged.connect(lock_python_when_hidden)
    main_window.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)

    console_dock = find_console_dock(main_window)
    if console_dock is not None and console_dock is not dock:
        console_dock.setWindowTitle("PyMOL 控制台")
        console_dock.show()
        main_window.tabifyDockWidget(console_dock, dock)
        if hasattr(main_window, "setTabPosition"):
            main_window.setTabPosition(
                QtCore.Qt.BottomDockWidgetArea,
                QtWidgets.QTabWidget.North,
            )

    dock.show()
    dock.raise_()

    theme_source = find_console_theme_source(main_window, console_dock)
    dialog._theme_follower = ConsoleThemeFollower(
        theme_source,
        dialog,
        main_window,
        parent=dialog,
    )
    if hasattr(main_window, "resizeDocks"):
        preferred_height = dialog.preferred_dock_height(4)
        dialog.transcript.setFixedHeight(
            dialog.preferred_transcript_height(4)
        )
        dock.setFixedHeight(preferred_height)
        main_window.resizeDocks(
            [dock],
            [preferred_height],
            QtCore.Qt.Vertical,
        )

        def release_initial_height():
            try:
                dialog.transcript.setMinimumHeight(0)
                dialog.transcript.setMaximumHeight(16777215)
                dock.setMinimumHeight(0)
                dock.setMaximumHeight(16777215)
            except RuntimeError:
                # The application may close during the short startup timer.
                return

        QtCore.QTimer.singleShot(100, release_initial_height)

    application = QtWidgets.QApplication.instance()
    if application is not None:
        application.aboutToQuit.connect(dialog.shutdown)
    return dock, dialog
