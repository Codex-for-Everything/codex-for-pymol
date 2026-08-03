import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from codex_for_pymol.audit import AuditLogger


class AuditLoggerTests(unittest.TestCase):
    def test_write_failure_is_reported_without_raising(self):
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "not-a-directory"
            blocker.write_text("x", encoding="utf-8")
            logger = AuditLogger(blocker)
            self.assertFalse(logger.write("tool_call", value=1))
            self.assertIn("FileExistsError", logger.last_error)

    def test_sensitive_values_are_redacted_and_file_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = AuditLogger(Path(directory) / "logs")
            fake_api_key = "sk-" + "abcdefghijklmnop"
            self.assertTrue(
                logger.write(
                    "tool_call",
                    api_key="secret-value",
                    code=(
                        "token=plain-value\npassword='quoted-value'\n"
                        "value={!r}".format(fake_api_key)
                    ),
                )
            )
            record = json.loads(logger.path.read_text(encoding="utf-8"))
            self.assertEqual(record["api_key"], "[REDACTED]")
            self.assertNotIn("plain-value", record["code"])
            self.assertNotIn("quoted-value", record["code"])
            self.assertNotIn(fake_api_key, record["code"])
            if os.name != "nt":
                self.assertEqual(
                    stat.S_IMODE(logger.directory.stat().st_mode),
                    0o700,
                )
                self.assertEqual(stat.S_IMODE(logger.path.stat().st_mode), 0o600)

    def test_log_rotation_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = AuditLogger(
                Path(directory) / "logs",
                max_bytes=1024,
                backups=2,
            )
            for index in range(40):
                self.assertTrue(logger.write("event", index=index, text="x" * 100))
            paths = sorted(logger.directory.glob("audit*.jsonl"))
            self.assertLessEqual(len(paths), 3)
            self.assertTrue((logger.directory / "audit.1.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
