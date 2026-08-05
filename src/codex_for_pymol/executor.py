"""PyMOL inspection, controlled actions, screenshots, and Python execution."""

import base64
import contextlib
import io
import json
import os
import re
import tempfile
import time
import traceback
import uuid
from pathlib import Path

from .i18n import text
from .serializer import to_jsonable


def _ensure_private_directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        try:
            path.chmod(0o700)
        except OSError:
            pass
    return path


def _secure_file(path):
    if os.name != "nt":
        try:
            Path(path).chmod(0o600)
        except OSError:
            pass


class BoundedTextIO(io.TextIOBase):
    """Text sink that retains at most ``limit`` characters."""

    def __init__(self, limit):
        super().__init__()
        self.limit = int(limit)
        self._parts = []
        self._stored = 0
        self._discarded = 0

    def write(self, value):
        text = str(value)
        remaining = self.limit - self._stored
        if remaining > 0:
            kept = text[:remaining]
            self._parts.append(kept)
            self._stored += len(kept)
        self._discarded += max(0, len(text) - max(0, remaining))
        return len(text)

    def writable(self):
        return True

    @property
    def encoding(self):
        return "utf-8"

    def getvalue(self):
        value = "".join(self._parts)
        if self._discarded:
            value += "\n[{} additional characters truncated]".format(self._discarded)
        return value


SAFE_SETTINGS = {
    "cartoon_transparency",
    "dash_width",
    "label_color",
    "label_size",
    "ray_opaque_background",
    "stick_radius",
    "surface_transparency",
    "transparency",
}

REPRESENTATIONS = {
    "cartoon",
    "dots",
    "everything",
    "labels",
    "lines",
    "mesh",
    "nonbonded",
    "ribbon",
    "spheres",
    "sticks",
    "surface",
}

def action_risk(operations):
    """Return a human-readable risk description or ``None``."""
    actions = {item.get("action") for item in operations if isinstance(item, dict)}
    if "load" in actions and "fetch" in actions:
        return text("risk.local_and_network")
    if "load" in actions:
        return text("risk.local")
    if "fetch" in actions:
        return text("risk.network")
    return None


class CheckpointManager:
    def __init__(self, cmd, directory, keep=5):
        self.cmd = cmd
        self.directory = Path(directory)
        self.keep = keep
        self.last_path = None
        self._consumed = set()
        self._last_timestamp_ns = 0

    def create(self, label="python"):
        _ensure_private_directory(self.directory)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        timestamp_ns = max(time.time_ns(), self._last_timestamp_ns + 1)
        self._last_timestamp_ns = timestamp_ns
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label)[:40]
        path = self.directory / "{}-{:019d}-{}-{}.pse".format(
            stamp, timestamp_ns, uuid.uuid4().hex, safe_label
        )
        self.cmd.save(str(path), quiet=1)
        if not path.is_file():
            raise RuntimeError(
                "PyMOL did not create the requested checkpoint"
            )
        _secure_file(path)
        self.last_path = path
        self._prune()
        return str(path)

    def _latest_path(self):
        path = self.last_path
        if (
            not path
            or path in self._consumed
            or not path.is_file()
        ):
            try:
                paths = [
                    item
                    for item in self.directory.glob("*.pse")
                    if item.is_file() and item not in self._consumed
                ]
                path = max(
                    paths,
                    key=lambda item: (item.stat().st_mtime_ns, item.name),
                    default=None,
                )
            except OSError:
                path = None
        return path

    def has_checkpoint(self):
        """Return whether an instruction checkpoint can still be undone."""
        return self._latest_path() is not None

    def undo_last(self):
        """Restore and consume the newest instruction checkpoint."""
        path = self._latest_path()
        if path is None:
            raise RuntimeError("No PyMOL checkpoint is available")
        self.cmd.load(str(path), quiet=1)
        self._consumed.add(path)
        try:
            path.unlink()
        except OSError:
            pass
        self.last_path = self._latest_path()
        return str(path)

    def _prune(self):
        paths = sorted(
            self.directory.glob("*.pse"),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
        )
        for path in paths[:-self.keep]:
            try:
                path.unlink()
            except OSError:
                pass


