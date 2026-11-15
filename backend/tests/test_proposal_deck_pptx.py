"""The proposal deck as a PowerPoint file (ADR 0032 Amendment A, PD6): pure, no database.

The file is read back with python-pptx and checked for the slides, the words, the amounts (the same
strings as the PDF), what must NOT be in it (links, macros, embedded objects) and that the same data
gives the same bytes."""

import io
import re
import zipfile
from pathlib import Path

import pytest
from pptx import Presentation
from pypdf import PdfReader

from app.modules.proposal_decks import rules
from app.modules.proposal_decks.render import render_deck
from app.modules.proposal_decks.render_pptx import clean, render_pptx
from tests.test_proposal_deck import brand, data, line, logo

APP = Path(__file__).resolve().parents[1] / "app"


def slides_text(blob: bytes) -> list[str]:
    prs = Presentation(io.BytesIO(blob))
    out: list[str] = []
    for slide in prs.slides:
        parts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
            if shape.has_table:
                for row in shape.table.rows:
                    parts.extend(cell.text for cell in row.cells)
        out.append("\n".join(parts))
    return out


def pdf_pages(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


def test_same_slides_as_the_pdf_for_several_decks() -> None:
    cases = [
        data(),
        data(brand=brand(about_text="", terms_text=""), customer_note=None),
        data(lines=tuple(line(n) for n in range(1, 26))),
        data(brand=brand(about_text="x" * 5), customer_note=""),
    ]
    for case in cases:
        assert len(Presentation(io.BytesIO(render_pptx(case))).slides) == pdf_pages(
            render_deck(case)
        )


def test_twenty_five_lines_make_three_proposal_slides() -> None:
    text = slides_text(render_pptx(data(lines=tuple(line(n) for n in range(1, 26)))))
    assert sum("What we propose" in t for t in text) == 3
    assert "What we propose (3 of 3)" in "\n".join(text)


def test_the_words_and_amounts_are_those_of_the_quote() -> None:
    text = "\n".join(slides_text(render_pptx(data())))
    for wanted in (
        "Proposal for Riverside Villas",
        "Banyan Builders Ltd",
        "Asha Rao",
        "Proposal QT-0007 · 13 November 2026",
        "About Acme Homes Pvt Ltd",
        "Villa plot 1",
        "₹12,34,567.89",
        "₹4,60,20,000.00",
        "₹-10,00,000.00".replace("₹-", "-₹"),
        "This proposal is valid until 13 December 2026.",
        "Thank you for visiting the site.",
        "Payment within 30 days.",
        "sales@example.test",
        "2 / 6",
        "6 / 6",
    ):
        assert wanted in text, wanted


def test_the_amounts_are_exactly_the_strings_the_pdf_uses() -> None:
    d = data()
    text = "\n".join(slides_text(render_pptx(d)))
    for amount in (d.total, d.tax_total, d.subtotal, d.gross_total):
        assert rules.money(amount, d.currency) in text


def test_typed_text_is_plain_text_not_markup() -> None:
    text = "\n".join(
        slides_text(render_pptx(data(title="A <b>bold</b> & <script>x</script> plan")))
    )
    assert "A <b>bold</b> & <script>x</script> plan" in text


def test_control_characters_are_removed_but_line_breaks_stay() -> None:
    assert clean("a\x00b\x0bc\x1fd") == "abcd"
    assert clean("one\r\ntwo\rthree") == "one\ntwo\nthree"
    text = "\n".join(slides_text(render_pptx(data(customer_note="First\x00 line\nSecond line"))))
    assert "First line\nSecond line" in text


def test_hindi_and_telugu_are_kept_as_typed() -> None:
    text = "\n".join(slides_text(render_pptx(data(customer="नमस्ते తెలుగు Ltd"))))
    assert "नमस्ते తెలుగు Ltd" in text


def test_a_discount_is_shown_per_line() -> None:
    from decimal import Decimal

    text = "\n".join(
        slides_text(render_pptx(data(lines=(line(1, discount_percent=Decimal("12.5")),))))
    )
    assert "12.5 % off" in text


def test_no_links_macros_or_embedded_objects() -> None:
    blob = render_pptx(data(brand=brand(logo_png=logo())))
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = archive.namelist()
        assert not [n for n in names if re.search(r"vba|ole|embed|activeX|macro", n, re.I)]
        assert not any(n.endswith(".bin") for n in names)
        for name in names:
            if name.endswith(".rels"):
                assert 'TargetMode="External"' not in archive.read(name).decode()
            if name.endswith(".xml"):
                xml = archive.read(name).decode("utf-8")
                assert "hlinkClick" not in xml and "hlinkHover" not in xml


def test_only_the_organisations_logo_is_an_image() -> None:
    def media(blob: bytes) -> list[str]:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            return [
                n for n in archive.namelist() if n.startswith("ppt/media/") and "thumbnail" not in n
            ]

    assert media(render_pptx(data())) == []
    with_logo = media(render_pptx(data(brand=brand(logo_png=logo()))))
    assert len(with_logo) == 1 and with_logo[0].endswith(".png")


def test_the_same_data_gives_the_same_bytes_and_every_entry_has_the_fixed_time() -> None:
    d = data(brand=brand(logo_png=logo()))
    first = render_pptx(d)
    assert first == render_pptx(d)
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert {i.date_time for i in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_different_data_gives_different_bytes() -> None:
    assert render_pptx(data()) != render_pptx(data(title="Another title"))


def test_the_file_properties_name_the_organisation_and_use_the_issue_date() -> None:
    props = Presentation(io.BytesIO(render_pptx(data()))).core_properties
    assert props.author == "Acme Homes Pvt Ltd"
    assert props.title == "Proposal for Riverside Villas - QT-0007"
    assert (props.created.year, props.created.month, props.created.day) == (2026, 11, 13)
    assert props.modified == props.created


def test_slides_are_widescreen() -> None:
    prs = Presentation(io.BytesIO(render_pptx(data())))
    assert round(prs.slide_width / prs.slide_height, 2) == round(16 / 9, 2)


def test_very_long_text_gets_a_smaller_font_not_a_cut() -> None:
    long_text = ("A long sentence about the project. " * 80).strip()
    blob = render_pptx(data(brand=brand(about_text=long_text)))
    prs = Presentation(io.BytesIO(blob))
    sizes = [
        run.font.size.pt
        for shape in prs.slides[1].shapes
        if shape.has_text_frame and long_text[:20] in shape.text_frame.text
        for paragraph in shape.text_frame.paragraphs
        for run in paragraph.runs
        if run.font.size
    ]
    assert sizes and max(sizes) < 16 and min(sizes) >= 10
    assert long_text in "\n".join(slides_text(blob))


class TestFitFontSize:
    def test_short_text_keeps_the_biggest_size(self) -> None:
        assert rules.fit_font_size("Hello", width_in=8, height_in=2, max_pt=16) == 16

    def test_longer_text_gets_smaller(self) -> None:
        small = rules.fit_font_size("word " * 300, width_in=8, height_in=3, max_pt=16)
        assert 9 <= small < 16

    def test_never_below_the_minimum(self) -> None:
        assert (
            rules.fit_font_size("word " * 5000, width_in=4, height_in=1, max_pt=20, min_pt=10) == 10
        )

    def test_line_breaks_count_as_lines(self) -> None:
        many = "\n".join("x" for _ in range(40))
        one = "x" * 40
        a = rules.fit_font_size(many, width_in=8, height_in=3, max_pt=20)
        b = rules.fit_font_size(one, width_in=8, height_in=3, max_pt=20)
        assert a < b

    def test_a_bigger_box_never_gives_a_smaller_size(self) -> None:
        text = "word " * 200
        sizes = [
            rules.fit_font_size(text, width_in=8, height_in=h, max_pt=20) for h in (1, 2, 3, 4, 5)
        ]
        assert sizes == sorted(sizes)


@pytest.mark.parametrize("name", ["pptx"])
def test_only_the_pptx_renderer_imports_python_pptx(name: str) -> None:
    pattern = re.compile(rf"^\s*(import|from)\s+{name}(\.|\s)", re.M)
    offenders = [
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [str(Path("modules/proposal_decks/render_pptx.py"))]


def test_every_relationship_points_at_a_part_that_exists() -> None:
    with zipfile.ZipFile(io.BytesIO(render_pptx(data(brand=brand(logo_png=logo()))))) as archive:
        names = set(archive.namelist())
        for rels in [n for n in names if n.endswith(".rels")]:
            base = Path(rels).parent.parent
            for target in re.findall(r'Target="([^"]+)"', archive.read(rels).decode("utf-8")):
                resolved = (
                    target.lstrip("/")
                    if target.startswith("/")
                    else str((base / target).as_posix())
                )
                parts = [p for p in resolved.split("/") if p != "."]
                stack: list[str] = []
                for part in parts:
                    if part == "..":
                        stack.pop()
                    else:
                        stack.append(part)
                assert "/".join(stack) in names, (rels, target)


def test_no_template_leftovers() -> None:
    with zipfile.ZipFile(io.BytesIO(render_pptx(data()))) as archive:
        assert not [n for n in archive.namelist() if "printerSettings" in n or "thumbnail" in n]
        assert b"thumbnail" not in archive.read("_rels/.rels")
