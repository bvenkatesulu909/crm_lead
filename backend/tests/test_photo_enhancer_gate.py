"""Gate tests for the property photo enhancer (ADR 0039, PE6): the promises of the ADR, kept honest.

Pure, no database. They fail when someone widens what the enhancer may do (a new adjustment, a
model or an outside service in the module, a cap above the ADR's) or lets the documentation drift
from the code. A change meant to widen the enhancer must change these tests, and so the ADR, on
purpose.
"""

import re
from pathlib import Path

from app.modules.photo_enhancer import rules, schemas
from app.modules.photo_enhancer.rules import Operations

MODULE = Path(rules.__file__).parent
DOC = Path(__file__).resolve().parents[2] / "docs" / "photo-enhancer.md"
PROMISED_OPERATIONS = {
    "auto_exposure",
    "auto_white_balance",
    "brightness_percent",
    "contrast_percent",
    "straighten_degrees",
    "crop",
    "sharpen",
    "preset",
    "watermark",
}


def test_the_list_of_allowed_adjustments_is_the_one_the_adr_promises() -> None:
    assert set(Operations.__dataclass_fields__) == PROMISED_OPERATIONS


def test_the_caps_are_no_wider_than_the_adr() -> None:
    assert rules.MAX_BRIGHTNESS_PERCENT <= 30
    assert rules.MAX_CONTRAST_PERCENT <= 20
    assert rules.MAX_STRAIGHTEN_DEGREES <= 5.0
    assert rules.MIN_CROP_KEPT >= 0.6
    assert rules.MIN_GAMMA >= 0.7
    assert rules.MAX_PIXELS <= 50_000_000
    assert rules.MAX_SIDE <= 12_000
    assert rules.MAX_UPLOAD_BYTES <= 20 * 1024 * 1024
    assert rules.OUTPUT_MAX_SIDE <= 4_000
    assert rules.OUTPUT_MAX_BYTES <= 5 * 1024 * 1024
    assert max(rules.PRESET_SIDES.values()) <= rules.OUTPUT_MAX_SIDE
    assert set(rules.ALLOWED_FORMATS) <= {"JPEG", "PNG", "WEBP"}


def test_nothing_in_the_module_reaches_a_model_or_an_outside_service() -> None:
    forbidden = re.compile(
        r"^\s*(?:import|from)\s+(httpx|requests|urllib|aiohttp|anthropic|openai|langchain|"
        r"langgraph|torch|onnx|cv2|numpy)\b",
        re.MULTILINE,
    )
    for path in MODULE.glob("*.py"):
        found = forbidden.search(path.read_text(encoding="utf-8"))
        assert found is None, f"{path.name} imports {found.group(1) if found else ''}"


def test_the_module_asks_for_no_model_and_names_no_generative_edit() -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in MODULE.glob("*.py")).lower()
    for word in (
        "sky_replace",
        "inpaint",
        "remove_object",
        "generative",
        "diffusion",
        "stable_diff",
    ):
        assert word not in text, word
    assert "uses_model" not in text  # the registry entry (no model) is declared in the catalogue


def test_the_api_bodies_have_no_room_for_a_model_prompt_or_address() -> None:
    names: set[str] = set()
    for schema in (schemas.EnhancementCreate, schemas.DeckChoice, schemas.EnhancementRead):
        names |= set(schema.model_fields)
    assert not names & {"model", "prompt", "url", "tenant_id", "requested_by_user_id", "file"}


def test_the_documentation_states_the_caps_the_code_enforces() -> None:
    doc = " ".join(DOC.read_text(encoding="utf-8").split())  # line breaks are not content
    for needle in (
        f"{rules.MAX_BRIGHTNESS_PERCENT}",
        f"{rules.MAX_CONTRAST_PERCENT}",
        f"{rules.MAX_STRAIGHTEN_DEGREES:g}",
        f"{int(rules.MIN_CROP_KEPT * 100)} %",
        "50 megapixels",
        "12,000",
        "20 MB",
        "4,000",
        "5 MB",
        rules.FILE_LABEL,
        rules.DECK_CAPTION,
    ):
        assert needle in doc, f"docs/photo-enhancer.md does not mention {needle!r}"
    for side in rules.PRESET_SIDES.values():
        assert f"{side:,}" in doc or str(side) in doc, side


def test_the_documentation_does_not_claim_what_is_not_built() -> None:
    doc = DOC.read_text(encoding="utf-8")
    assert "replacing the sky" in doc.lower()  # named as not available
    assert "PE6" in doc
