"""The optional "Why this proposal" slide of the proposal deck (ADR 0032 Amendment A, PD7): pure,
no database. Both renderers draw it from ``DeckData.summary``; without a summary there is no such
slide; the rules say what a summary may be (at most 120 words and 1,000 characters)."""

import io
from dataclasses import replace

import pytest
from pptx import Presentation
from pypdf import PdfReader

from app.modules.proposal_decks import rules
from app.modules.proposal_decks.render import render_deck
from app.modules.proposal_decks.render_pptx import render_pptx
from tests.test_proposal_deck import brand, data

SUMMARY = (
    "You asked for a quiet plot near the school. This one is 300 metres away and fits your budget."
)


def pdf_pages(blob: bytes) -> list[str]:
    return [p.extract_text() for p in PdfReader(io.BytesIO(blob)).pages]


def pptx_slides(blob: bytes) -> list[str]:
    out = []
    for slide in Presentation(io.BytesIO(blob)).slides:
        out.append("\n".join(s.text_frame.text for s in slide.shapes if s.has_text_frame))
    return out


class TestRules:
    def test_a_normal_summary_is_fine(self) -> None:
        assert rules.check_summary(SUMMARY) is None

    @pytest.mark.parametrize("empty", ["", "   ", "\n\n"])
    def test_an_empty_summary_is_refused(self, empty: str) -> None:
        assert rules.check_summary(empty) == "The summary is empty."

    def test_exactly_120_words_is_fine_and_121_is_not(self) -> None:
        assert rules.check_summary(" ".join(["word"] * 120)) is None
        assert "120 words" in (rules.check_summary(" ".join(["word"] * 121)) or "")

    def test_exactly_1000_characters_is_fine_and_1001_is_not(self) -> None:
        assert rules.check_summary("a" * 1000) is None
        assert "1000 characters" in (rules.check_summary("a" * 1001) or "")

    def test_leading_and_trailing_space_does_not_count(self) -> None:
        assert rules.check_summary("   " + "a" * 1000 + "   ") is None


class TestSlide:
    def test_the_pdf_has_the_slide_only_with_a_summary(self) -> None:
        without = pdf_pages(render_deck(data(), compress=False))
        with_summary = pdf_pages(render_deck(replace(data(), summary=SUMMARY), compress=False))
        assert len(with_summary) == len(without) + 1
        assert not any("Why this proposal" in p for p in without)
        [page] = [p for p in with_summary if "Why this proposal" in p]
        assert SUMMARY in page.replace("\n", " ")

    def test_the_powerpoint_has_the_slide_only_with_a_summary(self) -> None:
        without = pptx_slides(render_pptx(data()))
        with_summary = pptx_slides(render_pptx(replace(data(), summary=SUMMARY)))
        assert len(with_summary) == len(without) + 1
        assert not any("Why this proposal" in s for s in without)
        [slide] = [s for s in with_summary if "Why this proposal" in s]
        assert SUMMARY in slide

    @pytest.mark.parametrize("blank", [None, "", "   \n "])
    def test_a_blank_summary_adds_no_slide(self, blank: str | None) -> None:
        d = replace(data(), summary=blank)
        assert len(pdf_pages(render_deck(d, compress=False))) == len(
            pdf_pages(render_deck(data(), compress=False))
        )
        assert len(pptx_slides(render_pptx(d))) == len(pptx_slides(render_pptx(data())))

    def test_it_comes_after_about_us_and_before_the_lines(self) -> None:
        d = replace(data(), summary=SUMMARY)
        for titles in (
            [p for p in pdf_pages(render_deck(d, compress=False))],
            pptx_slides(render_pptx(d)),
        ):
            order = [
                next(
                    name
                    for name in (
                        "Prepared for",
                        "About ",
                        "Why this proposal",
                        "What we propose",
                        "Investment",
                    )
                    if name in text
                )
                for text in titles[:5]
            ]
            assert order == [
                "Prepared for",
                "About ",
                "Why this proposal",
                "What we propose",
                "Investment",
            ]

    def test_without_an_about_text_it_follows_the_cover(self) -> None:
        d = replace(data(brand=brand(about_text="")), summary=SUMMARY)
        assert "Why this proposal" in pdf_pages(render_deck(d, compress=False))[1]
        assert "Why this proposal" in pptx_slides(render_pptx(d))[1]

    def test_both_files_have_the_same_number_of_slides(self) -> None:
        d = replace(data(), summary=SUMMARY)
        assert len(PdfReader(io.BytesIO(render_deck(d))).pages) == len(
            Presentation(io.BytesIO(render_pptx(d))).slides
        )

    def test_typed_text_stays_plain_text(self) -> None:
        d = replace(data(), summary="A <b>bold</b> & <script>x</script> claim")
        text = "\n".join(pptx_slides(render_pptx(d)))
        assert "A <b>bold</b> & <script>x</script> claim" in text
        assert "<b>bold</b>" in "".join(pdf_pages(render_deck(d, compress=False)))

    def test_hindi_text_is_drawn_not_replaced_by_question_marks(self) -> None:
        d = replace(data(), summary="आपके बजट के अनुसार यह प्लॉट सही है।")
        page = next(
            p for p in pdf_pages(render_deck(d, compress=False)) if "Why this proposal" in p
        )
        assert "?" not in page

    def test_the_same_data_gives_the_same_bytes(self) -> None:
        d = replace(data(), summary=SUMMARY)
        assert render_deck(d) == render_deck(d)
        assert render_pptx(d) == render_pptx(d)

    def test_a_summary_changes_the_file(self) -> None:
        assert render_deck(data()) != render_deck(replace(data(), summary=SUMMARY))
        assert render_pptx(data()) != render_pptx(replace(data(), summary=SUMMARY))
