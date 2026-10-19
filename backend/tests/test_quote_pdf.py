"""Quote PDF drawing (ADR 0005), without a database."""

from datetime import date
from decimal import Decimal

from app.modules.quotes.pdf import PdfLine, QuotePdfData, render_quote_pdf

D = Decimal


def sample(**changes: object) -> QuotePdfData:
    values: dict[str, object] = {
        "number": "QT-0007 rev 2",
        "title": "<b>Widgets & more</b>",
        "supplier": "Alpha Demo (fictional)",
        "customer": "Example Customer One Ltd",
        "contact": "Ada Example",
        "issued": date(2026, 10, 19),
        "valid_until": date(2026, 11, 18),
        "currency": "EUR",
        "lines": (
            PdfLine(
                1,
                "WID-1",
                "Widget",
                D("2.500"),
                "each",
                D("100.00"),
                D("15.00"),
                D("85.00"),
                D("19.00"),
                D("212.50"),
            ),
        ),  # fmt: skip
        "gross_total": D("250.00"),
        "discount_total": D("37.50"),
        "subtotal": D("212.50"),
        "tax_total": D("40.38"),
        "total": D("252.88"),
        "customer_note": "Delivery in two weeks.",
    }
    return QuotePdfData(**(values | changes))  # type: ignore[arg-type]


def test_the_pdf_shows_what_the_customer_needs() -> None:
    pdf = render_quote_pdf(sample(), compress=False)
    assert pdf.startswith(b"%PDF-")
    for text in [
        b"Quote QT-0007 rev 2",
        b"Example Customer One Ltd",
        b"Attn. Ada Example",
        b"2026-11-18",
        b"WID-1",
        b"2.5 each",  # quantities without trailing zeros
        b"15 %",
        b"252.88 EUR",
        b"Delivery in two weeks.",
    ]:
        assert text in pdf, text


def test_user_text_is_printed_as_typed_not_interpreted() -> None:
    pdf = render_quote_pdf(sample(), compress=False)
    # The title's "<b>" is drawn as the characters "<", "b", ">" (ReportLab writes them as
    # separate text pieces), not interpreted as "bold".
    assert b"(<) Tj (b) Tj (>) Tj (Widgets & more) Tj (<) Tj (/b) Tj" in pdf


def test_same_quote_same_bytes() -> None:
    # No timestamps or random IDs inside: the checksum of a stored PDF is reproducible.
    assert render_quote_pdf(sample()) == render_quote_pdf(sample())
    assert render_quote_pdf(sample()) != render_quote_pdf(sample(total=D("1.00")))


def test_optional_parts_can_be_missing() -> None:
    pdf = render_quote_pdf(
        sample(contact=None, customer_note=None, discount_total=D("0")), compress=False
    )
    assert b"Attn." not in pdf
    assert b"Notes" not in pdf
    assert b"Discount" not in pdf
