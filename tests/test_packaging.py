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

from codex_for_pymol.version import __version__


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build_plugin.py"


def _load_build_module():
    spec = importlib.util.spec_from_file_location(
        "codex_for_pymol_build_plugin", BUILD_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the PyMOL plugin build script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_with(module, source, output, license_file=ROOT / "LICENSE"):
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(module, "SOURCE", source))
        stack.enter_context(mock.patch.object(module, "DIST", output.parent))
        stack.enter_context(mock.patch.object(module, "OUTPUT", output))
        stack.enter_context(mock.patch.object(module, "LICENSE_FILE", license_file))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        module.main()


class PackagingTests(unittest.TestCase):
    def test_distribution_and_import_package_names_are_consistent(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        module = _load_build_module()

        self.assertIn('name = "codex-for-pymol"', pyproject)
        self.assertIn('packages = ["src/codex_for_pymol"]', pyproject)
        self.assertTrue(
            (ROOT / "src" / "codex_for_pymol" / "__init__.py").is_file()
        )
        self.assertFalse((ROOT / "src" / "pymol_codex").exists())
        self.assertEqual(
            module.OUTPUT.name,
            "codex-for-pymol-{}.zip".format(__version__),
        )

    def test_project_version_matches_package_version(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        project_section = pyproject.split("[project]", 1)[1].split("\n[", 1)[0]
        match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', project_section, re.MULTILINE)

        self.assertIsNotNone(match, "pyproject.toml must declare [project].version")
        self.assertEqual(match.group(1), __version__)

    def test_plugin_filename_rejects_an_unsafe_version(self):
        module = _load_build_module()
        with tempfile.TemporaryDirectory() as directory:
            version_file = Path(directory) / "version.py"
            version_file.write_text(
                '__version__ = "../../unexpected"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "release version"):
                module.read_version(version_file)

    def test_plugin_zip_contains_only_portable_source_files(self):
        module = _load_build_module()
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "source"
            output = temporary / "dist" / "plugin.zip"
            license_file = temporary / "LICENSE"
            license_file.write_bytes(b"Example license\r\n")
            files = {
                "__init__.py": "VERSION = 1\n",
                "nested/visible.py": "VISIBLE = True\n",
                "nested/not-plugin-source.txt": "must not be packaged\n",
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
            external = temporary / "external.py"
            external.write_text("SECRET = True\n", encoding="utf-8")
            try:
                (source / "linked.py").symlink_to(external)
            except OSError:
                pass

            _build_with(module, source, output, license_file)

            with ZipFile(output) as archive:
                names = archive.namelist()
                compression = {item.filename: item.compress_type for item in archive.infolist()}
                archived_license = archive.read("codex_for_pymol/LICENSE")

            self.assertEqual(
                names,
                [
                    "codex_for_pymol/LICENSE",
                    "codex_for_pymol/__init__.py",
                    "codex_for_pymol/nested/visible.py",
                ],
            )
            self.assertEqual(archived_license, license_file.read_bytes())
            self.assertTrue(all(value == ZIP_DEFLATED for value in compression.values()))
            for name in names:
                path = PurePosixPath(name)
                self.assertFalse(path.is_absolute())
                self.assertNotIn("..", path.parts)
                self.assertNotIn("\\", name)

    def test_plugin_source_root_cannot_be_a_symlink(self):
        module = _load_build_module()
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            real_source = temporary / "real-source"
            real_source.mkdir()
            (real_source / "__init__.py").write_text("", encoding="utf-8")
            linked_source = temporary / "linked-source"
            try:
                linked_source.symlink_to(real_source, target_is_directory=True)
            except OSError as error:
                self.skipTest("directory symlinks are unavailable: {}".format(error))
            license_file = temporary / "LICENSE"
            license_file.write_text("Example license\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "real directory"):
                _build_with(
                    module,
                    linked_source,
                    temporary / "dist" / "plugin.zip",
                    license_file,
                )

    def test_rebuilding_plugin_zip_removes_stale_entries(self):
        module = _load_build_module()
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "source"
            source.mkdir()
            (source / "__init__.py").write_text("", encoding="utf-8")
            license_file = temporary / "LICENSE"
            license_file.write_text("Example license\n", encoding="utf-8")
            output = temporary / "dist" / "plugin.zip"

            _build_with(module, source, output, license_file)
            with ZipFile(output, "a") as archive:
                archive.writestr("stale.txt", "must disappear")

            _build_with(module, source, output, license_file)

            with ZipFile(output) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["codex_for_pymol/LICENSE", "codex_for_pymol/__init__.py"],
                )

    def test_real_plugin_zip_imports_in_an_isolated_interpreter(self):
        module = _load_build_module()
        with tempfile.TemporaryDirectory() as directory:
            output = (
                Path(directory)
                / "dist"
                / "codex-for-pymol-{}.zip".format(__version__)
            )
            _build_with(module, ROOT / "src" / "codex_for_pymol", output)

            with ZipFile(output) as archive:
                names = archive.namelist()
                expected_sources = [
                    "codex_for_pymol/{}".format(
                        path.relative_to(
                            ROOT / "src" / "codex_for_pymol"
                        ).as_posix()
                    )
                    for path in sorted(
                        (ROOT / "src" / "codex_for_pymol").rglob("*.py")
                    )
                    if path.is_file() and not path.is_symlink()
                ]
                self.assertEqual(
                    names,
                    ["codex_for_pymol/LICENSE"] + expected_sources,
                )
                self.assertEqual(
                    archive.read("codex_for_pymol/LICENSE"),
                    (ROOT / "LICENSE").read_bytes(),
                )

            command = (
                "import importlib.util, sys; "
                "sys.path.insert(0, sys.argv[1]); "
                "import codex_for_pymol; "
                "print(codex_for_pymol.__version__); "
                "print(importlib.util.find_spec('pymol_codex'))"
            )
            completed = subprocess.run(
                [sys.executable, "-I", "-c", command, str(output)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                completed.stdout.splitlines(),
                [__version__, "None"],
            )


if __name__ == "__main__":
    unittest.main()
