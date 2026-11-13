"""Pure rules for an organisation's branding (ADR 0032, PD1): colour, text and logo.

Nothing here touches the database. The logo is never trusted: it is decoded, checked and WRITTEN
AGAIN as a clean PNG, so whatever was hidden in the uploaded file (metadata, a second image, a
script in a crafted header) is gone. All text is cleaned with the shared screening and later drawn
as plain text.
"""

import io
import re
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from app.core.screening import screen

DEFAULT_COLOR = "1f3a5f"
_COLOR = re.compile(r"[0-9a-f]{6}")

# Field limits (characters). The database repeats them as checks (migration 0063).
LIMITS = {
    "about_text": 1500,
    "terms_text": 1500,
    "contact_line": 200,
    "footer_line": 200,
}

MAX_UPLOAD_BYTES = 1_048_576  # what a person may send
MAX_PIXELS = 4_000_000  # checked from the header, before the picture is decoded
MAX_SIDE = 2_000
MIN_SIDE = 16
OUTPUT_SIDE = 800  # the stored logo fits in this square
MAX_STORED_BYTES = 500_000
ALLOWED_FORMATS = ("PNG", "JPEG")


class BrandingRuleError(ValueError):
    """A value the rules refuse. ``code`` is stable; the message is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def check_color(value: str) -> str:
    """``#1F3A5F`` or ``1f3a5f`` -> ``1f3a5f``; anything else is refused."""
    text = value.strip().removeprefix("#").lower() if isinstance(value, str) else ""
    if not _COLOR.fullmatch(text):
        raise BrandingRuleError("branding_color_invalid", "The colour must be six hex digits.")
    return text


@dataclass(frozen=True)
class CleanText:
    text: str
    cleaned: bool  # something was taken out (a link, markup, hidden characters)


def clean_text(field: str, value: str) -> CleanText:
    """Clean one text field. Links, markup and hidden characters are taken out; an e-mail address
    stays (a contact line needs one); words that read like instructions to an AI are refused."""
    if not isinstance(value, str):
        raise BrandingRuleError("branding_text_invalid", "The text is not valid.")
    limit = LIMITS[field]
    result = screen(value, strip_links=True, strip_addresses=False)
    if any(finding.code == "instruction_phrase" for finding in result.findings):
        raise BrandingRuleError(
            "branding_text_refused", "The text contains words that read like instructions."
        )
    text = result.clean.strip()
    if len(text) > limit:
        raise BrandingRuleError("branding_text_too_long", f"The text can have {limit} characters.")
    return CleanText(text, text != value.strip())


@dataclass(frozen=True)
class Logo:
    png: bytes
    width: int
    height: int


def reencode_logo(data: bytes) -> Logo:
    """Decode an uploaded logo and return a clean, small PNG. Refuses anything that is not a PNG or
    JPEG, is too big in bytes or pixels, cannot be decoded, or is not a sensible logo size."""
    if not data:
        raise BrandingRuleError("logo_invalid", "The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise BrandingRuleError("logo_too_large", "The logo can be at most 1 MB.")
    try:
        image = Image.open(io.BytesIO(data))
        # The header gives the size without decoding: a "decompression bomb" is refused here.
        width, height = image.size
        if image.format not in ALLOWED_FORMATS:
            raise BrandingRuleError("logo_type_not_allowed", "The logo must be a PNG or a JPEG.")
        if width * height > MAX_PIXELS or max(width, height) > MAX_SIDE:
            raise BrandingRuleError(
                "logo_too_large", f"The logo can be at most {MAX_SIDE} pixels on a side."
            )
        if min(width, height) < MIN_SIDE:
            raise BrandingRuleError(
                "logo_too_small", f"The logo must be at least {MIN_SIDE} pixels."
            )
        image.load()
        picture = image.convert("RGBA")
    except BrandingRuleError:
        raise
    except Image.DecompressionBombError:
        raise BrandingRuleError(
            "logo_too_large", f"The logo can be at most {MAX_SIDE} pixels on a side."
        ) from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise BrandingRuleError("logo_invalid", "The file is not a readable picture.") from None
    picture.thumbnail((OUTPUT_SIDE, OUTPUT_SIDE))
    out = io.BytesIO()
    picture.save(out, format="PNG", optimize=True)  # no metadata is carried over
    png = out.getvalue()
    if len(png) > MAX_STORED_BYTES:
        raise BrandingRuleError("logo_too_large", "The logo is too detailed. Use a simpler one.")
    return Logo(png, picture.width, picture.height)


def text_color_for(background_hex: str) -> str:
    """Black or white text, whichever reads better on ``background_hex`` (WCAG luminance)."""
    value = check_color(background_hex)
    r, g, b = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return "111111" if luminance > 0.179 else "ffffff"