class PyMOLExecutor:
    """Execute bounded operations against a supplied ``pymol.cmd`` object."""

    def __init__(
        self,
        cmd,
        pymol_module=None,
        cache_directory=None,
        checkpoint_directory=None,
    ):
        self.cmd = cmd
        self.pymol_module = pymol_module
        root = Path(cache_directory or tempfile.gettempdir()) / "codex-for-pymol"
        _ensure_private_directory(root)
        self.snapshot_directory = root / "snapshots"
        checkpoint_root = (
            Path(checkpoint_directory)
            if checkpoint_directory is not None
            else root / "checkpoints"
        )
        self.checkpoints = CheckpointManager(cmd, checkpoint_root)
        self.scene_revision = 0
        self.session = {}
        self._last_snapshot_timestamp_ns = 0

    @staticmethod
    def _selection(value, default="all"):
        selection = str(value or default)
        if len(selection) > 2000:
            raise ValueError("Selection expression is too long")
        return selection

    @staticmethod
    def _name(value, label="Name"):
        name = str(value or "").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
            raise ValueError("{} must be a simple PyMOL identifier".format(label))
        return name

    def inspect(self, arguments):
        selection = self._selection(arguments.get("selection"))
        max_records = max(1, min(int(arguments.get("max_records", 500)), 2000))
        count = int(self.cmd.count_atoms(selection))
        objects = []
        for name in self.cmd.get_names("objects"):
            item = {"name": name}
            try:
                item["type"] = self.cmd.get_type(name)
                item["states"] = int(self.cmd.count_states(name))
                item["atoms"] = int(self.cmd.count_atoms(name))
            except Exception as exc:
                item["error"] = str(exc)
            objects.append(item)

        result = {
            "pymol_version": to_jsonable(self.cmd.get_version()),
            "selection": selection,
            "atom_count": count,
            "objects": objects,
            "selections": list(self.cmd.get_names("selections")),
            "chains": list(self.cmd.get_chains(selection)),
            "view": to_jsonable(self.cmd.get_view()),
            "scene_revision": self.scene_revision,
        }

        if arguments.get("include_residues", True):
            residues = set()
            self.cmd.iterate(
                "({})".format(selection),
                "residues.add((model, chain, resi, resn))",
                space={"residues": residues},
            )
            unique = sorted(residues)
            result["residues"] = [
                {"model": model, "chain": chain, "resi": resi, "resn": resn}
                for model, chain, resi, resn in unique[:max_records]
            ]
            result["residue_count"] = len(unique)
            result["residues_truncated"] = len(unique) > max_records

        if arguments.get("include_ligands", True):
            ligands = {}

            def collect_ligand(model, chain, resi, resn):
                key = (model, chain, resi, resn)
                ligands[key] = ligands.get(key, 0) + 1

            self.cmd.iterate(
                "({}) and organic".format(selection),
                "collect_ligand(model, chain, resi, resn)",
                space={"collect_ligand": collect_ligand},
            )
            unique = sorted(
                ligands.items(),
                key=lambda item: (-item[1], item[0]),
            )
            result["ligands"] = [
                {
                    "model": key[0],
                    "chain": key[1],
                    "resi": key[2],
                    "resn": key[3],
                    "atom_count": atom_count,
                }
                for key, atom_count in unique[:max_records]
            ]
            result["ligand_count"] = len(unique)
            result["ligands_truncated"] = len(unique) > max_records

        return result

    def apply(self, arguments, before_execute=None):
        operations = arguments.get("operations")
        if not isinstance(operations, list) or not 1 <= len(operations) <= 20:
            raise ValueError("operations must contain between 1 and 20 items")

        prepared = []
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError("Each operation must be an object")
            action = operation.get("action")
            method = getattr(self, "_apply_{}".format(action), None)
            validator = getattr(self, "_validate_{}".format(action), None)
            if method is None or validator is None:
                raise ValueError("Unsupported action: {}".format(action))
            validator(operation)
            prepared.append((action, method, operation))

        if before_execute is not None:
            before_execute()

        completed = []
        for index, (action, method, operation) in enumerate(prepared):
            try:
                method(operation)
                completed.append(action)
            except Exception as exc:
                # A PyMOL command can mutate state before raising. Conservatively
                # advance the revision whenever execution of a prepared operation
                # was attempted and report exactly how far the batch progressed.
                self.scene_revision += 1
                return {
                    "ok": False,
                    "completed": completed,
                    "failed_index": index,
                    "failed_action": action,
                    "error": "{}: {}".format(type(exc).__name__, exc),
                    "scene_revision": self.scene_revision,
                }

        self.scene_revision += 1
        return {
            "ok": True,
            "completed": completed,
            "scene_revision": self.scene_revision,
        }

    def _validate_fetch(self, item):
        pdb_id = str(item.get("pdb_id", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9]{4,12}", pdb_id):
            raise ValueError("pdb_id must contain 4-12 letters or digits")
        self._name(item.get("name") or pdb_id, "Object name")

    def _apply_fetch(self, item):
        self._validate_fetch(item)
        pdb_id = str(item.get("pdb_id", "")).strip()
        name = self._name(item.get("name") or pdb_id, "Object name")
        self.cmd.fetch(pdb_id, name=name, async_=0)

    def _validate_load(self, item):
        path = Path(str(item.get("path", ""))).expanduser()
        if not path.is_file():
            raise ValueError("Structure file does not exist: {}".format(path))
        if item.get("name"):
            self._name(item.get("name"), "Object name")

    def _apply_load(self, item):
        self._validate_load(item)
        path = Path(str(item.get("path", ""))).expanduser()
        name = item.get("name")
        if name:
            self.cmd.load(str(path), self._name(name, "Object name"))
        else:
            self.cmd.load(str(path))

    def _validate_show(self, item):
        representation = str(item.get("representation", "cartoon"))
        if representation not in REPRESENTATIONS:
            raise ValueError("Unsupported representation: {}".format(representation))
        self._selection(item.get("selection"))

    def _apply_show(self, item):
        self._validate_show(item)
        representation = str(item.get("representation", "cartoon"))
        self.cmd.show(representation, self._selection(item.get("selection")))

    def _validate_hide(self, item):
        representation = str(item.get("representation", "everything"))
        if representation not in REPRESENTATIONS:
            raise ValueError("Unsupported representation: {}".format(representation))
        self._selection(item.get("selection"))

    def _apply_hide(self, item):
        self._validate_hide(item)
        representation = str(item.get("representation", "everything"))
        self.cmd.hide(representation, self._selection(item.get("selection")))

    def _validate_color(self, item):
        color = str(item.get("color", "")).strip()
        if not color or len(color) > 100:
            raise ValueError("A valid color name is required")
        self._selection(item.get("selection"))

    def _apply_color(self, item):
        self._validate_color(item)
        color = str(item.get("color", "")).strip()
        self.cmd.color(color, self._selection(item.get("selection")))

    def _validate_select(self, item):
        self._name(item.get("name"), "Selection name")
        self._selection(item.get("selection"))

    def _apply_select(self, item):
        self._validate_select(item)
        name = self._name(item.get("name"), "Selection name")
        self.cmd.select(name, self._selection(item.get("selection")))

    def _validate_zoom(self, item):
        max(0.0, min(float(item.get("buffer", 0.0)), 100.0))
        self._selection(item.get("selection"))

    def _apply_zoom(self, item):
        self._validate_zoom(item)
        buffer_value = max(0.0, min(float(item.get("buffer", 0.0)), 100.0))
        self.cmd.zoom(self._selection(item.get("selection")), buffer=buffer_value)

    def _validate_orient(self, item):
        self._selection(item.get("selection"))

    def _apply_orient(self, item):
        self._validate_orient(item)
        self.cmd.orient(self._selection(item.get("selection")))

    def _validate_center(self, item):
        self._selection(item.get("selection"))

    def _apply_center(self, item):
        self._validate_center(item)
        self.cmd.center(self._selection(item.get("selection")))

    def _label_expression(self, item):
        mode = str(item.get("label_mode", "residue"))
        expressions = {
            "residue": '"%s%s" % (resn, resi)',
            "atom": "name",
            "chain_residue": '"%s/%s%s" % (chain, resn, resi)',
        }
        if mode == "custom":
            text = str(item.get("text", ""))
            if not text or len(text) > 200:
                raise ValueError("Custom label text must contain 1-200 characters")
            return json.dumps(text)
        if mode in expressions:
            return expressions[mode]
        raise ValueError("Unsupported label mode: {}".format(mode))

    def _validate_label(self, item):
        self._selection(item.get("selection"))
        self._label_expression(item)

    def _apply_label(self, item):
        self._validate_label(item)
        # JSON quoting in _label_expression produces a plain string literal and
        # prevents injection through PyMOL's label expression evaluator.
        self.cmd.label(
            self._selection(item.get("selection")), self._label_expression(item)
        )

    def _validate_distance(self, item):
        self._name(item.get("name", "distance"), "Distance name")
        selection1 = self._selection(item.get("selection1"), "")
        selection2 = self._selection(item.get("selection2"), "")
        if not selection1 or not selection2:
            raise ValueError("distance requires selection1 and selection2")

    def _apply_distance(self, item):
        self._validate_distance(item)
        name = self._name(item.get("name", "distance"), "Distance name")
        selection1 = self._selection(item.get("selection1"), "")
        selection2 = self._selection(item.get("selection2"), "")
        self.cmd.distance(name, selection1, selection2)

    def _validate_set(self, item):
        setting = str(item.get("setting", ""))
        if setting not in SAFE_SETTINGS:
            raise ValueError("Setting is not in the controlled allowlist: {}".format(setting))
        self._selection(item.get("selection"))

    def _apply_set(self, item):
        self._validate_set(item)
        setting = str(item.get("setting", ""))
        self.cmd.set(setting, item.get("value"), self._selection(item.get("selection")))

    @staticmethod
    def _validate_background(item):
        color = str(item.get("color", "white"))
        if not color or len(color) > 100:
            raise ValueError("A valid background color is required")

    def _apply_background(self, item):
        self._validate_background(item)
        color = str(item.get("color", "white"))
        self.cmd.bg_color(color)

    def snapshot(self, arguments):
        width = max(320, min(int(arguments.get("width", 1400)), 2400))
        height = max(240, min(int(arguments.get("height", 1000)), 1800))
        ray = 1 if arguments.get("ray", False) else 0
        _ensure_private_directory(self.snapshot_directory)
        timestamp_ns = max(
            time.time_ns(),
            self._last_snapshot_timestamp_ns + 1,
        )
        self._last_snapshot_timestamp_ns = timestamp_ns
        filename = "snapshot-{:019d}-{}-{}.png".format(
            timestamp_ns, os.getpid(), uuid.uuid4().hex
        )
        path = self.snapshot_directory / filename
        self.cmd.png(str(path), width=width, height=height, ray=ray, quiet=1)
        try:
            self.cmd.refresh()
        except Exception:
            pass
        if not path.is_file():
            raise RuntimeError("PyMOL did not create the screenshot")
        _secure_file(path)
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        self._prune_snapshots()
        return {
            "path": str(path),
            "width": width,
            "height": height,
            "ray": bool(ray),
            "image_url": "data:image/png;base64," + data,
        }

    def _prune_snapshots(self, keep=20):
        paths = sorted(
            self.snapshot_directory.glob("*.png"),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
        )
        for path in paths[:-keep]:
            try:
                path.unlink()
            except OSError:
                pass

    def execute_python(self, code, label="python", checkpoint=None):
        if not isinstance(code, str) or not code.strip():
            raise ValueError("Python code is empty")
        if len(code) > 100000:
            raise ValueError("Python code exceeds the 100,000 character limit")

        if checkpoint is None:
            checkpoint = self.checkpoints.create(label)
        stdout = BoundedTextIO(200000)
        stderr = BoundedTextIO(200000)
        namespace = {
            "__name__": "__codex_for_pymol__",
            "cmd": self.cmd,
            "pymol": self.pymol_module,
            "session": self.session,
        }
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exec(compile(code, "<codex-for-pymol>", "exec"), namespace, namespace)
            result = namespace.get("__codex_result__")
            cleaned_session = to_jsonable(self.session)
            self.session = cleaned_session if isinstance(cleaned_session, dict) else {}
            self.scene_revision += 1
            return {
                "ok": True,
                "result": to_jsonable(result),
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
                "checkpoint": checkpoint,
                "scene_revision": self.scene_revision,
            }
        except BaseException:
            cleaned_session = to_jsonable(self.session)
            self.session = cleaned_session if isinstance(cleaned_session, dict) else {}
            # The code may have changed PyMOL before failing.
            self.scene_revision += 1
            return {
                "ok": False,
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
                "traceback": traceback.format_exc()[-200000:],
                "checkpoint": checkpoint,
                "scene_revision": self.scene_revision,
            }
