"""Public interface of the branding module (ADR 0032). The proposal deck renderer will read the
branding through here (step PD3); nothing else is exported yet."""

from app.modules.branding import rules

check_color = rules.check_color
text_color_for = rules.text_color_for

__all__ = ["check_color", "text_color_for"]
