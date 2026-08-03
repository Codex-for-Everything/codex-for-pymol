import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pymol_codex.discovery import (
    CodexFeatureDiscoveryError,
    app_server_arguments,
    discover_codex_features,
    find_codex,
    parse_feature_list,
    process_invocation,
)


class DiscoveryTests(unittest.TestCase):
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
                "pymol_codex.discovery.candidate_paths", return_value=[]
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
        with mock.patch("pymol_codex.discovery.os.name", "nt"):
            with mock.patch.dict(os.environ, {"COMSPEC": "C:\\Windows\\cmd.exe"}):
                program, args = process_invocation(
                    "C:\\Tools\\codex.cmd",
                    {"shell_tool"},
                )
        self.assertEqual(program, "C:\\Windows\\cmd.exe")
        self.assertEqual(args[:3], ["/d", "/s", "/c"])
        self.assertTrue(args[3].startswith("call "))
        self.assertIn("app-server --stdio", args[3])
        self.assertIn("--disable shell_tool", args[3])

    def test_direct_executable_uses_only_reported_features(self):
        program, args = process_invocation(
            "/opt/codex",
            {"shell_tool", "respect_system_proxy"},
        )
        self.assertEqual(program, "/opt/codex")
        self.assertEqual(args[:2], ["app-server", "--stdio"])
        self.assertIn("shell_tool", args)
        self.assertIn("respect_system_proxy", args)
        self.assertIn("mcp_servers={}", args)
        self.assertNotIn("plugins", args)

    def test_feature_list_parser_ignores_removed_and_noise(self):
        output = """
shell_tool                 stable             true
respect_system_proxy      under development  false
old_tool                   removed            false
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
            "pymol_codex.discovery.subprocess.run",
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
            "pymol_codex.discovery.subprocess.run",
            return_value=completed,
        ):
            self.assertIsNone(discover_codex_features("/opt/codex"))
        with mock.patch(
            "pymol_codex.discovery.discover_codex_features",
            return_value=None,
        ):
            with self.assertRaises(CodexFeatureDiscoveryError):
                app_server_arguments("/opt/codex")


if __name__ == "__main__":
    unittest.main()
