"""User-facing presentation helpers."""


TOOL_DISPLAY_NAMES = {
    "pymol_inspect": "读取 PyMOL 状态",
    "pymol_apply": "修改 PyMOL 场景",
    "pymol_snapshot": "获取 PyMOL 截图",
    "pymol_python_exec": "执行不受限 Python",
}


def chat_prefix(role):
    """Return the shared role prefix used for complete and streaming messages."""
    return "{}：".format(role)


def chat_block(role, text):
    """Format a complete chat message without forcing its content to a new line."""
    return chat_prefix(role) + text


def tool_display_name(tool):
    """Return a localized tool label while preserving unknown identifiers."""
    return TOOL_DISPLAY_NAMES.get(tool, tool or "PyMOL")
