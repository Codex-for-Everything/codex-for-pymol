"""PyMOL plugin entry points for Codex for PyMOL."""

from .version import __version__

_dialog = None
_dock = None
_auto_open_pending = False
_auto_open_attempt = 0
_AUTO_OPEN_MAX_ATTEMPTS = 100
_AUTO_OPEN_RETRY_MS = 100


def _qt_main_window():
    try:
        from pymol.gui import get_qtwindow

        return get_qtwindow()
    except (ImportError, AttributeError):
        return None


def open_dialog():
    """Open Codex in PyMOL's bottom dock, with a dialog fallback."""
    global _dialog, _dock
    from .ui import CodexDialog

    main_window = _qt_main_window()
    can_dock = False
    if main_window is not None:
        from pymol.Qt import QtWidgets

        can_dock = isinstance(main_window, QtWidgets.QMainWindow)

    if can_dock:
        from .docking import create_codex_dock

        if _dock is None or _dock.parentWidget() is not main_window:
            _dock, _dialog = create_codex_dock(main_window)
        else:
            _dock.show()
            _dock.raise_()
        return _dialog

    if _dialog is None or _dock is not None:
        _dock = None
        _dialog = CodexDialog()
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog


def _auto_open_step():
    """Wait for PyMOL's console dock, then show Codex at startup."""
    global _auto_open_attempt, _auto_open_pending
    if _dialog is not None:
        _auto_open_pending = False
        return

    main_window = _qt_main_window()
    console_ready = False
    if main_window is not None:
        from pymol.Qt import QtWidgets
        from .docking import find_console_dock

        console_ready = (
            isinstance(main_window, QtWidgets.QMainWindow)
            and find_console_dock(main_window) is not None
        )

    if console_ready:
        _auto_open_pending = False
        open_dialog()
        return

    if _auto_open_attempt < _AUTO_OPEN_MAX_ATTEMPTS:
        from pymol.Qt import QtCore

        _auto_open_attempt += 1
        QtCore.QTimer.singleShot(_AUTO_OPEN_RETRY_MS, _auto_open_step)
        return

    # Older PyMOL builds may not expose the native console dock. Preserve the
    # existing standalone-dialog fallback after the bounded startup wait.
    _auto_open_pending = False
    open_dialog()


def _schedule_auto_open():
    global _auto_open_attempt, _auto_open_pending
    if _dialog is not None or _auto_open_pending:
        return
    from pymol.Qt import QtCore

    _auto_open_attempt = 0
    _auto_open_pending = True
    QtCore.QTimer.singleShot(0, _auto_open_step)


def __init_plugin__(app=None):
    """Register the plugin with PyMOL's Qt plugin manager."""
    from pymol import cmd
    from pymol.plugins import addmenuitemqt

    addmenuitemqt("Codex for PyMOL", open_dialog)
    cmd.extend("codex_chat", open_dialog)
    _schedule_auto_open()


__all__ = ["__init_plugin__", "__version__", "open_dialog"]
