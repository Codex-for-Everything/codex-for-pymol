from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEXT_ROOTS = [
    ROOT / ".github",
    ROOT / "docs",
    ROOT / "scripts",
    ROOT / "src",
    ROOT / "tests",
]
TEXT_FILES = [
    ROOT / ".gitattributes",
    ROOT / ".gitignore",
    ROOT / "LICENSE",
    ROOT / "README.md",
    ROOT / "pyproject.toml",
]
IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
}
TEXT_SUFFIXES = {".md", ".py", ".toml", ".txt", ".yml", ".yaml"}


def repository_text_files():
    paths = list(TEXT_FILES)
    for root in TEXT_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in TEXT_SUFFIXES
                and not any(part in IGNORED_DIRECTORIES for part in path.parts)
            ):
                paths.append(path)
    return sorted(set(paths))


class RepositoryHygieneTests(unittest.TestCase):
    def test_no_generated_or_credential_files_are_present(self):
        forbidden_names = {
            ".DS_Store",
            ".env",
            ".pypirc",
            "auth.json",
            "credentials.json",
        }
        forbidden_suffixes = {
            ".key",
            ".p12",
            ".pem",
            ".pfx",
            ".pyc",
            ".pyo",
        }
        failures = []
        for path in ROOT.rglob("*"):
            relative = path.relative_to(ROOT)
            if any(part in {".git", "dist"} for part in relative.parts):
                continue
            if path.name in forbidden_names or path.suffix.lower() in forbidden_suffixes:
                failures.append(str(relative))
            if path.is_dir() and path.name in IGNORED_DIRECTORIES:
                failures.append(str(relative) + "/")
        self.assertEqual(failures, [])

    def test_text_has_no_local_home_paths_or_literal_credentials(self):
        local_path_patterns = [
            re.compile("/" + r"Users/[^/\s]+/"),
            re.compile("/" + r"home/[^/\s]+/"),
            re.compile(r"[A-Za-z]:" + r"\\Users\\[^\\\s]+\\"),
        ]
        secret_patterns = [
            re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
            re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
            re.compile(r"\bgh[opusr]_[A-Za-z0-9]{30,}\b"),
        ]
        failures = []
        for path in repository_text_files():
            text = path.read_text(encoding="utf-8")
            for pattern in local_path_patterns + secret_patterns:
                if pattern.search(text):
                    failures.append(
                        "{}: {}".format(path.relative_to(ROOT), pattern.pattern)
                    )
        self.assertEqual(failures, [])

    def test_renamed_runtime_has_no_stale_internal_identifiers(self):
        stale_tokens = [
            "pymol" + "_codex",
            "pymol" + "-codex",
            "PYMOL" + "_CODEX",
        ]
        failures = []
        checked = [
            ROOT / ".github",
            ROOT / "docs",
            ROOT / "scripts",
            ROOT / "src" / "codex_for_pymol",
            ROOT / "README.md",
            ROOT / "pyproject.toml",
        ]
        for root in checked:
            paths = [root] if root.is_file() else root.rglob("*")
            for path in paths:
                if not path.is_file() or (
                    path.suffix.lower() not in TEXT_SUFFIXES
                    and path.name not in {"README.md", "pyproject.toml"}
                ):
                    continue
                text = path.read_text(encoding="utf-8")
                for token in stale_tokens:
                    if token in text:
                        failures.append(
                            "{}: {}".format(path.relative_to(ROOT), token)
                        )
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
