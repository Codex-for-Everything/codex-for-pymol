import os
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

from codex_for_pymol.discovery import (
    CodexFeatureDiscoveryError,
    FEATURE_DISCOVERY_TIMEOUT_SECONDS,
    ProcessInvocation,
    WINDOWS_LAUNCHER_ENV,
    app_server_arguments,
    candidate_paths,
    discover_codex_features,
    feature_invocation,
    find_codex,
    is_supported_launcher,
    parse_feature_list,
    process_invocation,
)


class DiscoveryTests(unittest.TestCase):
    def test_windows_rejects_unsupported_launcher_types(self):
        for path in ("codex", "codex.js", "codex.ps1", "codex.py"):
            with self.subTest(path=path):
                self.assertFalse(is_supported_launcher(path, windows=True))
        for path in ("codex.exe", "codex.cmd", "codex.BAT"):
            with self.subTest(path=path):
                self.assertTrue(is_supported_launcher(path, windows=True))

    def test_invalid_configured_launcher_falls_back_to_valid_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "codex.ps1"
            valid = Path(directory) / "codex.cmd"
            invalid.write_text("", encoding="utf-8")
            valid.write_text("", encoding="utf-8")
            valid.chmod(0o700)
            with mock.patch(
                "codex_for_pymol.discovery.candidate_paths",
                return_value=[str(valid)],
            ), mock.patch(
                "codex_for_pymol.discovery.is_supported_launcher",
                side_effect=lambda path: str(path).endswith(".cmd"),
            ):
                self.assertEqual(find_codex(str(invalid)), str(valid))

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

    def test_macos_bundled_candidates_remain_unchanged(self):
        home = PurePosixPath("/") / "Users" / "test-account"
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "codex_for_pymol.discovery.shutil.which",
            return_value=None,
        ), mock.patch(
            "codex_for_pymol.discovery.sys.platform",
            "darwin",
        ), mock.patch(
            "codex_for_pymol.discovery.Path.home",
            return_value=home,
        ):
            candidates = candidate_paths()
        self.assertEqual(
            candidates,
            [
                "/Applications/ChatGPT.app/Contents/Resources/codex",
                str(
                    home
                    / "Applications/ChatGPT.app/Contents/Resources/codex"
                ),
            ],
        )

    @unittest.skipUnless(os.name == "nt", "Windows candidate paths")
    def test_windows_candidates_cover_common_user_install_locations(self):
        home = Path("C:/") / "Users" / "test-account"
        local = home / "AppData" / "Local"
        roaming = home / "AppData" / "Roaming"
        prefix = Path("D:/npm-prefix")
        environment = {
            "LOCALAPPDATA": str(local),
            "APPDATA": str(roaming),
            "NPM_CONFIG_PREFIX": str(prefix),
        }
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch(
            "codex_for_pymol.discovery.shutil.which",
            return_value=None,
        ), mock.patch(
            "codex_for_pymol.discovery.Path.home",
            return_value=home,
        ):
            candidates = candidate_paths()
        self.assertIn(str(roaming / "npm" / "codex.cmd"), candidates)
        self.assertIn(str(prefix / "codex.cmd"), candidates)
        self.assertIn(str(prefix / "bin" / "codex.cmd"), candidates)
        self.assertIn(str(home / ".local" / "bin" / "codex.exe"), candidates)
        self.assertFalse(any(".vscode" in path for path in candidates))
        self.assertFalse(any("ChatGPT" in path for path in candidates))
        self.assertFalse(any("WindowsApps" in path for path in candidates))

    @unittest.skipUnless(os.name == "nt", "Windows candidate paths")
    def test_windows_candidates_fall_back_to_home_appdata(self):
        home = Path("C:/") / "Users" / "test-account"
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "codex_for_pymol.discovery.shutil.which",
            return_value=None,
        ), mock.patch(
            "codex_for_pymol.discovery.Path.home",
            return_value=home,
        ):
            candidates = candidate_paths()
        self.assertIn(
            str(home / "AppData" / "Roaming" / "npm" / "codex.cmd"),
            candidates,
        )

    def test_macos_and_posix_invocation_remains_direct(self):
        executable = "/Applications/ChatGPT.app/Contents/Resources/codex"
        self.assertEqual(
            feature_invocation(executable),
            ProcessInvocation(executable, ["features", "list"], {}),
        )

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
                invocation = process_invocation(
                    "C:\\Codex Tools\\codex.cmd",
                    {"shell_tool"},
                )
        self.assertEqual(invocation.program, "C:\\Windows\\cmd.exe")
        self.assertEqual(invocation.arguments[:3], ["/d", "/v:off", "/c"])
        self.assertEqual(
            invocation.arguments[3],
            "%{}%".format(WINDOWS_LAUNCHER_ENV),
        )
        self.assertEqual(invocation.arguments[4:6], ["app-server", "--stdio"])
        self.assertIn("shell_tool", invocation.arguments)
        self.assertEqual(
            invocation.environment,
            {WINDOWS_LAUNCHER_ENV: '"C:\\Codex Tools\\codex.cmd"'},
        )

    @unittest.skipUnless(os.name == "nt", "Windows cmd launcher test")
    def test_windows_cmd_invocation_executes_launcher_with_spaces(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "Codex & Tools (100%)"
            parent.mkdir()
            for suffix in (".cmd", ".bat"):
                with self.subTest(suffix=suffix):
                    path = parent / ("codex" + suffix)
                    path.write_text(
                        "@echo off\n"
                        "if /I not \"%~1\"==\"features\" exit /b 7\n"
                        "if /I not \"%~2\"==\"list\" exit /b 8\n"
                        "echo shell_tool stable true\n",
                        encoding="utf-8",
                    )
                    self.assertEqual(
                        discover_codex_features(str(path)),
                        {"shell_tool"},
                    )

    def test_windows_cmd_rejects_invalid_path_text(self):
        invalid_paths = [
            'C:\\Tools"Quoted\\codex.cmd',
            "C:\\Tools\\codex\r.cmd",
            "C:\\Tools\\codex\n.cmd",
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
        invocation = process_invocation(
            "/opt/codex",
            {
                "fast_mode",
                "future_host_capability",
                "shell_tool",
                "respect_system_proxy",
            },
        )
        self.assertEqual(invocation.program, "/opt/codex")
        self.assertEqual(invocation.environment, {})
        self.assertEqual(
            invocation.arguments,
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
        self.assertNotIn("fast_mode", invocation.arguments)
        self.assertNotIn("plugins", invocation.arguments)

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
        self.assertEqual(
            run.call_args.kwargs["timeout"],
            FEATURE_DISCOVERY_TIMEOUT_SECONDS,
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
