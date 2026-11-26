"""Pure rules for the property photo enhancer (ADR 0039, PE1).

Nothing here touches the database or the file store. The idea in one paragraph: an agent's
phone photo may be made a *truer* picture of what the camera saw (brighter, straighter,
smaller, cropped, with the agency's mark in a corner) but never a *different* picture. So
there is a short list of allowed edits, each with a hard cap, and no edit that could add or
remove anything from the scene. The photo is decoded and written again, so camera metadata
(including the GPS position of the property) is gone and one short label saying "adjusted
copy" is written into the new file.
"""

from __future__ import annotations

import io
import math
import time
from dataclasses import dataclass
from typing import Any, Literal

from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
    UnidentifiedImageError,
)

from app.core.screening import screen

# --- Limits (ADR 0039 PE7) --------------------------------------------------------------------
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 50_000_000  # checked from the header, before the picture is decoded
MAX_SIDE = 12_000
MIN_SIDE = 64
ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")
OUTPUT_MAX_SIDE = 4_000
OUTPUT_MAX_BYTES = 5 * 1024 * 1024
PREVIEW_SIDE = 800
JPEG_QUALITIES = (85, 78, 70, 62)  # tried in turn until the copy fits OUTPUT_MAX_BYTES

# --- Caps of the allowed edits (fixed values, not settings) ------------------------------------
MAX_BRIGHTNESS_PERCENT = 30
MAX_CONTRAST_PERCENT = 20
MAX_STRAIGHTEN_DEGREES = 5.0
EXPOSURE_TARGET = 110  # average brightness (0-255) that auto exposure aims for, never above
MIN_GAMMA = 0.7
MIN_CROP_KEPT = 0.6  # a crop must keep at least 60 % of the width and of the height
PRESET_SIDES = {"original": OUTPUT_MAX_SIDE, "brochure": 2_000, "whatsapp": 1_280, "thumbnail": 400}
CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")
MAX_WATERMARK_TEXT = 40
LOGO_WATERMARK_SHARE = 0.18  # the logo is at most this share of the picture's width

# The label (ADR 0039 PE4). The file note is in English; the deck caption is a fixed sentence.
FILE_LABEL = "Enhanced copy of an original photo. Adjustments only: nothing added or removed."
DECK_CAPTION = "Photo adjusted for brightness and colour"
_EXIF_IMAGE_DESCRIPTION = 0x010E


