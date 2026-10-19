"""Helpers for user-entered search text."""


def escape_like(text: str) -> str:
    """Make %, _ and \\ in user input match literally in ILIKE (no wildcard injection)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
