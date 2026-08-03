import contextlib
import importlib.util
import io
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from zipfile import ZIP_DEFLATED, ZipFile

from pymol_codex.version import __version__


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build_plugin.py"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("pymol_codex_build_plugin", BUILD_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the PyMOL plugin build script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_with(module, source, output):
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(module, "SOURCE", source))
        stack.enter_context(mock.patch.object(module, "DIST", output.parent))
        stack.enter_context(mock.patch.object(module, "OUTPUT", output))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        module.main()


class PackagingTests(unittest.TestCase):
    def test_project_version_matches_package_version(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        project_section = pyproject.split("[project]", 1)[1].split("\n[", 1)[0]
        match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', project_section, re.MULTILINE)

        self.assertIsNotNone(match, "pyproject.toml must declare [project].version")
        self.assertEqual(match.group(1), __version__)

    def test_plugin_zip_contains_only_portable_source_files(self):
        module = _load_build_module()
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "source"
            output = temporary / "dist" / "plugin.zip"
            files = {
                "__init__.py": "VERSION = 1\n",
                "nested/visible.py": "VISIBLE = True\n",
                ".hidden.py": "HIDDEN = True\n",
                ".private/config.py": "PRIVATE = True\n",
                "__pycache__/cached.py": "CACHED = True\n",
                "module.pyc": "bytecode",
                "module.pyo": "optimized bytecode",
            }
            for relative, contents in files.items():
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents, encoding="utf-8")

            _build_with(module, source, output)

            with ZipFile(output) as archive:
                names = archive.namelist()
                compression = {item.filename: item.compress_type for item in archive.infolist()}

            self.assertEqual(
                names,
                ["pymol_codex/__init__.py", "pymol_codex/nested/visible.py"],
            )
            self.assertTrue(all(value == ZIP_DEFLATED for value in compression.values()))
            for name in names:
                path = PurePosixPath(name)
                self.assertFalse(path.is_absolute())
                self.assertNotIn("..", path.parts)
                self.assertNotIn("\\", name)

    def test_rebuilding_plugin_zip_removes_stale_entries(self):
        module = _load_build_module()
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "source"
            source.mkdir()
            (source / "__init__.py").write_text("", encoding="utf-8")
            output = temporary / "dist" / "plugin.zip"

            _build_with(module, source, output)
            with ZipFile(output, "a") as archive:
                archive.writestr("stale.txt", "must disappear")

            _build_with(module, source, output)

            with ZipFile(output) as archive:
                self.assertEqual(archive.namelist(), ["pymol_codex/__init__.py"])

    def test_real_plugin_zip_imports_in_an_isolated_interpreter(self):
        module = _load_build_module()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dist" / "pymol_codex_plugin.zip"
            _build_with(module, ROOT / "src" / "pymol_codex", output)

            command = (
                "import sys; "
                "sys.path.insert(0, sys.argv[1]); "
                "import pymol_codex; "
                "print(pymol_codex.__version__)"
            )
            completed = subprocess.run(
                [sys.executable, "-I", "-c", command, str(output)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), __version__)


if __name__ == "__main__":
    unittest.main()