class PhotoRuleError(ValueError):
    """A value the rules refuse. ``code`` is stable; the message is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --- What may be asked for --------------------------------------------------------------------
@dataclass(frozen=True)
class Watermark:
    corner: str = "bottom_right"
    kind: Literal["text", "logo"] = "text"
    text: str = ""


@dataclass(frozen=True)
class Operations:
    auto_exposure: bool = False
    auto_white_balance: bool = False
    brightness_percent: int = 0
    contrast_percent: int = 0
    straighten_degrees: float = 0.0
    # Fractions of the (straightened) picture: left, top, right, bottom edge of what is kept.
    crop: tuple[float, float, float, float] | None = None
    sharpen: bool = False
    preset: str = "original"
    watermark: Watermark | None = None


_ALLOWED_KEYS = set(Operations.__dataclass_fields__)


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise PhotoRuleError("operation_invalid", f"{name} must be a number.")
    return float(value)


def _watermark_from(data: Any) -> Watermark:
    if not isinstance(data, dict) or set(data) - {"corner", "kind", "text"}:
        raise PhotoRuleError("operation_invalid", "The watermark is not valid.")
    corner = data.get("corner", "bottom_right")
    kind = data.get("kind", "text")
    text = data.get("text", "")
    if corner not in CORNERS or kind not in ("text", "logo") or not isinstance(text, str):
        raise PhotoRuleError("operation_invalid", "The watermark is not valid.")
    if kind == "logo":
        return Watermark(corner, "logo", "")
    cleaned = screen(text, strip_links=True, strip_addresses=False)
    if any(f.code == "instruction_phrase" for f in cleaned.findings):
        raise PhotoRuleError("watermark_refused", "The watermark text is not allowed.")
    text = cleaned.clean.strip()
    if not text or len(text) > MAX_WATERMARK_TEXT:
        raise PhotoRuleError(
            "watermark_text_invalid",
            f"The watermark text needs 1 to {MAX_WATERMARK_TEXT} characters.",
        )
    return Watermark(corner, "text", text)


def _crop_from(values: Any) -> tuple[float, float, float, float]:
    if not isinstance(values, list | tuple) or len(values) != 4:
        raise PhotoRuleError("operation_invalid", "The crop needs four numbers.")
    left, top, right, bottom = (_number(v, "crop") for v in values)
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise PhotoRuleError("operation_invalid", "The crop is not inside the picture.")
    if right - left < MIN_CROP_KEPT or bottom - top < MIN_CROP_KEPT:
        raise PhotoRuleError(
            "operation_too_strong",
            f"A crop must keep at least {int(MIN_CROP_KEPT * 100)} % of each side.",
        )
    return (left, top, right, bottom)


def operations_from_dict(raw: dict[str, Any]) -> Operations:
    """Read what a person asked for. Unknown fields, wrong types and values above a cap are refused
    (never quietly reduced), so what is stored in the record is exactly what was done."""
    if not isinstance(raw, dict):
        raise PhotoRuleError("operation_invalid", "The adjustments are not valid.")
    if set(raw) - _ALLOWED_KEYS:
        raise PhotoRuleError("operation_unknown", "That adjustment is not available.")

    def flag(name: str) -> bool:
        value = raw.get(name, False)
        if not isinstance(value, bool):
            raise PhotoRuleError("operation_invalid", f"{name} must be true or false.")
        return value

    brightness = _number(raw.get("brightness_percent", 0), "brightness_percent")
    contrast = _number(raw.get("contrast_percent", 0), "contrast_percent")
    straighten = _number(raw.get("straighten_degrees", 0), "straighten_degrees")
    if brightness != int(brightness) or contrast != int(contrast):
        raise PhotoRuleError("operation_invalid", "Brightness and contrast are whole percents.")
    if abs(brightness) > MAX_BRIGHTNESS_PERCENT:
        raise PhotoRuleError(
            "operation_too_strong", f"Brightness can change by {MAX_BRIGHTNESS_PERCENT} %."
        )
    if abs(contrast) > MAX_CONTRAST_PERCENT:
        raise PhotoRuleError(
            "operation_too_strong", f"Contrast can change by {MAX_CONTRAST_PERCENT} %."
        )
    if abs(straighten) > MAX_STRAIGHTEN_DEGREES:
        raise PhotoRuleError(
            "operation_too_strong",
            f"A photo can be straightened by {MAX_STRAIGHTEN_DEGREES:g} degrees.",
        )
    preset = raw.get("preset", "original")
    if preset not in PRESET_SIDES:
        raise PhotoRuleError("preset_unknown", "That size is not available.")
    return Operations(
        auto_exposure=flag("auto_exposure"),
        auto_white_balance=flag("auto_white_balance"),
        brightness_percent=int(brightness),
        contrast_percent=int(contrast),
        straighten_degrees=straighten,
        crop=_crop_from(raw["crop"]) if raw.get("crop") is not None else None,
        sharpen=flag("sharpen"),
        preset=preset,
        watermark=_watermark_from(raw["watermark"]) if raw.get("watermark") is not None else None,
    )


def operations_to_dict(ops: Operations) -> dict[str, Any]:
    """The adjustments as plain data, the way they are kept in the record (and read back by
    ``operations_from_dict``)."""
    return {
        "auto_exposure": ops.auto_exposure,
        "auto_white_balance": ops.auto_white_balance,
        "brightness_percent": ops.brightness_percent,
        "contrast_percent": ops.contrast_percent,
        "straighten_degrees": ops.straighten_degrees,
        "crop": list(ops.crop) if ops.crop else None,
        "sharpen": ops.sharpen,
        "preset": ops.preset,
        "watermark": (
            {"corner": ops.watermark.corner, "kind": ops.watermark.kind, "text": ops.watermark.text}
            if ops.watermark
            else None
        ),
    }


def describe(ops: Operations) -> list[str]:
    """The list shown beside an enhanced copy ("what was done"), in plain words."""
    lines: list[str] = []
    if ops.auto_exposure:
        lines.append("Exposure evened out")
    if ops.auto_white_balance:
        lines.append("Colour cast corrected")
    if ops.brightness_percent:
        lines.append(f"Brightness {ops.brightness_percent:+d} %")
    if ops.contrast_percent:
        lines.append(f"Contrast {ops.contrast_percent:+d} %")
    if ops.straighten_degrees:
        lines.append(f"Straightened {abs(ops.straighten_degrees):g} degrees")
    if ops.crop:
        lines.append("Cropped")
    if ops.sharpen:
        lines.append("Mildly sharpened")
    if ops.watermark:
        lines.append("Watermark added")
    lines.append(f"Resized to at most {PRESET_SIDES[ops.preset]} pixels")
    return lines


# --- Looking at an upload ---------------------------------------------------------------------
@dataclass(frozen=True)
class PhotoInfo:
    format: str
    width: int
    height: int


def inspect(data: bytes) -> PhotoInfo:
    """Check an uploaded photo from its bytes and its header, without decoding the pixels."""
    if not data:
        raise PhotoRuleError("not_an_image", "The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise PhotoRuleError("too_large", "The photo can be at most 20 MB.")
    too_big = "The photo is too large in pixels (50 megapixels at most)."
    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size
        fmt = image.format or ""
        if fmt not in ALLOWED_FORMATS:
            raise PhotoRuleError("type_not_allowed", "Use a JPEG, PNG or WebP photo.")
        if width * height > MAX_PIXELS or max(width, height) > MAX_SIDE:
            raise PhotoRuleError("too_large", too_big)
        if min(width, height) < MIN_SIDE:
            raise PhotoRuleError("too_small", f"The photo must be at least {MIN_SIDE} pixels.")
        if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) > 1:
            raise PhotoRuleError("animated", "Animated pictures are not accepted.")
    except PhotoRuleError:
        raise
    except Image.DecompressionBombError:
        raise PhotoRuleError("too_large", too_big) from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise PhotoRuleError("not_an_image", "The file is not a readable photo.") from None
    return PhotoInfo(fmt, width, height)


# --- Making the enhanced copy -----------------------------------------------------------------
@dataclass(frozen=True)
class Enhanced:
    jpeg: bytes
    width: int
    height: int
    applied: list[str]
    caption: str = DECK_CAPTION


def _channel_mean(picture: Image.Image, band: int) -> float:
    histogram = picture.getchannel(band).histogram()
    total = sum(histogram)
    return sum(i * n for i, n in enumerate(histogram)) / total if total else 0.0


def _white_balance(picture: Image.Image) -> Image.Image:
    """Grey-world correction: scale each colour so their averages meet, never by more than 15 %."""
    means = [max(1.0, _channel_mean(picture, i)) for i in range(3)]
    grey = sum(means) / 3
    gains = [min(1.15, max(0.85, grey / m)) for m in means]
    channels = [
        band.point([min(255, int(v * gain + 0.5)) for v in range(256)])
        for band, gain in zip(picture.split(), gains, strict=True)
    ]
    return Image.merge("RGB", channels)


def _lift_shadows(picture: Image.Image) -> Image.Image:
    """A gentle brightening of a dark picture (gamma no lower than 0.7), aimed at a middle grey."""
    mean = sum(_channel_mean(picture, i) for i in range(3)) / 3
    if mean >= EXPOSURE_TARGET or mean < 1:
        return picture
    gamma = max(MIN_GAMMA, math.log(EXPOSURE_TARGET / 255) / math.log(mean / 255))
    table = [min(255, round(255 * (v / 255) ** gamma)) for v in range(256)]
    return picture.point(table * 3)


def _straighten(picture: Image.Image, degrees: float) -> Image.Image:
    """Rotate, then keep only the middle that has no empty corners (a conservative inscribed
    rectangle of the same shape), so nothing is invented at the edges."""
    width, height = picture.size
    rotated = picture.rotate(degrees, resample=Image.Resampling.BICUBIC, expand=False)
    theta = math.radians(abs(degrees))
    longer, shorter = max(width, height), min(width, height)
    scale = 1.0 / (math.cos(theta) + math.sin(theta) * longer / shorter)
    new_w, new_h = max(1, int(width * scale)), max(1, int(height * scale))
    left, top = (width - new_w) // 2, (height - new_h) // 2
    return rotated.crop((left, top, left + new_w, top + new_h))


def _watermark(picture: Image.Image, mark: Watermark, logo_png: bytes | None) -> Image.Image:
    margin = max(4, picture.width // 60)
    if mark.kind == "logo":
        if not logo_png:
            raise PhotoRuleError("watermark_logo_missing", "The organisation has no logo to use.")
        try:
            item = Image.open(io.BytesIO(logo_png)).convert("RGBA")
        except (UnidentifiedImageError, OSError, ValueError):
            raise PhotoRuleError(
                "watermark_logo_missing", "The organisation's logo cannot be read."
            ) from None
        target = max(8, int(picture.width * LOGO_WATERMARK_SHARE))
        item.thumbnail((target, target))
        item.putalpha(item.getchannel("A").point([int(v * 0.7) for v in range(256)]))
    else:
        font = ImageFont.load_default(size=max(12, picture.width // 40))
        box = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), mark.text, font=font)
        item = Image.new(
            "RGBA", (math.ceil(box[2] - box[0]) + 2, math.ceil(box[3] - box[1]) + 2), (0, 0, 0, 0)
        )
        ImageDraw.Draw(item).text(
            (1 - box[0], 1 - box[1]), mark.text, font=font, fill=(255, 255, 255, 190)
        )
    x = margin if mark.corner.endswith("left") else picture.width - item.width - margin
    y = margin if mark.corner.startswith("top") else picture.height - item.height - margin
    layer = Image.new("RGBA", picture.size, (0, 0, 0, 0))
    layer.paste(item, (max(0, x), max(0, y)), item)
    return Image.alpha_composite(picture.convert("RGBA"), layer).convert("RGB")


BYTES_PER_PIXEL_AT_PEAK = 12  # a rough, deliberately generous estimate of working memory


def estimated_memory_bytes(info: PhotoInfo) -> int:
    """What decoding and adjusting this photo may need at its peak (the worker's refusal cap)."""
    return info.width * info.height * BYTES_PER_PIXEL_AT_PEAK


def _on_time(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise PhotoRuleError("took_too_long", "The photo took too long to adjust.")


def enhance(
    data: bytes,
    ops: Operations,
    *,
    logo_png: bytes | None = None,
    preview: bool = False,
    deadline: float | None = None,
) -> Enhanced:
    """Apply the allowed edits and return a clean JPEG. ``preview`` works on a small copy (fast)
    with exactly the same steps. The input is checked first; none of its metadata is kept."""
    inspect(data)
    try:
        picture = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))  # phone rotation applied
        if picture.mode in ("RGBA", "LA", "P"):
            rgba = picture.convert("RGBA")
            picture = Image.new("RGB", rgba.size, (255, 255, 255))
            picture.paste(rgba, mask=rgba.getchannel("A"))
        else:
            picture = picture.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError):
        raise PhotoRuleError("not_an_image", "The file is not a readable photo.") from None

    _on_time(deadline)
    if preview:
        picture.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
    if ops.straighten_degrees:
        picture = _straighten(picture, ops.straighten_degrees)
    if ops.crop:
        w, h = picture.size
        left, top, right, bottom = ops.crop
        picture = picture.crop(
            (round(left * w), round(top * h), round(right * w), round(bottom * h))
        )
    _on_time(deadline)
    if ops.auto_white_balance:
        picture = _white_balance(picture)
    if ops.auto_exposure:
        picture = Image.blend(picture, ImageOps.autocontrast(picture, cutoff=0.5), 0.6)
        picture = _lift_shadows(picture)
    if ops.brightness_percent:
        picture = ImageEnhance.Brightness(picture).enhance(1 + ops.brightness_percent / 100)
    if ops.contrast_percent:
        picture = ImageEnhance.Contrast(picture).enhance(1 + ops.contrast_percent / 100)
    _on_time(deadline)
    side = PRESET_SIDES[ops.preset]
    if max(picture.size) > side:  # never made bigger than it was
        picture.thumbnail((side, side), Image.Resampling.LANCZOS)
    if ops.sharpen:
        picture = picture.filter(ImageFilter.UnsharpMask(radius=1.5, percent=60, threshold=3))
    if ops.watermark:
        picture = _watermark(picture, ops.watermark, logo_png)

    _on_time(deadline)
    exif = Image.Exif()
    exif[_EXIF_IMAGE_DESCRIPTION] = FILE_LABEL
    for quality in JPEG_QUALITIES:
        out = io.BytesIO()
        picture.save(out, format="JPEG", quality=quality, optimize=True, exif=exif.tobytes())
        if out.tell() <= OUTPUT_MAX_BYTES:
            return Enhanced(out.getvalue(), picture.width, picture.height, describe(ops))
    raise PhotoRuleError("result_too_large", "The enhanced copy is too large. Use a smaller size.")
