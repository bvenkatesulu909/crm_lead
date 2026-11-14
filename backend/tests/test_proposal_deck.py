"""The proposal deck renderer (ADR 0032, PD2): pure, no database. The PDF is read back with pypdf
and checked for the words, the amounts, the pages, the font and what must NOT be in it."""

import io
import re
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from PIL import Image
from pypdf import PdfReader

from app.modules.proposal_decks import rules
from app.modules.proposal_decks.data import DeckBrand, DeckData, DeckLine
from app.modules.proposal_decks.render import drawable_characters, render_deck

RUPEE = "₹"


def logo() -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (200, 80), (200, 30, 30, 255)).save(out, format="PNG")
    return out.getvalue()


def brand(**over: object) -> DeckBrand:
    values: dict[str, object] = {
        "organisation": "Acme Homes Pvt Ltd",
        "color": "0b6e4f",
        "about_text": "We build homes in Vijayawada since 1998.",
        "terms_text": "Payment within 30 days.",
        "contact_line": "sales@example.test",
        "footer_line": "Acme Homes - RERA DEMO-0001",
        "logo_png": None,
    }
    values.update(over)
    return DeckBrand(**values)  # type: ignore[arg-type]


def line(n: int, **over: object) -> DeckLine:
    values: dict[str, object] = {
        "position": n,
        "description": f"Villa plot {n}",
        "quantity": Decimal("2.500"),
        "unit": "pcs",
        "net_unit_price": Decimal("1234567.89"),
        "discount_percent": Decimal("0"),
        "tax_rate": Decimal("18"),
        "line_subtotal": Decimal("3086419.73"),
    }
    values.update(over)
    return DeckLine(**values)  # type: ignore[arg-type]


def data(**over: object) -> DeckData:
    values: dict[str, object] = {
        "number": "QT-0007",
        "title": "Proposal for Riverside Villas",
        "customer": "Banyan Builders Ltd",
        "contact": "Asha Rao",
        "issued": date(2026, 11, 13),
        "valid_until": date(2026, 12, 13),
        "currency": "INR",
        "lines": (line(1), line(2)),
        "gross_total": Decimal("40000000"),
        "discount_total": Decimal("1000000"),
        "subtotal": Decimal("39000000"),
        "tax_total": Decimal("7020000"),
        "total": Decimal("46020000"),
        "customer_note": "Thank you for visiting the site.",
        "brand": brand(),
    }
    values.update(over)
    return DeckData(**values)  # type: ignore[arg-type]


def read(pdf: bytes) -> PdfReader:
    return PdfReader(io.BytesIO(pdf))


def texts(pdf: bytes) -> list[str]:
    return [page.extract_text() for page in read(pdf).pages]


# --- money and small helpers ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "currency", "shown"),
    [
        ("0", "INR", f"{RUPEE}0.00"),
        ("999.5", "INR", f"{RUPEE}999.50"),
        ("1000", "INR", f"{RUPEE}1,000.00"),
        ("123456.78", "INR", f"{RUPEE}1,23,456.78"),
        ("12345678.9", "INR", f"{RUPEE}1,23,45,678.90"),
        ("460200000", "INR", f"{RUPEE}46,02,00,000.00"),
        ("-1000", "INR", f"-{RUPEE}1,000.00"),
        ("1234.5", "EUR", "1,234.50 EUR"),
        ("1234567.891", "USD", "1,234,567.89 USD"),
        ("-5", "USD", "-5.00 USD"),
    ],
)
def test_money_is_written_the_indian_way_for_rupees(amount: str, currency: str, shown: str) -> None:
    assert rules.money(Decimal(amount), currency) == shown


def test_quantities_lose_trailing_zeros() -> None:
    assert rules.plain_number(Decimal("2.500")) == "2.5"
    assert rules.plain_number(Decimal("10.00")) == "10"


def test_dates_are_written_in_words() -> None:
    assert rules.long_date(date(2026, 11, 3)) == "3 November 2026"


def test_lines_are_split_ten_to_a_page() -> None:
    assert [len(p) for p in rules.pages(list(range(25)))] == [10, 10, 5]
    assert rules.pages([]) == [[]]
    assert [len(p) for p in rules.pages(list(range(10)))] == [10]
    with pytest.raises(ValueError):
        rules.pages([1], 0)


def test_characters_the_font_cannot_draw_become_question_marks() -> None:
    can = drawable_characters()
    assert rules.printable("Plot ₹ 5", can) == "Plot ₹ 5"
    assert rules.printable("हिन्दी x", can) == "?????? x"
    assert rules.printable("a\nb", can) == "a\nb"


# --- the pages ------------------------------------------------------------------------------


