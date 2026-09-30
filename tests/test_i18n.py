import unittest
from pathlib import Path

from codex_for_pymol import i18n
from codex_for_pymol.preferences import PreferenceStore


class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default="", type=None):
        value = self.values.get(key, default)
        return type(value) if type is not None else value

    def setValue(self, key, value):
        self.values[key] = value


class I18nTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_locale(i18n.ZH_CN)

    def test_catalogs_have_identical_keys_and_placeholders(self):
        chinese = i18n.CATALOGS[i18n.ZH_CN]
        english = i18n.CATALOGS[i18n.EN]
        self.assertEqual(set(chinese), set(english))
        for key in chinese:
            with self.subTest(key=key):
                self.assertTrue(chinese[key])
                self.assertTrue(english[key])
                self.assertEqual(
                    i18n.placeholders(chinese[key]),
                    i18n.placeholders(english[key]),
                )

    def test_locale_resolution_is_explicit_after_first_use(self):
        self.assertEqual(i18n.normalize_locale("", "zh-Hans"), i18n.ZH_CN)
        self.assertEqual(i18n.normalize_locale("", "en_US"), i18n.EN)
        self.assertEqual(i18n.normalize_locale(i18n.ZH_CN, "en_US"), i18n.ZH_CN)

    def test_chinese_preserves_existing_primary_labels(self):
        i18n.set_locale(i18n.ZH_CN)
        self.assertEqual(i18n.text("button.send"), "发送")
        self.assertEqual(i18n.text("status.ready"), "就绪")
        self.assertEqual(i18n.text("python.enable"), "启用不受限 Python（高风险）")

    def test_english_formats_dynamic_messages(self):
        i18n.set_locale(i18n.EN)
        self.assertEqual(
            i18n.text("error.prefix", detail="failed"),
            "Error: failed",
        )

    def test_status_text_has_locale_appropriate_terminal_punctuation(self):
        i18n.set_locale(i18n.ZH_CN)
        self.assertEqual(i18n.status_text("设置已保存"), "设置已保存。")
        self.assertEqual(i18n.status_text("正在处理…"), "正在处理…")
        i18n.set_locale(i18n.EN)
        self.assertEqual(i18n.status_text("Settings saved"), "Settings saved.")
        self.assertEqual(i18n.status_text("Working…"), "Working…")

    def test_first_use_follows_system_then_persists_user_choice(self):
        settings = FakeSettings()
        preferences = PreferenceStore(settings, "zh-Hans")
        self.assertEqual(preferences.language(), i18n.ZH_CN)
        self.assertEqual(settings.values["ui_language"], i18n.ZH_CN)

        preferences.set_language(i18n.EN)
        self.assertEqual(
            PreferenceStore(settings, "zh-Hans").language(),
            i18n.EN,
        )

    def test_existing_model_and_executable_keys_remain_compatible(self):
        settings = FakeSettings(
            {
                "codex_executable": "/opt/codex",
                "codex_model": "gpt-test",
                "codex_reasoning_effort": "high",
                "codex_service_tier": "fast",
            }
        )
        preferences = PreferenceStore(settings)
        self.assertEqual(preferences.codex_executable(), "/opt/codex")
        self.assertEqual(
            preferences.model_settings(),
            ("gpt-test", "high", "fast"),
        )
        preferences.set_model_settings("gpt-next", "medium", "")
        self.assertEqual(
            preferences.model_settings(),
            ("gpt-next", "medium", ""),
        )

    def test_plugin_owned_chinese_text_is_centralized(self):
        source_root = Path(__file__).parents[1] / "src" / "codex_for_pymol"
        offenders = []
        for path in source_root.glob("*.py"):
            if path.name == "i18n.py":
                continue
            has_chinese = any(
                "\u4e00" <= character <= "\u9fff"
                for character in path.read_text(encoding="utf-8")
            )
            if has_chinese:
                offenders.append(path.name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
