"""Quote PDF (ADR 0005), drawn with ReportLab.

Shows what the customer gets - number, lines, totals, validity and the customer note - and
never internal notes, approval details or the status (a stored PDF must stay true for ever,
while the status changes). Built from plain data, so it is easy to test.
"""

import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


@dataclass(frozen=True)
class PdfLine:
    position: int
    sku: str
    description: str
    quantity: Decimal
    unit: str
    list_price: Decimal
    discount_percent: Decimal
    net_unit_price: Decimal
    tax_rate: Decimal
    line_subtotal: Decimal


@dataclass(frozen=True)
class QuotePdfData:
    number: str  # "QT-0007" or "QT-0007 rev 2"
    title: str
    supplier: str
    customer: str
    contact: str | None
    issued: date
    valid_until: date
    currency: str
    lines: tuple[PdfLine, ...]
    gross_total: Decimal
    discount_total: Decimal
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    customer_note: str | None


def _money(amount: Decimal, currency: str) -> str:
    # Currency code instead of a symbol: the built-in PDF fonts can't show every symbol.
    return f"{amount:,.2f} {currency}"


def _number(value: Decimal) -> str:
    return f"{value.normalize():f}"  # 2.500 -> "2.5", 10.00 -> "10"


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    # Paragraph understands a little HTML, so user text is escaped: a title like "<b>" or
    # "&" must be printed as typed, never interpreted.
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def render_quote_pdf(data: QuotePdfData, *, compress: bool = True) -> bytes:
    """The PDF as bytes. ``compress=False`` keeps the text readable (used by tests)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Quote {data.number}",
        author=data.supplier,
        pageCompression=1 if compress else 0,
        invariant=1,  # same input -> same bytes (no timestamps/random IDs inside)
    )
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=10, leading=13)
    normal = base
    supplier = ParagraphStyle("supplier", parent=base, fontName="Helvetica-Bold", fontSize=11)
    heading = ParagraphStyle(
        "heading", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24, spaceBefore=6
    )
    subheading = ParagraphStyle("subheading", parent=base, fontSize=13, leading=16, spaceBefore=4)
    section = ParagraphStyle("section", parent=base, fontName="Helvetica-Bold", fontSize=11)
    small = ParagraphStyle("small", parent=base, fontSize=8, textColor=colors.grey)
    cell = ParagraphStyle("cell", parent=base, fontSize=9, leading=11)
    cell_right = ParagraphStyle("cell_right", parent=cell, alignment=2)

    story: list[object] = [
        _p(data.supplier, supplier),
        _p(f"Quote {data.number}", heading),
        _p(data.title, subheading),
        Spacer(1, 4 * mm),
    ]
    facts = [
        ["For", data.customer + (f"\nAttn. {data.contact}" if data.contact else "")],
        ["Date", data.issued.isoformat()],
        ["Valid until", data.valid_until.isoformat()],
        ["Currency", data.currency],
    ]
    facts_table = Table(
        [[_p(k, cell), _p(v, cell)] for k, v in facts], colWidths=[30 * mm, 120 * mm]
    )
    facts_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [facts_table, Spacer(1, 6 * mm)]

    header = ["#", "Item", "Qty", "List price", "Disc.", "Net price", "Tax", "Amount"]
    rows: list[list[object]] = [[_p(h, cell) for h in header]]
    for ln in data.lines:
        rows.append(
            [
                _p(str(ln.position), cell),
                _p(f"{ln.description}\n{ln.sku}", cell),
                _p(f"{_number(ln.quantity)} {ln.unit}", cell_right),
                _p(_money(ln.list_price, data.currency), cell_right),
                _p(f"{_number(ln.discount_percent)} %" if ln.discount_percent else "-", cell_right),
                _p(_money(ln.net_unit_price, data.currency), cell_right),
                _p(f"{_number(ln.tax_rate)} %", cell_right),
                _p(_money(ln.line_subtotal, data.currency), cell_right),
            ]
        )
    lines_table = Table(
        rows,
        colWidths=[8 * mm, 52 * mm, 18 * mm, 24 * mm, 12 * mm, 24 * mm, 12 * mm, 24 * mm],
        repeatRows=1,
    )
    lines_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story += [lines_table, Spacer(1, 4 * mm)]

    totals = [["List value", _money(data.gross_total, data.currency)]]
    if data.discount_total:
        totals.append(["Discount", "- " + _money(data.discount_total, data.currency)])
    totals += [
        ["Net", _money(data.subtotal, data.currency)],
        ["Tax", _money(data.tax_total, data.currency)],
        ["Total", _money(data.total, data.currency)],
    ]
    totals_table = Table(
        [[_p(k, cell), _p(v, cell_right)] for k, v in totals],
        colWidths=[30 * mm, 40 * mm],
        hAlign="RIGHT",
    )
    totals_table.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.black)]))
    story.append(totals_table)

    if data.customer_note:
        story += [
            Spacer(1, 6 * mm),
            _p("Notes", section),
            _p(data.customer_note, normal),
        ]
    story += [
        Spacer(1, 10 * mm),
        _p(
            f"Prices exclude tax unless shown otherwise. This quote is valid until "
            f"{data.valid_until.isoformat()}.",
            small,
        ),
    ]
    doc.build(story)  # type: ignore[arg-type]
    return buffer.getvalue()