def test_a_full_deck_has_cover_about_lines_investment_terms_and_next_steps() -> None:
    pdf = render_deck(data())
    assert len(read(pdf).pages) == 6
    cover, about, propose, invest, terms, steps = texts(pdf)
    assert "Proposal for Riverside Villas" in cover and "Banyan Builders Ltd" in cover
    assert "Asha Rao" in cover and "QT-0007" in cover and "13 November 2026" in cover
    assert "About Acme Homes Pvt Ltd" in about and "since 1998" in about
    assert "What we propose" in propose and "Villa plot 1" in propose
    assert "Investment" in invest and "valid until 13 December 2026" in invest
    assert "Notes for you" in terms and "Our standard terms" in terms
    assert "Next steps" in steps and "sales@example.test" in steps


def test_every_page_is_sixteen_by_nine() -> None:
    for page in read(render_deck(data())).pages:
        assert (float(page.mediabox.width), float(page.mediabox.height)) == (960.0, 540.0)


def test_without_an_about_text_or_notes_those_pages_are_left_out() -> None:
    bare = data(brand=brand(about_text="", terms_text=""), customer_note=None)
    pages = texts(render_deck(bare))
    assert len(pages) == 4
    assert not any("About" in t for t in pages) and not any("Notes and terms" in t for t in pages)


def test_a_note_alone_or_terms_alone_still_gets_the_page() -> None:
    only_note = texts(render_deck(data(brand=brand(terms_text=""))))
    assert any("Notes for you" in t for t in only_note)
    assert not any("Our standard terms" in t for t in only_note)
    only_terms = texts(render_deck(data(customer_note=None)))
    assert any("Our standard terms" in t for t in only_terms)
    assert not any("Notes for you" in t for t in only_terms)


def test_many_lines_continue_on_further_pages() -> None:
    many = data(lines=tuple(line(n) for n in range(1, 26)))
    pages = texts(render_deck(many))
    proposals = [t for t in pages if "What we propose" in t]
    assert len(proposals) == 3
    assert "(1 of 3)" in proposals[0] and "(3 of 3)" in proposals[2]
    assert "Villa plot 25" in proposals[2] and "Villa plot 11" in proposals[1]


def test_a_deck_with_no_lines_still_has_its_header_row() -> None:
    pages = texts(render_deck(data(lines=())))
    assert any("What we propose" in t and "Description" in t for t in pages)


def test_each_inner_page_has_the_footer_and_its_number() -> None:
    pages = texts(render_deck(data()))
    assert "1 / 6" not in pages[0]  # the cover has no page frame
    for number, page in enumerate(pages[1:], start=2):
        assert "Acme Homes - RERA DEMO-0001" in page and f"{number} / 6" in page


def test_without_a_footer_line_the_organisation_name_is_the_footer() -> None:
    pages = texts(render_deck(data(brand=brand(footer_line=""))))
    assert "Acme Homes Pvt Ltd" in pages[1]


# --- the numbers ----------------------------------------------------------------------------


def test_amounts_use_the_rupee_sign_and_lakh_grouping() -> None:
    propose, invest = texts(render_deck(data()))[2:4]
    assert f"{RUPEE}12,34,567.89" in propose and f"{RUPEE}30,86,419.73" in propose
    for shown in (
        f"{RUPEE}4,00,00,000.00",
        f"{RUPEE}3,90,00,000.00",
        f"{RUPEE}70,20,000.00",
        f"{RUPEE}4,60,20,000.00",
    ):
        assert shown in invest
    assert f"-{RUPEE}10,00,000.00" in invest  # the discount


def test_no_discount_row_when_there_is_no_discount() -> None:
    invest = texts(render_deck(data(discount_total=Decimal("0"))))[3]
    assert "Discount" not in invest


def test_a_discounted_line_says_so() -> None:
    propose = texts(render_deck(data(lines=(line(1, discount_percent=Decimal("5.00")),))))[2]
    assert "5 % off" in propose


def test_other_currencies_keep_their_code() -> None:
    propose = texts(render_deck(data(currency="EUR")))[2]
    assert "1,234,567.89 EUR" in propose and RUPEE not in propose


# --- what people typed ----------------------------------------------------------------------


def test_typed_text_is_drawn_as_typed_not_as_markup() -> None:
    nasty = data(
        title="Plots <b>A</b> & B",
        lines=(line(1, description="<i>Corner</i> & <script>x</script>"),),
    )
    pages = texts(render_deck(nasty))
    assert "Plots <b>A</b> & B" in pages[0]
    assert "<i>Corner</i> & <script>x</script>" in pages[2]


def test_the_organisations_texts_are_drawn_as_typed_too() -> None:
    pages = texts(render_deck(data(brand=brand(about_text="We are <u>the best</u> & cheap"))))
    assert "We are <u>the best</u> & cheap" in pages[1]


def test_line_breaks_in_texts_are_kept() -> None:
    page = texts(render_deck(data(customer_note="First line\nSecond line")))[4]
    assert "First line\nSecond line" in page  # on two lines, not run together


