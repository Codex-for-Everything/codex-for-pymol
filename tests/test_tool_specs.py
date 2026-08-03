import unittest

from codex_for_pymol.tool_specs import (
    DEVELOPER_INSTRUCTIONS,
    dynamic_tools,
    python_mode_context,
)


class ToolSpecsTests(unittest.TestCase):
    def test_disabled_python_context_requires_controlled_tools_first(self):
        context = python_mode_context(False)
        entry = context["codex_for_pymol_python_mode"]

        self.assertEqual(entry["kind"], "application")
        self.assertIn("DISABLED", entry["value"])
        self.assertIn("First exhaust pymol_inspect", entry["value"])
        self.assertIn("Do not call pymol_python_exec", entry["value"])

    def test_enabled_python_context_still_prefers_controlled_tools(self):
        value = python_mode_context(True)["codex_for_pymol_python_mode"]["value"]

        self.assertIn("ENABLED", value)
        self.assertIn("Still prefer pymol_inspect", value)
        self.assertIn("separate user approval", value)

    def test_python_tool_and_instructions_describe_the_hard_gate(self):
        python_tool = next(
            tool
            for tool in dynamic_tools()
            if tool["name"] == "pymol_python_exec"
        )

        self.assertIn("Exhaust the controlled PyMOL tools", python_tool["description"])
        self.assertIn("stop the turn", python_tool["description"])
        self.assertIn("terminate the turn", DEVELOPER_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
