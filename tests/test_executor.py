import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_for_pymol.executor import PyMOLExecutor, action_risk


class FakeCmd:
    def __init__(self):
        self.calls = []

    def count_atoms(self, selection):
        return 42 if selection == "all" else 5

    def get_names(self, kind):
        return ["obj"] if kind == "objects" else ["pocket"]

    def get_type(self, name):
        return "object:molecule"

    def count_states(self, name):
        return 1

    def get_version(self):
        return ("3.1.0",)

    def get_chains(self, selection):
        return ["A"]

    def get_view(self):
        return tuple(range(18))

    def iterate(self, selection, expression, space):
        if "organic" in selection:
            space["collect_ligand"]("obj", "A", "101", "LIG")
            space["collect_ligand"]("obj", "A", "101", "LIG")
        else:
            space["residues"].add(("obj", "A", "1", "ALA"))

    def show(self, representation, selection):
        self.calls.append(("show", representation, selection))

    def color(self, color, selection):
        if color == "explode":
            raise RuntimeError("simulated PyMOL failure")
        self.calls.append(("color", color, selection))

    def label(self, selection, expression):
        self.calls.append(("label", selection, expression))

    def save(self, path, quiet=1):
        Path(path).write_bytes(b"checkpoint")
        self.calls.append(("save", path))

    def load(self, path, *args, **kwargs):
        self.calls.append(("load", path))

    def png(self, path, **_kwargs):
        Path(path).write_bytes(b"png")

    def refresh(self):
        return None


