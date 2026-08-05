"""Exercise the installed Codex App Server's ephemeral-thread contract.

This optional maintainer test uses an isolated, temporary Codex home and never
starts a model turn. It neither reads normal Codex history nor needs a model
response.
"""

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time

from codex_for_pymol.discovery import (
    discover_codex_features,
    find_codex,
    process_invocation,
)
from codex_for_pymol.protocol import validated_ephemeral_thread_id


class AppServerProbe:
    def __init__(self, process):
        self.process = process
        self.messages = queue.Queue()
        self.stderr_lines = []
        self.next_request_id = 1
        self.stdout_thread = threading.Thread(
            target=self._read_stdout,
            daemon=True,
        )
        self.stderr_thread = threading.Thread(
            target=self._read_stderr,
            daemon=True,
        )
        self.stdout_thread.start()
        self.stderr_thread.start()

    def _read_stdout(self):
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except json.JSONDecodeError as exc:
                    self.messages.put(exc)
        finally:
            self.messages.put(None)

    def _read_stderr(self):
        for line in self.process.stderr:
            self.stderr_lines.append(line.rstrip())
            del self.stderr_lines[:-50]

    def _write(self, message):
        encoded = json.dumps(message, separators=(",", ":")) + "\n"
        self.process.stdin.write(encoded)
        self.process.stdin.flush()

    def notify(self, method, params=None):
        self._write({"method": method, "params": params or {}})

    def request(self, method, params=None, timeout=10):
        request_id = self.next_request_id
        self.next_request_id += 1
        self._write(
            {
                "method": method,
                "id": request_id,
                "params": params or {},
            }
        )
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("waiting for {} timed out".format(method))
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(
                    "waiting for {} timed out".format(method)
                ) from None
            if message is None:
                details = "\n".join(self.stderr_lines[-10:])
                raise RuntimeError(
                    "Codex App Server exited while waiting for {}{}".format(
                        method,
                        ":\n" + details if details else "",
                    )
                )
            if isinstance(message, Exception):
                raise RuntimeError("invalid JSON from Codex: {}".format(message))
            if message.get("id") != request_id or "method" in message:
                continue
            if "error" in message:
                error = message["error"]
                if isinstance(error, dict):
                    error = error.get("message") or error
                raise RuntimeError("{} failed: {}".format(method, error))
            return message.get("result")


def _terminate(process):
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--codex",
        help="Codex executable to test; defaults to normal plugin discovery",
    )
    args = parser.parse_args()
    executable = find_codex(args.codex)
    if not executable:
        raise RuntimeError("Codex executable was not found")
    features = discover_codex_features(executable, timeout=10)
    if not features:
        raise RuntimeError("Codex did not return a usable feature catalog")
    invocation = process_invocation(executable, features)

    with tempfile.TemporaryDirectory(
        prefix="codex-for-pymol-app-server-smoke-"
    ) as directory:
        private_home = Path(directory) / "codex-home"
        private_home.mkdir(mode=0o700)
        environment = os.environ.copy()
        environment.update(invocation.environment)
        environment["CODEX_HOME"] = str(private_home)
        process = subprocess.Popen(
            [invocation.program] + invocation.arguments,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
        )
        probe = AppServerProbe(process)
        try:
            probe.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "codex_for_pymol_protocol_smoke",
                        "title": "Codex for PyMOL protocol smoke test",
                        "version": "0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            probe.notify("initialized")
            started = probe.request(
                "thread/start",
                {
                    "cwd": directory,
                    "sandbox": "read-only",
                    "approvalPolicy": "never",
                    "developerInstructions": "Protocol smoke test only.",
                    "dynamicTools": [],
                    "environments": [],
                    "ephemeral": True,
                    "serviceName": "codex_for_pymol_protocol_smoke",
                },
            )
            thread_id = validated_ephemeral_thread_id(started)
            listed = probe.request("thread/list", {"limit": 100})
            data = listed.get("data") if isinstance(listed, dict) else None
            if not isinstance(data, list):
                raise RuntimeError("thread/list returned an invalid result")
            if any(
                isinstance(thread, dict) and thread.get("id") == thread_id
                for thread in data
            ):
                raise RuntimeError(
                    "the ephemeral thread appeared in persistent thread/list results"
                )
        finally:
            _terminate(process)

    print("Codex App Server ephemeral-thread smoke test passed")


if __name__ == "__main__":
    main()
