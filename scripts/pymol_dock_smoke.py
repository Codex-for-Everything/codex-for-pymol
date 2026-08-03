"""Smoke-test docking against a running real PyMOL Qt main window."""

import threading
import time
import sys
import traceback

from pymol import cmd, gui
from pymol.Qt import QtCore, QtGui, QtWidgets
from pymol.Qt.utils import MainThreadCaller

import codex_for_pymol
from codex_for_pymol import docking, ui


COMPLETION = threading.Event()
RESULT = {"error": None}


class NullAuditLogger:
    last_error = None

    def __init__(self, _directory):
        pass

    def write(self, _event, **_fields):
        return True


class NullExecutor:
    def __init__(self, *_args, **_kwargs):
        pass


class TestCodexDialog(ui.CodexDialog):
    def _connect_codex(self):
        pass


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def log(message):
    print(message, file=sys.__stdout__, flush=True)


def run_test():
    try:
        main_window = gui.get_qtwindow()
        require(main_window is not None, "real PyMOL Qt main window was not found")

        ui.AuditLogger = NullAuditLogger
        ui.PyMOLExecutor = NullExecutor
        original_create = docking.create_codex_dock
        docking.create_codex_dock = lambda window: original_create(
            window,
            dialog_class=TestCodexDialog,
        )

        codex_for_pymol.__init_plugin__()
        QtWidgets.QApplication.processEvents()
        dialog = codex_for_pymol._dialog
        require(dialog is not None, "plugin did not open automatically at startup")
        dock = main_window.findChild(
            QtWidgets.QDockWidget,
            docking.DOCK_OBJECT_NAME,
        )
        console = docking.find_console_dock(main_window)
        require(dock is not None, "Codex dock was not created")
        require(console is not None, "real PyMOL console dock was not found")
        require(
            main_window.dockWidgetArea(dock) == QtCore.Qt.BottomDockWidgetArea,
            "Codex dock is not in the real bottom dock area",
        )
        require(
            dock in main_window.tabifiedDockWidgets(console),
            "Codex was not tabified with the real PyMOL console",
        )
        require(dock.isVisible(), "Codex dock is not visible")
        require(
            not (dock.features() & QtWidgets.QDockWidget.DockWidgetClosable),
            "real Codex dock still exposes a close button",
        )
        require(
            dock.titleBarWidget() is not None
            and dock.titleBarWidget().height() == 0,
            "real Codex dock title bar is still visible",
        )
        feedback = main_window.findChild(QtWidgets.QWidget, "feedback_browser")
        require(feedback is not None, "real PyMOL console theme source was not found")
        require(
            dialog.transcript.palette().color(QtGui.QPalette.Base)
            == feedback.palette().color(QtGui.QPalette.Base),
            "real Codex background does not match the PyMOL console",
        )
        require(
            dialog.transcript.palette().color(QtGui.QPalette.Text)
            == feedback.palette().color(QtGui.QPalette.Text),
            "real Codex text color does not match the PyMOL console",
        )
        require(
            dialog.autoFillBackground()
            and dialog.footer_widget.autoFillBackground(),
            "real Codex transparent containers do not paint their background",
        )
        require(
            dialog.footer_widget.palette().color(QtGui.QPalette.Window)
            == feedback.palette().color(QtGui.QPalette.Base),
            "real Codex footer background does not match the PyMOL console",
        )
        require(
            dialog.status_label.palette().color(QtGui.QPalette.WindowText)
            == feedback.palette().color(QtGui.QPalette.Text)
            and dialog.python_checkbox.palette().color(
                QtGui.QPalette.WindowText
            )
            == feedback.palette().color(QtGui.QPalette.Text),
            "real status or Python text color does not match the console",
        )
        require(
            dialog.transcript.frameShape() == QtWidgets.QFrame.NoFrame,
            "real Codex transcript still has a visible frame",
        )
        root_margins = dialog.layout().contentsMargins()
        require(
            (
                root_margins.left(),
                root_margins.top(),
                root_margins.right(),
                root_margins.bottom(),
            )
            == (1, 1, 1, 1)
            and dialog.layout().spacing() == 0,
            "real Codex layout does not match PyMOL's compact console layout",
        )
        require(
            dialog.transcript.font() == feedback.font()
            and dialog.input.font() == feedback.font(),
            "real Codex text widgets do not use the console font",
        )
        require(
            dialog.transcript.document().documentMargin()
            == feedback.document().documentMargin(),
            "real Codex transcript does not use the console text inset",
        )
        expected_text_inset = int(
            round(feedback.document().documentMargin())
        )
        status_margins = dialog.status_row.contentsMargins()
        require(
            (
                status_margins.left(),
                status_margins.top(),
                status_margins.right(),
                status_margins.bottom(),
            )
            == (expected_text_inset, 0, expected_text_inset, 0),
            "real status row does not align with the console text inset",
        )
        require(
            dialog.status_separator.height() == 1,
            "real status separator is not one pixel high",
        )
        console_scrollbar = feedback.verticalScrollBar()
        for editor in (dialog.transcript, dialog.input):
            scrollbar = editor.verticalScrollBar()
            require(
                scrollbar.objectName()
                == (console_scrollbar.objectName() or "pymol_scroll_bar"),
                "real Codex editor does not use the console scrollbar hook",
            )
            require(
                scrollbar.styleSheet() == console_scrollbar.styleSheet(),
                "real Codex scrollbar stylesheet does not match the console",
            )
        transcript_bottom = (
            dialog.transcript.mapTo(dialog, QtCore.QPoint(0, 0)).y()
            + dialog.transcript.height()
        )
        status_top = dialog.status_label.mapTo(
            dialog, QtCore.QPoint(0, 0)
        ).y()
        input_top = dialog.input.mapTo(dialog, QtCore.QPoint(0, 0)).y()
        require(
            transcript_bottom <= status_top < input_top,
            "real status line is not between transcript and input",
        )
        transcript_text_left = (
            dialog.transcript.viewport().mapTo(
                dialog, QtCore.QPoint(0, 0)
            ).x()
            + expected_text_inset
        )
        status_text_left = dialog.status_label.mapTo(
            dialog, QtCore.QPoint(0, 0)
        ).x()
        require(
            abs(transcript_text_left - status_text_left) <= 1,
            "real status text is not aligned with transcript text",
        )
        send_center = dialog.send_button.mapTo(
            dialog, dialog.send_button.rect().center()
        ).y()
        python_center = dialog.python_checkbox.mapTo(
            dialog, dialog.python_checkbox.rect().center()
        ).y()
        require(
            abs(send_center - python_center) <= 2,
            "real Python control does not share the action row",
        )
        require(
            dialog.action_row.spacing() == 6,
            "real action controls are still packed too tightly",
        )
        dialog.transcript.setPlainText(
            "\n".join("message {}".format(index) for index in range(100))
        )
        main_window.resize(max(main_window.width(), 1000), 900)
        QtWidgets.QApplication.processEvents()
        main_window.resizeDocks([dock], [220], QtCore.Qt.Vertical)
        QtWidgets.QApplication.processEvents()
        compact_transcript_height = dialog.transcript.height()
        compact_footer_height = dialog.footer_widget.height()
        compact_footer_gap = (
            dialog.height() - dialog.footer_widget.geometry().bottom()
        )
        require(
            dialog.transcript.verticalScrollBar().maximum() > 0,
            "compact real transcript does not expose its vertical scrollbar",
        )
        main_window.resizeDocks([dock], [700], QtCore.Qt.Vertical)
        QtWidgets.QApplication.processEvents()
        require(
            dialog.footer_widget.height() == compact_footer_height,
            "real footer height changed while resizing the dock",
        )
        require(
            abs(
                dialog.height()
                - dialog.footer_widget.geometry().bottom()
                - compact_footer_gap
            )
            <= 1,
            "real footer did not remain anchored to the bottom",
        )
        require(
            dialog.transcript.height() > compact_transcript_height,
            "real Codex dock does not expand the transcript with extra height",
        )

        dialog.full_python_enabled = True
        dock.close()
        require(not dock.isVisible(), "Codex dock did not close")
        require(
            not dialog.full_python_enabled,
            "closing the real dock did not lock unrestricted Python",
        )
        codex_for_pymol.open_dialog()
        require(dock.isVisible(), "Codex dock did not reopen")
        dialog.shutdown()
        log("Real PyMOL dock smoke test passed")
    except BaseException:
        RESULT["error"] = traceback.format_exc()
        print(RESULT["error"], file=sys.__stderr__, flush=True)
    finally:
        COMPLETION.set()
        application = QtWidgets.QApplication.instance()
        if application is not None:
            application.exit(1 if RESULT["error"] else 0)


def schedule_in_gui_thread():
    log("Real PyMOL dock smoke test loaded")
    for _attempt in range(20):
        dispatcher = getattr(cmd, "_call_in_gui_thread", None)
        if isinstance(dispatcher, MainThreadCaller):
            log("Real PyMOL GUI dispatcher initialized")
            dispatcher(run_test)
            return
        time.sleep(0.1)
    RESULT["error"] = "Real PyMOL GUI dispatcher was not initialized"
    print(RESULT["error"], file=sys.__stderr__, flush=True)
    COMPLETION.set()
    application = QtWidgets.QApplication.instance()
    if application is not None:
        application.quit()


def watchdog():
    if COMPLETION.wait(20):
        return
    RESULT["error"] = "Real PyMOL dock smoke test timed out"
    print(RESULT["error"], file=sys.__stderr__, flush=True)
    application = QtWidgets.QApplication.instance()
    if application is not None:
        QtCore.QMetaObject.invokeMethod(
            application,
            "quit",
            QtCore.Qt.QueuedConnection,
        )


threading.Thread(target=schedule_in_gui_thread, daemon=True).start()
threading.Thread(target=watchdog, daemon=True).start()
