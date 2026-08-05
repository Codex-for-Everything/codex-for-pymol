"""User-facing presentation helpers."""


from .i18n import text


TOOL_DISPLAY_KEYS = {
    "pymol_inspect": "tool.inspect",
    "pymol_apply": "tool.apply",
    "pymol_snapshot": "tool.snapshot",
    "pymol_python_exec": "tool.python",
}


def chat_prefix(role):
    """Return the shared role prefix used for complete and streaming messages."""
    return text("chat.prefix", role=role)


def chat_block(role, text):
    """Format a complete chat message without forcing its content to a new line."""
    return chat_prefix(role) + text


def tool_display_name(tool):
    """Return a localized tool label while preserving unknown identifiers."""
    key = TOOL_DISPLAY_KEYS.get(tool)
    return text(key) if key else tool or "PyMOL"
