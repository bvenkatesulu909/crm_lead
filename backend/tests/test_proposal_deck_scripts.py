"""Hindi and Telugu in the proposal deck (ADR 0032 Amendment A, PD5): pure, no database.

Each run of text is drawn with the font of its script (Noto Sans, Devanagari, Telugu) and shaped
with HarfBuzz, so vowel signs and conjuncts are joined. A character no bundled font has is still
shown as ``?``. The PDF is read back with pypdf."""

import io
from typing import Any, cast

from pypdf import PdfReader

from app.modules.proposal_decks import rules
from app.modules.proposal_decks.render import drawable_characters, render_deck
from tests.test_proposal_deck import brand, data

HINDI = "नमस्ते"
TELUGU = "తెలుగు"


def fonts_in(pdf: bytes) -> set[str]:
    names: set[str] = set()
    for page in PdfReader(io.BytesIO(pdf)).pages:
        resources = cast(dict[str, Any], page["/Resources"])
        fonts = cast(dict[str, Any], resources["/Font"] if "/Font" in resources else {})
        for ref in fonts.values():
            base = str(ref.get_object()["/BaseFont"])
            names.add(base.split("+")[-1].lstrip("/"))
    return names


def test_scripts_are_told_apart() -> None:
    assert rules.script_of("a") == "latin"
    assert rules.script_of("₹") == "latin"
    assert rules.script_of("न") == "devanagari"
    assert rules.script_of("।") == "devanagari"
    assert rules.script_of("త") == "telugu"
    assert rules.script_of("౧") == "telugu"
    assert rules.script_of("1") == "latin"


def test_runs_split_by_script_and_keep_neutral_characters_with_latin() -> None:
    runs = rules.script_runs(f"Hi {HINDI} and {TELUGU}!")
    assert runs == [
        ("latin", "Hi "),
        ("devanagari", HINDI),
        ("latin", " and "),
        ("telugu", TELUGU),
        ("latin", "!"),
    ]


def test_joiners_stay_with_the_letters_around_them() -> None:
    word = "क्‍ष"  # ka + virama + ZWJ + ssa
    assert rules.script_runs(word) == [("devanagari", word)]
    assert rules.script_runs("a‍b") == [("latin", "a‍b")]


def test_empty_text_has_no_runs() -> None:
    assert rules.script_runs("") == []


def test_unknown_characters_become_question_marks_per_script() -> None:
    glyphs = {
        "latin": frozenset(map(ord, "ab ")),
        "devanagari": frozenset(map(ord, "न")),
        "telugu": frozenset(),
    }
    assert rules.printable_scripts("ab न త\nz", glyphs) == "ab न ?\n?"


def test_each_bundled_font_has_its_own_script() -> None:
    assert ord("न") in drawable_characters("devanagari")
    assert ord("త") in drawable_characters("telugu")
    assert ord("₹") in drawable_characters("latin")
    assert ord("न") not in drawable_characters("latin")
    assert ord("త") not in drawable_characters("devanagari")


def test_a_hindi_and_telugu_deck_uses_the_matching_fonts() -> None:
    pdf = render_deck(
        data(
            title=f"Proposal {HINDI}",
            customer=f"{TELUGU} Builders",
            brand=brand(about_text=f"{HINDI} {TELUGU}", organisation="Acme"),
        )
    )
    names = " ".join(fonts_in(pdf))
    assert "NotoSans-" in names or "NotoSans" in names
    assert "NotoSansDevanagari" in names
    assert "NotoSansTelugu" in names


def test_a_latin_only_deck_does_not_embed_the_indic_fonts() -> None:
    names = " ".join(fonts_in(render_deck(data())))
    assert "Devanagari" not in names
    assert "Telugu" not in names


def test_no_question_marks_replace_hindi_or_telugu_any_more() -> None:
    pdf = render_deck(data(customer=f"{HINDI} {TELUGU}"), compress=False)
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "?" not in text


def test_other_scripts_still_become_question_marks() -> None:
    pdf = render_deck(data(customer="日本語 Ltd"), compress=False)
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "???" in text
    assert "日" not in text


def test_the_same_data_gives_the_same_bytes_with_indic_text() -> None:
    d = data(customer=f"{HINDI} {TELUGU}", brand=brand(about_text=f"{HINDI}\n{TELUGU}"))
    assert render_deck(d) == render_deck(d)


def test_the_indic_fonts_are_shaped_with_harfbuzz() -> None:
    from reportlab.pdfbase import pdfmetrics

    render_deck(data(customer=HINDI))
    for name in (
        "NotoSansDevanagari",
        "NotoSansDevanagari-Bold",
        "NotoSansTelugu",
        "NotoSansTelugu-Bold",
    ):
        assert pdfmetrics.getFont(name).shapable is True


def test_bold_text_uses_the_bold_face_of_the_script() -> None:
    # The customer's name on the cover is bold; the about text is regular.
    bold_only = fonts_in(render_deck(data(customer=HINDI, brand=brand(about_text="Plain"))))
    assert any(n.startswith("NotoSansDevanagari-Bold") for n in bold_only)
    regular_only = fonts_in(
        render_deck(data(customer="Plain", brand=brand(about_text=TELUGU), title="Plain"))
    )
    assert any(n.startswith("NotoSansTelugu-Regular") for n in regular_only)
    assert not any(n.startswith("NotoSansTelugu-Bold") for n in regular_only)
