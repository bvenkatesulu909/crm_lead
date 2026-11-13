"""The proposal deck (ADR 0032, PD2): landscape 16:9 pages drawn with ReportLab from plain data.

Pages: cover, about us (when the organisation wrote one), what we propose (10 lines a page), the
investment, notes and terms (when there are any) and next steps with the contact line. The numbers
come from the quote record exactly as the quote PDF shows them.

Everything a person typed (titles, names, notes, the organisation's texts) is escaped and drawn as
plain text; a character the bundled Noto Sans has no picture for becomes ``?``. The PDF has no
links, no scripts and no outside pictures: the only image is the organisation's own re-encoded
logo. The same data always gives the same bytes (ReportLab's ``invariant`` mode).
"""

import io
import threading
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Frame, KeepInFrame, Paragraph, Table, TableStyle

from app.modules.branding import api as branding_api
from app.modules.proposal_decks import rules
from app.modules.proposal_decks.data import DeckData, DeckLine

WIDTH, HEIGHT = 960.0, 540.0  # 16:9, 13.33 x 7.5 inches
MARGIN = 60.0
BODY_WIDTH = WIDTH - 2 * MARGIN
REGULAR, BOLD = "NotoSans", "NotoSans-Bold"
_FONT_DIR = Path(__file__).with_name("fonts")

_lock = threading.Lock()
_registered = False
_glyphs: frozenset[int] = frozenset()


def _register_fonts() -> None:
    global _registered, _glyphs
    with _lock:
        if _registered:
            return
        for name, file in ((REGULAR, "NotoSans-Regular.ttf"), (BOLD, "NotoSans-Bold.ttf")):
            font = TTFont(name, str(_FONT_DIR / file))
            pdfmetrics.registerFont(font)
            if name == REGULAR:
                _glyphs = frozenset(font.face.charToGlyph)
        pdfmetrics.registerFontFamily(
            REGULAR, normal=REGULAR, bold=BOLD, italic=REGULAR, boldItalic=BOLD
        )
        _registered = True


def drawable_characters() -> frozenset[int]:
    """The characters the bundled font can draw (for tests and callers that want to warn)."""
    _register_fonts()
    return _glyphs


def _text(value: str) -> str:
    return rules.printable(value, _glyphs)


def _para(value: str, style: ParagraphStyle) -> Paragraph:
    # Paragraph understands a little markup, so typed text is escaped: "<b>" prints as typed.
    return Paragraph(escape(_text(value)).replace("\n", "<br/>"), style)


def _style(
    size: float,
    *,
    bold: bool = False,
    color: str = "#1b1f24",
    align: Literal[0, 1, 2, 4] = 0,
    leading: float | None = None,
) -> ParagraphStyle:
    return ParagraphStyle(
        f"s{size}{bold}{color}{align}",
        fontName=BOLD if bold else REGULAR,
        fontSize=size,
        leading=leading or size * 1.3,
        textColor=HexColor(color),
        alignment=align,
    )


def _fit(
    c: Canvas, flowables: Sequence[Paragraph], x: float, y: float, width: float, height: float
) -> None:
    """Draw ``flowables`` in the box, shrinking them when they would overflow: text never runs off
    the slide."""
    frame = Frame(x, y, width, height, leftPadding=0, bottomPadding=0, rightPadding=0, topPadding=0)
    frame.addFromList([KeepInFrame(width, height, list(flowables), mode="shrink")], c)


