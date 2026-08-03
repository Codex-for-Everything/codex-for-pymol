import unittest

from pymol_codex.presentation import chat_block, chat_prefix, tool_display_name


class PresentationTests(unittest.TestCase):
    def test_complete_and_streaming_messages_share_inline_prefix(self):
        self.assertEqual(chat_prefix("Codex"), "Codex：")
        self.assertEqual(chat_block("你", "你好。"), "你：你好。")

    def test_tool_names_are_localized_without_hiding_unknown_names(self):
        self.assertEqual(tool_display_name("pymol_inspect"), "读取 PyMOL 状态")
        self.assertEqual(tool_display_name("custom_tool"), "custom_tool")


if __name__ == "__main__":
    unittest.main()