def test_text_in_a_script_the_font_lacks_becomes_question_marks_not_boxes() -> None:
    pages = texts(render_deck(data(customer="తెలుగు Ltd")))
    assert "????? Ltd" in pages[0] or "?" in pages[0]
    assert "త" not in pages[0]


def test_a_text_with_many_short_lines_is_shrunk_to_fit_not_cut() -> None:
    tall = "\n".join(f"Point {i}" for i in range(70))  # far taller than the slide at full size
    page = texts(render_deck(data(brand=brand(about_text=tall))))[1]
    assert "Point 0" in page and "Point 69" in page
    # The text is scaled down (a scaling matrix in the page), not clipped: short text is not.
    scaled = re.compile(rb"\.\d+ 0 0 \.\d+ [\d.]+ [\d.]+ cm")
    assert scaled.search(render_deck(data(brand=brand(about_text=tall)), compress=False))
    assert not scaled.search(render_deck(data(brand=brand(about_text="Hello")), compress=False))


def test_a_very_long_text_is_shrunk_to_fit_not_cut() -> None:
    words = " ".join(f"word{i}" for i in range(280))  # about 1,500 characters
    pages = texts(render_deck(data(brand=brand(about_text=words))))
    assert "word0" in pages[1] and "word279" in pages[1]


def test_a_very_long_title_still_fits_on_the_cover() -> None:
    long_title = " ".join(f"Title{i}" for i in range(60))
    assert "Title59" in texts(render_deck(data(title=long_title)))[0]


# --- the logo and the colour ----------------------------------------------------------------


def images_in(pdf: bytes) -> int:
    return sum(len(page.images) for page in read(pdf).pages)


def test_a_logo_is_drawn_on_the_cover_only() -> None:
    assert images_in(render_deck(data(brand=brand(logo_png=logo())))) == 1
    assert images_in(render_deck(data())) == 0


def test_without_a_logo_the_cover_shows_the_organisation_name() -> None:
    assert "Acme Homes Pvt Ltd" in texts(render_deck(data()))[0]


def test_a_broken_logo_is_an_error_not_a_blank_cover() -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011 - any decode failure is acceptable
        render_deck(data(brand=brand(logo_png=b"not a picture")))


def test_the_brand_colour_is_used_for_the_cover_and_the_accent() -> None:
    pdf = render_deck(data(), compress=False)
    assert b".043137 .431373 .309804 rg" in pdf  # 0b6e4f as PDF colour components
    other = render_deck(data(brand=brand(color="b00020")), compress=False)
    assert b".043137 .431373 .309804 rg" not in other  # a different colour changes the pages
    # b00020: the cover, the top bar of every inner page and the headings all use it
    assert other.count(b".690196 0 .12549 rg") >= 8


# --- the file itself ------------------------------------------------------------------------


def test_the_noto_sans_font_is_embedded() -> None:
    pdf = render_deck(data(), compress=False)
    assert b"NotoSans" in pdf and b"NotoSans-Bold" in pdf
    assert pdf.count(b"/FontFile2") >= 2  # the font programs themselves, not just their names


@pytest.mark.parametrize(
    "forbidden", [b"/URI", b"/JavaScript", b"/JS", b"/OpenAction", b"/Launch", b"/EmbeddedFile"]
)
def test_the_pdf_has_no_links_scripts_or_attachments(forbidden: bytes) -> None:
    hostile = data(
        title="javascript:alert(1) http://evil.example",
        customer="https://evil.example/x",
        brand=brand(about_text="see http://evil.example"),
    )
    assert forbidden not in render_deck(hostile, compress=False)


def test_the_same_data_gives_the_same_bytes() -> None:
    assert render_deck(data()) == render_deck(data())
    assert render_deck(data()) != render_deck(data(title="Another"))


def test_the_title_and_author_are_set() -> None:
    meta = read(render_deck(data())).metadata
    assert meta is not None
    assert meta.title is not None and "Riverside Villas" in meta.title
    assert meta.author == "Acme Homes Pvt Ltd"


def test_a_deck_is_small() -> None:
    assert len(render_deck(data(lines=tuple(line(n) for n in range(1, 31))))) < 200_000


def test_the_font_licence_travels_with_the_fonts() -> None:
    from pathlib import Path

    folder = Path(__file__).resolve().parents[1] / "app" / "modules" / "proposal_decks" / "fonts"
    assert (folder / "OFL.txt").is_file() and "SIL Open Font License" in (
        folder / "OFL.txt"
    ).read_text()


def test_data_classes_are_immutable() -> None:
    deck = data()
    with pytest.raises(Exception):  # noqa: B017, PT011
        deck.title = "x"  # type: ignore[misc]
    assert replace(deck, title="y").title == "y"