class MissingCheckpointCmd(FakeCmd):
    def save(self, path, quiet=1):
        self.calls.append(("save_without_file", path))


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cmd = FakeCmd()
        self.executor = PyMOLExecutor(self.cmd, cache_directory=self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_inspect_deduplicates_residues(self):
        value = self.executor.inspect({})
        self.assertEqual(value["atom_count"], 42)
        self.assertEqual(value["residue_count"], 1)
        self.assertEqual(value["ligand_count"], 1)
        self.assertEqual(value["ligands"][0]["atom_count"], 2)

    def test_apply_controlled_operations(self):
        result = self.executor.apply(
            {
                "operations": [
                    {"action": "show", "representation": "sticks", "selection": "organic"},
                    {"action": "color", "color": "yellow", "selection": "organic"},
                ]
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["scene_revision"], 1)
        self.assertEqual(len(self.cmd.calls), 2)

    def test_invalid_representation_is_rejected(self):
        with self.assertRaises(ValueError):
            self.executor.apply(
                {
                    "operations": [
                        {"action": "show", "representation": "not-a-representation"}
                    ]
                }
            )

    def test_preflight_rejects_entire_invalid_batch(self):
        checkpoints = []
        with self.assertRaises(ValueError):
            self.executor.apply(
                {
                    "operations": [
                        {"action": "show", "representation": "cartoon"},
                        {"action": "unsupported"},
                    ]
                },
                before_execute=lambda: checkpoints.append(True),
            )
        self.assertEqual(self.cmd.calls, [])
        self.assertEqual(checkpoints, [])
        self.assertEqual(self.executor.scene_revision, 0)

    def test_checkpoint_callback_runs_once_before_mutation(self):
        events = []
        original_show = self.cmd.show

        def recording_show(*arguments):
            events.append("mutation")
            original_show(*arguments)

        self.cmd.show = recording_show
        self.executor.apply(
            {
                "operations": [
                    {
                        "action": "show",
                        "representation": "cartoon",
                    }
                ]
            },
            before_execute=lambda: events.append("checkpoint"),
        )
        self.assertEqual(events, ["checkpoint", "mutation"])

    def test_runtime_failure_reports_partial_progress_and_revision(self):
        result = self.executor.apply(
            {
                "operations": [
                    {"action": "show", "representation": "cartoon"},
                    {"action": "color", "color": "explode"},
                ]
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["completed"], ["show"])
        self.assertEqual(result["failed_index"], 1)
        self.assertEqual(result["scene_revision"], 1)
        self.assertEqual(self.executor.scene_revision, 1)

    def test_custom_label_is_quoted_as_plain_text(self):
        self.executor.apply(
            {
                "operations": [
                    {
                        "action": "label",
                        "selection": "name CA",
                        "label_mode": "custom",
                        "text": '" + __import__("os").system("bad") + "',
                    }
                ]
            }
        )
        _, _, expression = self.cmd.calls[-1]
        self.assertTrue(expression.startswith('"'))
        self.assertIn('\\"', expression)

    def test_unrestricted_python_uses_explicit_result_and_checkpoint(self):
        result = self.executor.execute_python(
            'print("hello")\n__codex_result__ = {"answer": 42}', "call-1"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], {"answer": 42})
        self.assertEqual(result["stdout"], "hello\n")
        self.assertTrue(Path(result["checkpoint"]).is_file())
        if os.name != "nt":
            mode = stat.S_IMODE(Path(result["checkpoint"]).stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_instruction_checkpoints_form_an_undo_stack(self):
        first = self.executor.checkpoints.create("first")
        second = self.executor.checkpoints.create("second")
        restarted_cmd = FakeCmd()
        restarted = PyMOLExecutor(
            restarted_cmd,
            cache_directory=self.temp.name,
        )
        self.assertTrue(restarted.checkpoints.has_checkpoint())
        self.assertEqual(restarted.checkpoints.undo_last(), second)
        self.assertEqual(restarted.checkpoints.undo_last(), first)
        self.assertFalse(restarted.checkpoints.has_checkpoint())
        self.assertEqual(
            [call for call in restarted_cmd.calls if call[0] == "load"],
            [("load", second), ("load", first)],
        )

    def test_checkpoint_names_and_pruning_survive_a_coarse_clock(self):
        created = []
        with mock.patch(
            "codex_for_pymol.executor.time.strftime",
            return_value="20260803-120000",
        ), mock.patch(
            "codex_for_pymol.executor.time.time_ns",
            return_value=1722664000000000000,
        ):
            for _index in range(7):
                path = Path(self.executor.checkpoints.create("same-label"))
                created.append(path)
                os.utime(path, ns=(1722664000000000000, 1722664000000000000))

        self.assertEqual(len(set(created)), 7)
        self.assertEqual(
            set(self.executor.checkpoints.directory.glob("*.pse")),
            set(created[-5:]),
        )

    def test_checkpoint_directory_can_be_isolated_per_pymol_session(self):
        isolated = Path(self.temp.name) / "runtime" / "checkpoints"
        executor = PyMOLExecutor(
            self.cmd,
            cache_directory=self.temp.name,
            checkpoint_directory=isolated,
        )
        checkpoint = Path(
            executor.checkpoints.create("isolated-session")
        )
        self.assertEqual(checkpoint.parent, isolated)
        self.assertTrue(checkpoint.is_file())

    def test_python_does_not_run_without_a_real_checkpoint(self):
        cmd_without_checkpoint = MissingCheckpointCmd()
        executor = PyMOLExecutor(
            cmd_without_checkpoint,
            cache_directory=self.temp.name,
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "did not create the requested checkpoint",
        ):
            executor.execute_python(
                "__codex_result__ = 'must not run'",
                "missing-checkpoint",
            )
        self.assertEqual(executor.scene_revision, 0)

    def test_python_output_is_bounded_while_running(self):
        result = self.executor.execute_python('print("x" * 300000)', "large-output")
        self.assertTrue(result["ok"])
        self.assertIn("additional characters truncated", result["stdout"])
        self.assertLess(len(result["stdout"]), 201000)

    def test_snapshots_are_private_and_pruned(self):
        created = []
        with mock.patch(
            "codex_for_pymol.executor.time.time",
            return_value=1722664000.0,
        ), mock.patch(
            "codex_for_pymol.executor.time.time_ns",
            return_value=1722664000000000000,
        ):
            for _index in range(22):
                snapshot = self.executor.snapshot({"width": 320, "height": 240})
                path = Path(snapshot["path"])
                created.append(path)
                self.assertTrue(path.is_file())
                os.utime(path, ns=(1722664000000000000, 1722664000000000000))
        paths = set(self.executor.snapshot_directory.glob("*.png"))
        self.assertEqual(paths, set(created[-20:]))
        if os.name != "nt":
            self.assertTrue(
                all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in paths)
            )

    def test_risky_actions(self):
        self.assertIsNone(action_risk([{"action": "show"}]))
        self.assertIn("下载", action_risk([{"action": "fetch"}]))
        self.assertIn("本地", action_risk([{"action": "load"}]))


if __name__ == "__main__":
    unittest.main()
