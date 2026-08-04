import importlib
import sys
import types
import unittest
from unittest import mock


class FakePalette:
    Active = 0
    Inactive = 1
    Disabled = 2
    Window = 10
    Base = 11
    AlternateBase = 12
    ToolTipBase = 13
    WindowText = 20
    Text = 21
    ToolTipText = 22
    Button = 30
    ButtonText = 31

    def __init__(self, source=None):
        self.values = dict(source.values) if source is not None else {}

    def color(self, group, role):
        return self.values[(group, role)]

    def setColor(self, group, role, value):
        self.values[(group, role)] = value

    def brush(self, group, role):
        return self.values[(group, role)]

    def setBrush(self, group, role, value):
        self.values[(group, role)] = value


class FakeStyle:
    def __init__(self, palette):
        self.palette = palette

    def standardPalette(self):
        return FakePalette(self.palette)


class FakeApplication:
    current = None

    @classmethod
    def instance(cls):
        return cls.current


class PaletteSource:
    def __init__(self, palette):
        self._palette = palette

    def palette(self):
        return self._palette


class DockingPaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pymol = types.ModuleType("pymol")
        pymol_qt = types.ModuleType("pymol.Qt")
        pymol_qt.QtCore = types.SimpleNamespace(QObject=object)
        pymol_qt.QtGui = types.SimpleNamespace(QPalette=FakePalette)
        pymol_qt.QtWidgets = types.SimpleNamespace(
            QApplication=FakeApplication,
        )
        fake_ui = types.ModuleType("codex_for_pymol.ui")
        fake_ui.CodexDialog = object
        cls.module_patch = mock.patch.dict(
            sys.modules,
            {
                "pymol": pymol,
                "pymol.Qt": pymol_qt,
                "codex_for_pymol.ui": fake_ui,
            },
        )
        cls.module_patch.start()
        sys.modules.pop("codex_for_pymol.docking", None)
        cls.docking = importlib.import_module("codex_for_pymol.docking")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("codex_for_pymol.docking", None)
        package = sys.modules.get("codex_for_pymol")
        if getattr(package, "docking", None) is cls.docking:
            delattr(package, "docking")
        FakeApplication.current = None
        cls.module_patch.stop()

    def make_palettes(self):
        source = FakePalette()
        native = FakePalette()
        for group in (
            FakePalette.Active,
            FakePalette.Inactive,
            FakePalette.Disabled,
        ):
            source.setColor(group, FakePalette.Base, "console-background")
            source.setColor(group, FakePalette.Text, "console-foreground")
            source.setColor(group, FakePalette.Button, "unreliable-button")
            source.setColor(group, FakePalette.ButtonText, "unreliable-text")
            native.setColor(group, FakePalette.Button, "native-button")
            native.setColor(group, FakePalette.ButtonText, "native-text")
        return source, native

    def test_windows_uses_native_button_pair(self):
        source, native = self.make_palettes()
        FakeApplication.current = types.SimpleNamespace(
            style=lambda: FakeStyle(native)
        )

        with mock.patch.object(self.docking.os, "name", "nt"):
            result = self.docking.console_palette(PaletteSource(source))

        for group in (
            FakePalette.Active,
            FakePalette.Inactive,
            FakePalette.Disabled,
        ):
            self.assertEqual(
                result.color(group, FakePalette.Button), "native-button"
            )
            self.assertEqual(
                result.color(group, FakePalette.ButtonText), "native-text"
            )
            self.assertEqual(
                result.color(group, FakePalette.Window), "console-background"
            )
            self.assertEqual(
                result.color(group, FakePalette.WindowText), "console-foreground"
            )

    def test_macos_keeps_existing_console_button_colors(self):
        source, native = self.make_palettes()
        FakeApplication.current = types.SimpleNamespace(
            style=lambda: FakeStyle(native)
        )

        with mock.patch.object(self.docking.os, "name", "posix"):
            result = self.docking.console_palette(PaletteSource(source))

        for group in (
            FakePalette.Active,
            FakePalette.Inactive,
            FakePalette.Disabled,
        ):
            self.assertEqual(
                result.color(group, FakePalette.Button), "console-background"
            )
            self.assertEqual(
                result.color(group, FakePalette.ButtonText), "console-foreground"
            )


if __name__ == "__main__":
    unittest.main()
