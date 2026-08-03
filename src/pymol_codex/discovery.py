"""Cross-platform Codex executable discovery."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


DISABLED_APP_SERVER_FEATURES = (
    "apps",
    "plugins",
    "browser_use",
    "computer_use",
    "image_generation",
    "shell_tool",
    "unified_exec",
)
ENABLED_APP_SERVER_FEATURES = ("respect_system_proxy",)


class CodexFeatureDiscoveryError(RuntimeError):
    """Raised when the selected Codex cannot report its feature catalog."""


def candidate_paths():
    """Return ordered, de-duplicated Codex executable candidates."""
    candidates = []
    configured = os.environ.get("PYMOL_CODEX_EXECUTABLE")
    if configured:
        candidates.append(configured)

    on_path = shutil.which("codex")
    if on_path:
        candidates.append(on_path)

    if sys.platform == "darwin":
        candidates.extend(
            [
                "/Applications/ChatGPT.app/Contents/Resources/codex",
                str(Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex"),
            ]
        )
    elif os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        candidates.extend(
            [
                str(local / "Programs" / "Codex" / "codex.exe"),
                str(local / "Programs" / "ChatGPT" / "resources" / "codex.exe"),
                str(local / "Microsoft" / "WindowsApps" / "codex.exe"),
                str(local / "Microsoft" / "WindowsApps" / "codex.cmd"),
            ]
        )

    result = []
    seen = set()
    for value in candidates:
        normalized = os.path.normcase(os.path.abspath(os.path.expanduser(value)))
        if normalized not in seen:
            seen.add(normalized)
            result.append(value)
    return result


def find_codex(configured=None):
    """Find a usable Codex executable, preferring an explicit setting."""
    values = [configured] if configured else []
    values.extend(candidate_paths())
    for value in values:
        if not value:
            continue
        path = Path(value).expanduser()
        if path.is_file() and (os.name == "nt" or os.access(str(path), os.X_OK)):
            return str(path)
    return None


def _command_invocation(executable, arguments):
    """Return a safely quoted process invocation for an executable or script."""
    # os.path.splitext does not instantiate a platform-specific pathlib class,
    # which also makes this branch straightforward to test on non-Windows hosts.
    suffix = os.path.splitext(executable)[1].lower()
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        command = "call " + subprocess.list2cmdline(
            [executable] + list(arguments)
        )
        return os.environ.get("COMSPEC", "cmd.exe"), ["/d", "/s", "/c", command]
    return executable, list(arguments)


def parse_feature_list(output):
    """Return non-removed feature names reported by ``codex features list``."""
    features = set()
    for line in str(output or "").splitlines():
        columns = line.split()
        if len(columns) < 3 or columns[-1].lower() not in {"true", "false"}:
            continue
        if " ".join(columns[1:-1]).strip().lower() == "removed":
            continue
        features.add(columns[0])
    return features


def discover_codex_features(executable, timeout=3):
    """Query the selected user's Codex binary for its current feature names."""
    program, arguments = _command_invocation(
        executable,
        ["features", "list"],
    )
    try:
        completed = subprocess.run(
            [program] + arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return parse_feature_list(completed.stdout)


def app_server_arguments(executable, available_features=None):
    """Build arguments using only features supported by the selected Codex."""
    if available_features is None:
        available_features = discover_codex_features(executable)
    if available_features is None:
        raise CodexFeatureDiscoveryError(
            "无法读取当前 Codex 的功能列表，已停止启动以避免意外开放"
            "命令行等无关能力。请确认该可执行文件支持 "
            "“codex features list”，或升级后重新选择 Codex。"
        )
    available_features = set(available_features)
    arguments = ["app-server", "--stdio"]
    for feature in DISABLED_APP_SERVER_FEATURES:
        if feature in available_features:
            arguments.extend(["--disable", feature])
    for feature in ENABLED_APP_SERVER_FEATURES:
        if feature in available_features:
            arguments.extend(["--enable", feature])
    arguments.extend(["-c", "mcp_servers={}"])
    return arguments


def process_invocation(executable, available_features=None):
    """Return ``(program, args)`` suitable for QProcess on this platform."""
    return _command_invocation(
        executable,
        app_server_arguments(executable, available_features),
    )


def feature_invocation(executable):
    """Return the invocation used to query the selected Codex feature list."""
    return _command_invocation(executable, ["features", "list"])
