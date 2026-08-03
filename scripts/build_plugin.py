"""Build an installable PyMOL plugin zip using only the standard library."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "pymol_codex"
DIST = ROOT / "dist"
OUTPUT = DIST / "pymol_codex_plugin.zip"


def main():
    DIST.mkdir(parents=True, exist_ok=True)
    with ZipFile(str(OUTPUT), "w", ZIP_DEFLATED) as archive:
        for path in sorted(SOURCE.rglob("*")):
            relative_source = path.relative_to(SOURCE)
            if (
                not path.is_file()
                or "__pycache__" in relative_source.parts
                or any(part.startswith(".") for part in relative_source.parts)
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            relative = Path("pymol_codex") / relative_source
            archive.write(str(path), str(relative))
    print(OUTPUT)


if __name__ == "__main__":
    main()
