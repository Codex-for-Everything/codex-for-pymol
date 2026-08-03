import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_for_pymol.discovery import (
    CodexFeatureDiscoveryError,
    app_server_arguments,
    candidate_paths,
    discover_codex_features,
    find_codex,
    parse_feature_list,
    process_invocation,
)


class DiscoveryTests(unittest.TestCase):
    def test_project_named_environment_variable_is_preferred(self):
        configured = "/configured/codex"
        with mock.patch.dict(
            os.environ,
            {"CODEX_FOR_PYMOL_EXECUTABLE": configured},
            clear=False,
        ), mock.patch("codex_for_pymol.discovery.shutil.which", return_value=None):
            self.assertEqual(candidate_paths()[0], configured)

    def test_explicit_executable_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "codex"
            path.write_text("", encoding="utf-8")
            if os.name != "nt":
                path.chmod(0o700)
            self.assertEqual(find_codex(str(path)), str(path))

    @unittest.skipIf(os.name == "nt", "POSIX executable permissions only")
    def test_non_executable_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "codex"
            path.write_text("", encoding="utf-8")
            path.chmod(0o600)
            with mock.patch(
                "codex_for_pymol.discovery.candidate_paths", return_value=[]
            ):
                self.assertIsNone(find_codex(str(path)))

    @unittest.skipIf(os.name == "nt", "POSIX home expansion test")
    def test_explicit_home_relative_path_is_expanded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bin" / "codex"
            path.parent.mkdir()
            path.write_text("", encoding="utf-8")
            path.chmod(0o700)
            with mock.patch.dict(os.environ, {"HOME": directory}):
                self.assertEqual(find_codex("~/bin/codex"), str(path))

    def test_windows_cmd_uses_comspec(self):
        with mock.patch("codex_for_pymol.discovery.os.name", "nt"):
            with mock.patch.dict(os.environ, {"COMSPEC": "C:\\Windows\\cmd.exe"}):
                program, args = process_invocation(
                    "C:\\Tools&Research\\codex.cmd",
                    {"shell_tool"},
                )
        self.assertEqual(program, "C:\\Windows\\cmd.exe")
        self.assertEqual(args[:4], ["/d", "/v:off", "/s", "/c"])
        self.assertTrue(
            args[4].startswith('call "C:\\Tools&Research\\codex.cmd" ')
        )
        self.assertIn("app-server --stdio", args[4])
        self.assertIn("--disable shell_tool", args[4])

    def test_windows_cmd_rejects_characters_that_cannot_be_quoted_safely(self):
        invalid_paths = [
            "C:\\Tools%PATH%\\codex.cmd",
            'C:\\Tools"Quoted\\codex.cmd',
            "C:\\Tools\rcodex.cmd",
            "C:\\Tools\ncodex.cmd",
            "C:\\Tools\0codex.cmd",
        ]
        for path in invalid_paths:
            with self.subTest(path=repr(path)), mock.patch(
                "codex_for_pymol.discovery.os.name",
                "nt",
            ):
                with self.assertRaisesRegex(ValueError, "invalid character"):
                    process_invocation(path, {"shell_tool"})

    def test_direct_executable_uses_only_reported_features(self):
        program, args = process_invocation(
            "/opt/codex",
            {
                "fast_mode",
                "future_host_capability",
                "shell_tool",
                "respect_system_proxy",
            },
        )
        self.assertEqual(program, "/opt/codex")
        self.assertEqual(
            args,
            [
                "app-server",
                "--stdio",
                "--disable",
                "future_host_capability",
                "--enable",
                "respect_system_proxy",
                "--disable",
                "shell_tool",
                "-c",
                "mcp_servers={}",
            ],
        )
        self.assertNotIn("fast_mode", args)
        self.assertNotIn("plugins", args)

    def test_feature_list_parser_ignores_removed_and_noise(self):
        output = """
shell_tool                 stable             true
respect_system_proxy      under development  false
old_tool                   removed            false
invalid/name               stable             true
WARNING: harmless
"""
        self.assertEqual(
            parse_feature_list(output),
            {"shell_tool", "respect_system_proxy"},
        )

    def test_feature_discovery_uses_selected_executable(self):
        completed = mock.Mock(
            returncode=0,
            stdout="shell_tool stable true\n",
        )
        with mock.patch(
            "codex_for_pymol.discovery.subprocess.run",
            return_value=completed,
        ) as run:
            self.assertEqual(
                discover_codex_features("/selected/codex"),
                {"shell_tool"},
            )
        self.assertEqual(
            run.call_args.args[0],
            ["/selected/codex", "features", "list"],
        )

    def test_feature_discovery_failure_is_fail_closed(self):
        completed = mock.Mock(returncode=2, stdout="")
        with mock.patch(
            "codex_for_pymol.discovery.subprocess.run",
            return_value=completed,
        ):
            self.assertIsNone(discover_codex_features("/opt/codex"))
        with mock.patch(
            "codex_for_pymol.discovery.discover_codex_features",
            return_value=None,
        ):
            with self.assertRaises(CodexFeatureDiscoveryError):
                app_server_arguments("/opt/codex")
        with self.assertRaises(CodexFeatureDiscoveryError):
            app_server_arguments("/opt/codex", set())


if __name__ == "__main__":
    unittest.main()
