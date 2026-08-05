"""Typed access to the plugin's persistent user preferences."""

from .i18n import normalize_locale


class PreferenceStore:
    def __init__(self, settings, system_locale=""):
        self.settings = settings
        self.system_locale = str(system_locale or "")

    def language(self):
        saved = self.settings.value("ui_language", "", type=str) or ""
        language = normalize_locale(saved, self.system_locale)
        if saved != language:
            self.settings.setValue("ui_language", language)
        return language

    def set_language(self, language):
        language = normalize_locale(language)
        self.settings.setValue("ui_language", language)
        return language

    def codex_executable(self):
        return self.settings.value("codex_executable", "", type=str) or ""

    def set_codex_executable(self, path):
        self.settings.setValue("codex_executable", str(path or ""))

    def model_settings(self):
        return (
            self.settings.value("codex_model", "", type=str) or "",
            self.settings.value("codex_reasoning_effort", "", type=str) or "",
            self.settings.value("codex_service_tier", "", type=str) or "",
        )

    def set_model_settings(self, model, effort, service_tier):
        self.settings.setValue("codex_model", model)
        self.settings.setValue("codex_reasoning_effort", effort)
        self.settings.setValue("codex_service_tier", service_tier)