class _Deck:
    def __init__(self, data: DeckData) -> None:
        self.d = data
        self.b = data.brand
        self.accent = HexColor(f"#{data.brand.color}")
        self.on_accent = f"#{branding_api.text_color_for(data.brand.color)}"

    def money(self, amount: Decimal) -> str:
        return rules.money(amount, self.d.currency)

    # --- the slides ---------------------------------------------------------------------

    def slides(self) -> list[tuple[bool, Callable[[Canvas], None]]]:
        """(has the usual page frame?, how to draw it). The cover has no frame."""
        out: list[tuple[bool, Callable[[Canvas], None]]] = [(False, self.cover)]
        if self.b.about_text.strip():
            out.append((True, self.about))
        chunks = rules.pages(self.d.lines)
        for index, chunk in enumerate(chunks, start=1):
            out.append((True, self._propose(chunk, index, len(chunks))))
        out.append((True, self.investment))
        if (self.d.customer_note or "").strip() or self.b.terms_text.strip():
            out.append((True, self.terms))
        out.append((True, self.next_steps))
        return out

    def render(self, *, compress: bool) -> bytes:
        _register_fonts()
        buffer = io.BytesIO()
        c = Canvas(
            buffer,
            pagesize=(WIDTH, HEIGHT),
            pageCompression=1 if compress else 0,
            invariant=1,
        )
        c.setTitle(_text(f"{self.d.title} - {self.d.number}"))
        c.setAuthor(_text(self.b.organisation))
        c.setCreator("crm-lead")
        slides = self.slides()
        for number, (framed, draw) in enumerate(slides, start=1):
            draw(c)
            if framed:
                self._chrome(c, number, len(slides))
            c.showPage()
        c.save()
        return buffer.getvalue()

    def _chrome(self, c: Canvas, number: int, total: int) -> None:
        c.setFillColor(self.accent)
        c.rect(0, HEIGHT - 10, WIDTH, 10, stroke=0, fill=1)
        c.setStrokeColor(Color(0.85, 0.87, 0.9))
        c.line(MARGIN, 44, WIDTH - MARGIN, 44)
        c.setFillColor(HexColor("#5b6470"))
        c.setFont(REGULAR, 10)
        c.drawString(MARGIN, 26, _text(self.b.footer_line.strip() or self.b.organisation))
        c.drawRightString(WIDTH - MARGIN, 26, f"{number} / {total}")

    def _heading(self, c: Canvas, text: str) -> None:
        c.setFillColor(self.accent)
        c.setFont(BOLD, 30)
        c.drawString(MARGIN, HEIGHT - 82, _text(text))

    def cover(self, c: Canvas) -> None:
        c.setFillColor(self.accent)
        c.rect(0, 0, WIDTH, HEIGHT, stroke=0, fill=1)
        top = HEIGHT - MARGIN
        if self.b.logo_png:
            self._logo(c, MARGIN, top)
        else:
            c.setFillColor(HexColor(self.on_accent))
            c.setFont(BOLD, 22)
            c.drawString(MARGIN, top - 22, _text(self.b.organisation))
        title = _para(self.d.title, _style(40, bold=True, color=self.on_accent, leading=48))
        _fit(c, [title], MARGIN, 190, BODY_WIDTH, 190)
        c.setFillColor(HexColor(self.on_accent))
        c.setFont(REGULAR, 13)
        c.drawString(MARGIN, 150, "Prepared for")
        c.setFont(BOLD, 24)
        c.drawString(MARGIN, 120, _text(self.d.customer)[:80])
        if self.d.contact:
            c.setFont(REGULAR, 16)
            c.drawString(MARGIN, 96, _text(self.d.contact)[:80])
        c.setFont(REGULAR, 12)
        c.drawString(MARGIN, 56, f"Proposal {self.d.number} · {rules.long_date(self.d.issued)}")

    def _logo(self, c: Canvas, x: float, top: float) -> None:
        """The logo on a white chip (logos are often dark), scaled to fit a 220 x 64 box."""
        if self.b.logo_png is None:
            raise ValueError("no logo to draw")
        reader = ImageReader(io.BytesIO(self.b.logo_png))
        width, height = reader.getSize()
        scale = min(220 / width, 64 / height)
        w, h = width * scale, height * scale
        c.setFillColor(white)
        c.roundRect(x, top - h - 16, w + 24, h + 16, 8, stroke=0, fill=1)
        c.drawImage(reader, x + 12, top - h - 8, width=w, height=h, mask="auto")

    def about(self, c: Canvas) -> None:
        self._heading(c, f"About {self.b.organisation}"[:60])
        _fit(c, [_para(self.b.about_text, _style(16, leading=23))], MARGIN, 70, BODY_WIDTH, 370)

    def _propose(self, chunk: list[DeckLine], index: int, count: int) -> Callable[[Canvas], None]:
        def draw(c: Canvas) -> None:
            self._heading(c, "What we propose" + (f" ({index} of {count})" if count > 1 else ""))
            self._lines_table(c, chunk)

        return draw

    def _lines_table(self, c: Canvas, chunk: list[DeckLine]) -> None:
        head = _style(11, bold=True, color=self.on_accent)
        right = _style(12, align=2)
        body = _style(12)
        rows: list[list[Paragraph]] = [
            [
                _para("#", head),
                _para("Description", head),
                _para("Quantity", _style(11, bold=True, color=self.on_accent, align=2)),
                _para("Unit price", _style(11, bold=True, color=self.on_accent, align=2)),
                _para("Line total", _style(11, bold=True, color=self.on_accent, align=2)),
            ]
        ]
        for line in chunk:
            price = self.money(line.net_unit_price)
            if line.discount_percent > 0:
                price += f"\n{rules.plain_number(line.discount_percent)} % off"
            quantity = f"{rules.plain_number(line.quantity)} {line.unit}".strip()
            rows.append(
                [
                    _para(str(line.position), body),
                    _para(line.description, body),
                    _para(quantity, right),
                    _para(price, right),
                    _para(self.money(line.line_subtotal), right),
                ]
            )
        table = Table(rows, colWidths=[34, 410, 100, 150, 146], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), self.accent),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.5, Color(0.85, 0.87, 0.9)),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        _, height = table.wrapOn(c, BODY_WIDTH, HEIGHT)
        table.drawOn(c, MARGIN, max(60, HEIGHT - 110 - height))

    def investment(self, c: Canvas) -> None:
        self._heading(c, "Investment")
        d = self.d
        label, value = _style(15), _style(15, align=2)
        strong, strong_value = _style(20, bold=True), _style(20, bold=True, align=2)
        rows: list[list[Paragraph]] = [
            [_para("Total before discount", label), _para(self.money(d.gross_total), value)]
        ]
        if d.discount_total != 0:
            rows.append([_para("Discount", label), _para(self.money(-d.discount_total), value)])
        rows += [
            [_para("Subtotal", label), _para(self.money(d.subtotal), value)],
            [_para("Tax", label), _para(self.money(d.tax_total), value)],
            [_para("Total", strong), _para(self.money(d.total), strong_value)],
        ]
        table = Table(rows, colWidths=[300, 220])
        table.setStyle(
            TableStyle(
                [
                    ("LINEABOVE", (0, -1), (-1, -1), 1.5, self.accent),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        _, height = table.wrapOn(c, 520, HEIGHT)
        table.drawOn(c, MARGIN, HEIGHT - 120 - height)
        c.setFillColor(self.accent)
        c.setFont(BOLD, 16)
        c.drawString(MARGIN, 92, f"This proposal is valid until {rules.long_date(d.valid_until)}.")

    def terms(self, c: Canvas) -> None:
        self._heading(c, "Notes and terms")
        columns: list[tuple[str, str]] = []
        if (self.d.customer_note or "").strip():
            columns.append(("Notes for you", self.d.customer_note or ""))
        if self.b.terms_text.strip():
            columns.append(("Our standard terms", self.b.terms_text))
        gap = 40.0
        width = (BODY_WIDTH - gap * (len(columns) - 1)) / len(columns)
        for index, (title, text) in enumerate(columns):
            x = MARGIN + index * (width + gap)
            _fit(
                c,
                [
                    _para(title, _style(15, bold=True, color=f"#{self.b.color}")),
                    _para("", _style(6)),
                ],
                x,
                390,
                width,
                30,
            )
            _fit(c, [_para(text, _style(14, leading=20))], x, 70, width, 320)

    def next_steps(self, c: Canvas) -> None:
        self._heading(c, "Next steps")
        steps = [
            f"Read this proposal and quote {self.d.number}.",
            "Tell us your questions or what you would like changed - we will update the quote.",
            "Accept the quote and we will confirm your order.",
        ]
        y = HEIGHT - 135
        for number, step in enumerate(steps, start=1):
            c.setFillColor(self.accent)
            c.circle(MARGIN + 14, y + 5, 14, stroke=0, fill=1)
            c.setFillColor(HexColor(self.on_accent))
            c.setFont(BOLD, 14)
            c.drawCentredString(MARGIN + 14, y, str(number))
            _fit(c, [_para(step, _style(17, leading=23))], MARGIN + 46, y - 20, BODY_WIDTH - 46, 36)
            y -= 70
        contact = self.b.contact_line.strip()
        if contact:
            c.setFillColor(self.accent)
            c.setFont(BOLD, 14)
            c.drawString(MARGIN, 120, "Contact")
            _fit(c, [_para(contact, _style(18, leading=24))], MARGIN, 70, BODY_WIDTH, 40)


def render_deck(data: DeckData, *, compress: bool = True) -> bytes:
    """The deck as PDF bytes. ``compress=False`` keeps the page content readable (used by tests)."""
    return _Deck(data).render(compress=compress)
