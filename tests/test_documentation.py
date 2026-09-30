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
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
LATEST_RELEASE_URL = (
    "https://github.com/Codex-for-Everything/codex-for-pymol/releases/latest"
)
VERSIONED_ASSET_EXAMPLE = "codex-for-pymol-X.Y.Z.zip"
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
    @unittest.skipUnless(
        (ROOT / ".github" / "workflows").is_dir(),
        "GitHub workflows are intentionally absent from source distributions",
    )
    def test_workflows_use_node24_action_generations(self):
        workflows = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        )
        for action in (
            "actions/checkout@v5",
            "actions/setup-python@v6",
            "actions/upload-artifact@v5",
            "actions/download-artifact@v5",
        ):
            with self.subTest(action=action):
                self.assertIn(action, workflows)
        for deprecated in (
            "actions/checkout@v4",
            "actions/setup-python@v5",
            "actions/upload-artifact@v4",
            "actions/download-artifact@v4",
        ):
            with self.subTest(deprecated=deprecated):
                self.assertNotIn(deprecated, workflows)

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
                self.assertIn(VERSIONED_ASSET_EXAMPLE, text)
                self.assertNotIn("`codex-for-pymol.zip`", text)
                self.assertIn("Source code", text)

    def test_codex_requirements_distinguish_windows_and_macos(self):
        english = [ROOT / "README.md", ROOT / "docs" / "INSTALL.md"]
        chinese = [
            ROOT / "docs" / "README.zh-CN.md",
            ROOT / "docs" / "INSTALL.zh-CN.md",
        ]
        for path in english:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn("standalone [Codex CLI]", text)
                self.assertTrue(
                    "not sufficient" in text or "does not satisfy" in text
                )
                self.assertIn("Contents/Resources/codex", text)
        for path in chinese:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn("必须安装独立的 [Codex CLI]", text)
                self.assertIn("Contents/Resources/codex", text)

    def test_language_and_model_setting_timing_matches_the_ui(self):
        for path in (ROOT / "README.md", ROOT / "docs" / "INSTALL.md"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn("Chinese system locale", text)
                self.assertIn("English otherwise", text)

        install_en = (ROOT / "docs" / "INSTALL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "Interface-language changes apply as soon as you save",
            install_en,
        )
        self.assertIn(
            "response-speed changes take effect on the next message",
            install_en,
        )

        for path in (
            ROOT / "docs" / "README.zh-CN.md",
            ROOT / "docs" / "INSTALL.zh-CN.md",
        ):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn("中文系统使用简体中文，其他系统使用英文", text)

        install_zh = (ROOT / "docs" / "INSTALL.zh-CN.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("界面语言在保存后立即生效", install_zh)
        self.assertIn(
            "模型、推理强度和响应速度从下一条消息开始生效",
            install_zh,
        )

    def test_windows_upgrade_notice_names_fixed_version(self):
        for path in INSTALL_DOCS:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn("0.3.2", text)
                self.assertIn("0.4.0", text)
                self.assertIn("Windows", text)
        if RELEASE_WORKFLOW.is_file():
            workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
            self.assertIn("versions 0.3.2 and earlier", workflow)
            self.assertIn("Upgrade to version 0.4.0 or later", workflow)

    def test_dynamic_tool_host_upgrade_notice_is_bilingual_and_synced(self):
        for path in INSTALL_DOCS:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn("0.5.1", text)
                self.assertIn("0.5.2", text)
                if path.name.endswith("zh-CN.md"):
                    self.assertIn("本地工具宿主", text)
                    self.assertIn("实际报告的功能", text)
                else:
                    self.assertIn("local tool host", text)
                    self.assertIn("capabilities reported", text)
        if RELEASE_WORKFLOW.is_file():
            workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
            self.assertIn("重要兼容性更新：使用 0.5.1", workflow)
            self.assertIn("Important compatibility update: users of version 0.5.1", workflow)
            self.assertIn("0.5.2 or later", workflow)

    @unittest.skipUnless(
        RELEASE_WORKFLOW.is_file(),
        "GitHub workflow is intentionally absent from source distributions",
    )
    def test_release_docs_match_the_automated_assets(self):
        workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("dist/codex-for-pymol-*.zip", workflow)
        self.assertIn(
            'package_path="release-assets/codex-for-pymol-${release_version}.zip"',
            workflow,
        )
        for path in RELEASE_DOCS:
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text(encoding="utf-8")
                self.assertIn(VERSIONED_ASSET_EXAMPLE, text)
                self.assertIn("SHA256SUMS.txt", text)

        for path in RELEASE_DOCS:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotRegex(text, r"git tag -a v\d+\.\d+\.\d+")

        self.assertNotIn("#PyMOL plugin installer", workflow)
        self.assertNotIn("#SHA-256 checksum", workflow)
        self.assertIn("RELEASE_INSTALL_NOTES: |-", workflow)
        self.assertIn("0.6.0 新增图片输入", workflow)
        self.assertIn("Version 0.6.0 adds image input", workflow)
        self.assertRegex(
            workflow,
            r"Windows：0\.3\.2[^\n]+0\.4\.0[^\n]+\n\s*\n\s*安装：",
        )
        self.assertRegex(
            workflow,
            r"Windows: versions 0\.3\.2[^\n]+0\.4\.0[^\n]+\n\s*\n\s*Installation:",
        )
        self.assertIn('--notes "$release_notes"', workflow)

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
