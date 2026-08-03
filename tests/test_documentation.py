from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
CHINESE_DOCS = sorted((ROOT / "docs").glob("*.zh-CN.md"))
INSTALL_DOCS = [
    ROOT / "README.md",
    ROOT / "docs" / "README.zh-CN.md",
    ROOT / "docs" / "INSTALL.md",
    ROOT / "docs" / "INSTALL.zh-CN.md",
]
RELEASE_DOCS = [
    ROOT / "docs" / "RELEASING.md",
    ROOT / "docs" / "RELEASING.zh-CN.md",
]
LATEST_RELEASE_URL = (
    "https://github.com/wuhuawei1996/codex-for-pymol/releases/latest"
)
CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
CHINESE_PUNCTUATION = "，。；：、！？）》】”’"


def _outside_fences(lines):
    outside = []
    fence = None
    for line in lines:
        match = re.match(r"^\s*(```+|~~~+)", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker[0]
            elif marker.startswith(fence):
                fence = None
            outside.append(False)
        else:
            outside.append(fence is None)
    return outside


def _is_structural(line):
    return not line.strip() or bool(
        re.match(
            r"^\s*(?:#{1,6}\s|\||>|[-+*]\s|\d+\.\s|---+\s*$|___+\s*$)",
            line,
        )
    )


def _is_list_item(line):
    return bool(re.match(r"^\s*(?:[-+*]|\d+\.)\s", line))


class DocumentationTests(unittest.TestCase):
    def test_relative_markdown_links_resolve(self):
        failures = []
        for path in [ROOT / "README.md"] + sorted(
            (ROOT / "docs").glob("*.md")
        ):
            text = path.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
                target = target.strip().strip("<>")
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                destination = path.parent / unquote(parsed.path)
                if not destination.exists():
                    failures.append(
                        "{} -> {}".format(path.relative_to(ROOT), target)
                    )
        self.assertEqual(failures, [])

    def test_installation_docs_identify_the_real_release_asset(self):
        for path in INSTALL_DOCS:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn(LATEST_RELEASE_URL, text)
                self.assertIn("codex-for-pymol.zip", text)
                self.assertIn("Source code", text)

    def test_release_docs_match_the_automated_assets(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        for asset in ("codex-for-pymol.zip", "SHA256SUMS.txt"):
            self.assertIn(asset, workflow)
            for path in RELEASE_DOCS:
                with self.subTest(asset=asset, path=path.relative_to(ROOT)):
                    self.assertIn(asset, path.read_text(encoding="utf-8"))

        for path in RELEASE_DOCS:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotRegex(text, r"git tag -a v\d+\.\d+\.\d+")

        self.assertNotIn("#PyMOL plugin installer", workflow)
        self.assertNotIn("#SHA-256 checksum", workflow)

    def test_privacy_docs_match_the_ephemeral_thread_contract(self):
        implementation = (
            ROOT / "src" / "codex_for_pymol" / "app_server.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"ephemeral": True', implementation)
        self.assertIn('"thread/delete"', implementation)
        for path in (ROOT / "README.md", ROOT / "docs" / "INSTALL.md"):
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text(encoding="utf-8")
                self.assertIn("ephemeral", text)
                self.assertTrue(
                    "delete" in text or "remove" in text,
                    "{} must explain rejected-thread cleanup".format(
                        path.relative_to(ROOT)
                    ),
                )
        for path in (
            ROOT / "docs" / "README.zh-CN.md",
            ROOT / "docs" / "INSTALL.zh-CN.md",
        ):
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text(encoding="utf-8")
                self.assertIn("不会写入历史记录", text)
                self.assertTrue(
                    "删除" in text or "移除" in text,
                    "{} 必须说明被拒绝对话的清理行为".format(
                        path.relative_to(ROOT)
                    ),
                )

    def test_chinese_prose_is_not_hard_wrapped(self):
        failures = []
        for path in CHINESE_DOCS:
            lines = path.read_text(encoding="utf-8").splitlines()
            outside = _outside_fences(lines)
            for index, (current, following) in enumerate(zip(lines, lines[1:]), 1):
                hard_wrapped_paragraph = (
                    outside[index - 1]
                    and outside[index]
                    and not _is_structural(current)
                    and not _is_structural(following)
                )
                hard_wrapped_list_item = (
                    outside[index - 1]
                    and outside[index]
                    and _is_list_item(current)
                    and not _is_structural(following)
                )
                hard_wrapped_quote = (
                    outside[index - 1]
                    and outside[index]
                    and current.lstrip().startswith(">")
                    and following.lstrip().startswith(">")
                )
                if hard_wrapped_paragraph or hard_wrapped_list_item or hard_wrapped_quote:
                    failures.append(f"{path.relative_to(ROOT)}:{index}")

        self.assertEqual(
            failures,
            [],
            "Chinese prose must use one source line per paragraph; soft wraps "
            "render as visible spaces on GitHub",
        )

    def test_chinese_prose_has_no_spacing_artifacts(self):
        cjk_space = re.compile(rf"[{CJK}] +[{CJK}]")
        punctuation_space = re.compile(
            rf"[{re.escape(CHINESE_PUNCTUATION)}] +"
        )
        space_before_punctuation = re.compile(
            rf" +[{re.escape(CHINESE_PUNCTUATION)}]"
        )
        failures = []
        for path in CHINESE_DOCS:
            lines = path.read_text(encoding="utf-8").splitlines()
            outside = _outside_fences(lines)
            for index, line in enumerate(lines, 1):
                if outside[index - 1] and (
                    cjk_space.search(line)
                    or punctuation_space.search(line)
                    or space_before_punctuation.search(line)
                ):
                    failures.append(f"{path.relative_to(ROOT)}:{index}")

        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
