"""Cross-platform Codex executable discovery."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple


FEATURE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
FEATURE_DISCOVERY_TIMEOUT_SECONDS = 10
WINDOWS_LAUNCHER_ENV = "CODEX_FOR_PYMOL_WINDOWS_LAUNCHER"
ENABLED_APP_SERVER_FEATURES = frozenset(("respect_system_proxy",))
PASSTHROUGH_APP_SERVER_FEATURES = frozenset(
    (
        # These affect transport, context maintenance, or the user-visible
        # service tier without granting another host capability.
        "enable_request_compression",
        "fast_mode",
        "remote_compaction_v2",
    )
)


class CodexFeatureDiscoveryError(RuntimeError):
    """Raised when the selected Codex cannot report its feature catalog."""


class ProcessInvocation(NamedTuple):
    """A process command and the environment values required to run it."""

    program: str
    arguments: list
    environment: dict


def candidate_paths():
    """Return ordered, de-duplicated Codex executable candidates."""
    candidates = []
    configured = os.environ.get("CODEX_FOR_PYMOL_EXECUTABLE")
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
        home = Path.home()
        local = Path(
            os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local"
        )
        roaming = Path(
            os.environ.get("APPDATA") or home / "AppData" / "Roaming"
        )
        candidates.extend(
            [
                str(local / "Programs" / "Codex" / "codex.exe"),
                str(roaming / "npm" / "codex.exe"),
                str(roaming / "npm" / "codex.cmd"),
                str(home / ".local" / "bin" / "codex.exe"),
                str(home / ".local" / "bin" / "codex.cmd"),
            ]
        )
        npm_prefix = os.environ.get("NPM_CONFIG_PREFIX")
        if npm_prefix:
            prefix = Path(npm_prefix).expanduser()
            candidates.extend(
                [
                    str(prefix / "codex.exe"),
                    str(prefix / "codex.cmd"),
                    str(prefix / "bin" / "codex.exe"),
                    str(prefix / "bin" / "codex.cmd"),
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
    """Return a safe process invocation for an executable or script."""
    # os.path.splitext does not instantiate a platform-specific pathlib class,
    # which also makes this branch straightforward to test on non-Windows hosts.
    suffix = os.path.splitext(executable)[1].lower()
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        if any(character in executable for character in '\0\r\n"'):
            raise ValueError("Codex launcher path contains an invalid character")
        # Keep the untrusted path out of the command line. The environment
        # value includes its own quotes, so expansion remains one command token
        # even when the path contains spaces or cmd.exe metacharacters. Delayed
        # expansion is disabled so a literal '!' remains data as well.
        return ProcessInvocation(
            os.environ.get("COMSPEC", "cmd.exe"),
            [
                "/d",
                "/v:off",
                "/c",
                "%{}%".format(WINDOWS_LAUNCHER_ENV),
            ]
            + list(arguments),
            {WINDOWS_LAUNCHER_ENV: '"{}"'.format(executable)},
        )
    return ProcessInvocation(executable, list(arguments), {})


def parse_feature_list(output):
    """Return non-removed feature names reported by ``codex features list``."""
    features = set()
    for line in str(output or "").splitlines():
        columns = line.split()
        if len(columns) < 3 or columns[-1].lower() not in {"true", "false"}:
            continue
        if " ".join(columns[1:-1]).strip().lower() == "removed":
            continue
        feature = columns[0]
        if FEATURE_NAME.fullmatch(feature):
            features.add(feature)
    return features


def discover_codex_features(
    executable,
    timeout=FEATURE_DISCOVERY_TIMEOUT_SECONDS,
):
    """Query the selected user's Codex binary for its current feature names."""
    invocation = _command_invocation(
        executable,
        ["features", "list"],
    )
    environment = None
    if invocation.environment:
        environment = os.environ.copy()
        environment.update(invocation.environment)
    try:
        completed = subprocess.run(
            [invocation.program] + invocation.arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=environment,
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
    available_features = set(available_features or ())
    if not available_features:
        raise CodexFeatureDiscoveryError(
            "无法读取当前 Codex 的功能列表，已停止启动以避免意外开放"
            "命令行等无关能力。请确认该可执行文件支持 "
            "“codex features list”，或升级后重新选择 Codex。"
        )
    arguments = ["app-server", "--stdio"]
    for feature in sorted(available_features):
        if feature in ENABLED_APP_SERVER_FEATURES:
            arguments.extend(["--enable", feature])
        elif feature not in PASSTHROUGH_APP_SERVER_FEATURES:
            # Fail closed for capabilities added by future Codex versions:
            # every reported optional feature is disabled unless this host
            # has explicitly classified it as necessary and non-capability-
            # bearing above.
            arguments.extend(["--disable", feature])
    arguments.extend(["-c", "mcp_servers={}"])
    return arguments


def process_invocation(executable, available_features=None):
    """Return a process invocation suitable for QProcess on this platform."""
    return _command_invocation(
        executable,
        app_server_arguments(executable, available_features),
    )


def feature_invocation(executable):
    """Return the invocation used to query the selected Codex feature list."""
    return _command_invocation(executable, ["features", "list"])
