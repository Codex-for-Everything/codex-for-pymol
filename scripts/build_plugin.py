"""Build an installable PyMOL plugin zip using only the standard library."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "codex_for_pymol"
DIST = ROOT / "dist"
OUTPUT = DIST / "codex-for-pymol.zip"
LICENSE_FILE = ROOT / "LICENSE"


def main():
    if not SOURCE.is_dir() or SOURCE.is_symlink():
        raise RuntimeError("Plugin source must be a real directory: {}".format(SOURCE))
    if not LICENSE_FILE.is_file() or LICENSE_FILE.is_symlink():
        raise RuntimeError("LICENSE must be a regular file: {}".format(LICENSE_FILE))
    DIST.mkdir(parents=True, exist_ok=True)
    with ZipFile(str(OUTPUT), "w", ZIP_DEFLATED) as archive:
        archive.write(str(LICENSE_FILE), "codex_for_pymol/LICENSE")
        for path in sorted(SOURCE.rglob("*")):
            relative_source = path.relative_to(SOURCE)
            if (
                not path.is_file()
                or path.is_symlink()
                or "__pycache__" in relative_source.parts
                or any(part.startswith(".") for part in relative_source.parts)
                or path.suffix != ".py"
            ):
                continue
            relative = Path("codex_for_pymol") / relative_source
            archive.write(str(path), str(relative))
    print(OUTPUT)


if __name__ == "__main__":
    main()
