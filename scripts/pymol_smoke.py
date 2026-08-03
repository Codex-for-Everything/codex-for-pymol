"""Manual smoke test using a real PyMOL Python runtime."""

import json
import sys
import tempfile
import traceback
from pathlib import Path

import pymol
from pymol import cmd

from pymol_codex.executor import PyMOLExecutor


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    pymol.finish_launching(["pymol", "-cq"])
    exit_code = 0
    try:
        with tempfile.TemporaryDirectory(prefix="pymol-codex-smoke-") as directory:
            executor = PyMOLExecutor(
                cmd,
                pymol_module=pymol,
                cache_directory=directory,
            )

            cmd.reinitialize()
            cmd.fragment("ala", "smoke_ala")
            inspected = executor.inspect({"selection": "smoke_ala"})
            require(inspected["atom_count"] > 0, "real PyMOL returned no atoms")
            require(
                inspected["objects"][0]["name"] == "smoke_ala",
                "real PyMOL object inspection failed",
            )

            instruction_checkpoints = []
            applied = executor.apply(
                {
                    "operations": [
                        {
                            "action": "show",
                            "representation": "sticks",
                            "selection": "smoke_ala",
                        },
                        {
                            "action": "color",
                            "color": "yellow",
                            "selection": "smoke_ala",
                        },
                        {
                            "action": "select",
                            "name": "smoke_selection",
                            "selection": "smoke_ala and name CA",
                        },
                    ]
                },
                before_execute=lambda: instruction_checkpoints.append(
                    executor.checkpoints.create("smoke-instruction")
                ),
            )
            require(applied["scene_revision"] == 1, "scene revision did not advance")
            require(
                len(instruction_checkpoints) == 1
                and Path(instruction_checkpoints[0]).is_file(),
                "instruction checkpoint was not created before mutation",
            )
            undone = executor.checkpoints.undo_last()
            executor.scene_revision += 1
            require(
                undone == instruction_checkpoints[0]
                and not Path(undone).exists()
                and "smoke_selection"
                not in cmd.get_names("selections"),
                "instruction undo did not restore the pre-mutation session",
            )

            python_result = executor.execute_python(
                '__codex_result__ = {"atoms": cmd.count_atoms("smoke_ala")}',
                "smoke-test",
            )
            require(python_result["ok"], "unrestricted Python smoke test failed")
            require(
                python_result["result"]["atoms"] == inspected["atom_count"],
                "unrestricted Python returned the wrong atom count",
            )
            require(
                Path(python_result["checkpoint"]).is_file(),
                "checkpoint was not created",
            )

            snapshot = executor.snapshot({"width": 640, "height": 480, "ray": False})
            require(
                snapshot["image_url"].startswith("data:image/png;base64,"),
                "snapshot did not return a data URL",
            )
            require(Path(snapshot["path"]).is_file(), "snapshot file was not created")

            print(
                json.dumps(
                    {
                        "pymol_version": inspected["pymol_version"],
                        "atom_count": inspected["atom_count"],
                        "scene_revision": executor.scene_revision,
                        "snapshot_bytes": Path(snapshot["path"]).stat().st_size,
                    },
                    ensure_ascii=False,
                ),
                file=sys.__stdout__,
                flush=True,
            )
    except BaseException:
        exit_code = 1
        traceback.print_exc(file=sys.__stderr__)
        sys.__stderr__.flush()
    finally:
        cmd.quit(exit_code)


if __name__ == "__main__":
    main()
