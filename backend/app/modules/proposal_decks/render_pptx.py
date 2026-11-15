"""The proposal deck as a PowerPoint file (ADR 0032 Amendment A, PD6).

The same plain data and the same slides as the PDF (``render.py``): cover, about us, what we propose
(10 lines a slide), investment, notes and terms, next steps. The numbers are formatted by the same
``rules`` functions, so the two files can never disagree.

Safety, as for the PDF: everything a person typed is plain text in a run (never markup, never a
link); there are no hyperlinks, no macros, no embedded objects and no outside pictures - the only
image is the organisation's own re-encoded logo. The same data always gives the same bytes (the
file's timestamps are fixed). The text is not shrunk by PowerPoint when the file is opened, so the
font size is chosen up front from a length estimate (``rules.fit_font_size``).

This is the only module that imports ``python-pptx`` (a guard test checks it).
"""

import io
import re
import zipfile
from datetime import UTC, datetime
from decimal import Decimal

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.presentation import Presentation as PresentationType
from pptx.slide import Slide
from pptx.table import _Cell
from pptx.util import Inches, Pt

from app.modules.branding import api as branding_api
from app.modules.proposal_decks import rules
from app.modules.proposal_decks.data import DeckData, DeckLine

FONT = "Calibri"
SLIDE_W, SLIDE_H = 13.333, 7.5  # inches, 16:9
MARGIN = 0.8
BODY_W = SLIDE_W - 2 * MARGIN
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def clean(value: str) -> str:
    """Remove the characters an Office file cannot hold (control characters). The rest is kept,
    Hindi and Telugu included: PowerPoint picks a font that has them."""
    return _BAD_XML.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))


def _rgb(hex6: str) -> RGBColor:
    return RGBColor.from_string(hex6.upper())


class _Deck:
    def __init__(self, data: DeckData) -> None:
        self.d = data
        self.b = data.brand
        self.accent = self.b.color
        self.on_accent = branding_api.text_color_for(self.b.color)
        self.prs: PresentationType = Presentation()
        self.prs.slide_width = Inches(SLIDE_W)
        self.prs.slide_height = Inches(SLIDE_H)

    def money(self, amount: Decimal) -> str:
        return rules.money(amount, self.d.currency)

    # --- building blocks ----------------------------------------------------------------

    def new_slide(self) -> Slide:
        return self.prs.slides.add_slide(self.prs.slide_layouts[6])  # the blank layout

    def rect(self, slide: Slide, x: float, y: float, w: float, h: float, color: str) -> None:
        shape = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h)
        )
        shape.fill.solid()
        shape.fill.fore_color.rgb = _rgb(color)
        shape.line.fill.background()

    def text(
        self,
        slide: Slide,
        x: float,
        y: float,
        w: float,
        h: float,
        value: str,
        *,
        size: float,
        bold: bool = False,
        color: str = "1b1f24",
        align: PP_ALIGN = PP_ALIGN.LEFT,
        min_size: float = 9,
        anchor: MSO_ANCHOR = MSO_ANCHOR.TOP,
    ) -> None:
        """A text box with plain text; the size shrinks (not below ``min_size``) until it fits."""
        text = clean(value)
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = box.text_frame
        frame.word_wrap = True
        frame.vertical_anchor = anchor
        for margin in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
            setattr(frame, margin, 0)
        fitted = rules.fit_font_size(text, width_in=w, height_in=h, max_pt=size, min_pt=min_size)
        for index, paragraph_text in enumerate(text.split("\n")):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.alignment = align
            run = paragraph.add_run()
            run.text = paragraph_text
            run.font.name = FONT
            run.font.size = Pt(fitted)
            run.font.bold = bold
            run.font.color.rgb = _rgb(color)

    def heading(self, slide: Slide, value: str) -> None:
        self.text(slide, MARGIN, 0.45, BODY_W, 0.8, value, size=30, bold=True, color=self.accent)

    def chrome(self, slide: Slide, number: int, total: int) -> None:
        self.rect(slide, 0, 0, SLIDE_W, 0.14, self.accent)
        footer = self.b.footer_line.strip() or self.b.organisation
        self.text(slide, MARGIN, 7.0, 9.5, 0.3, footer, size=10, color="5b6470")
        self.text(
            slide, SLIDE_W - MARGIN - 2, 7.0, 2, 0.3, f"{number} / {total}",
            size=10, color="5b6470", align=PP_ALIGN.RIGHT,
        )  # fmt: skip

    # --- the slides ---------------------------------------------------------------------

    def cover(self) -> None:
        slide = self.new_slide()
        self.rect(slide, 0, 0, SLIDE_W, SLIDE_H, self.accent)
        light = self.on_accent
        if self.b.logo_png:
            self.logo(slide)
        else:
            self.text(
                slide,
                MARGIN,
                0.7,
                BODY_W,
                0.5,
                self.b.organisation,
                size=22,
                bold=True,
                color=light,
            )
        self.text(
            slide,
            MARGIN,
            2.2,
            BODY_W,
            2.2,
            self.d.title,
            size=40,
            bold=True,
            color=light,
            min_size=20,
        )
        self.text(slide, MARGIN, 4.65, BODY_W, 0.35, "Prepared for", size=13, color=light)
        self.text(
            slide, MARGIN, 5.0, BODY_W, 0.5, self.d.customer[:80], size=24, bold=True, color=light
        )
        if self.d.contact:
            self.text(slide, MARGIN, 5.55, BODY_W, 0.4, self.d.contact[:80], size=16, color=light)
        line = f"Proposal {self.d.number} · {rules.long_date(self.d.issued)}"
        self.text(slide, MARGIN, 6.6, BODY_W, 0.35, line, size=12, color=light)

    def logo(self, slide: Slide) -> None:
        """The logo on a white chip (logos are often dark), scaled to fit a 3 x 0.9 inch box."""
        if self.b.logo_png is None:
            raise ValueError("no logo to draw")
        from PIL import Image

        with Image.open(io.BytesIO(self.b.logo_png)) as image:
            width, height = image.size
        scale = min(3.0 / width, 0.9 / height)
        w, h = width * scale, height * scale
        self.rect(slide, MARGIN, 0.6, w + 0.3, h + 0.25, "ffffff")
        slide.shapes.add_picture(
            io.BytesIO(self.b.logo_png), Inches(MARGIN + 0.15), Inches(0.72), Inches(w), Inches(h)
        )

    def about(self) -> Slide:
        slide = self.new_slide()
        self.heading(slide, f"About {self.b.organisation}"[:60])
        self.text(slide, MARGIN, 1.5, BODY_W, 5.2, self.b.about_text, size=16, min_size=10)
        return slide

    def summary_slide(self) -> Slide:
        slide = self.new_slide()
        self.heading(slide, "Why this proposal")
        self.text(slide, MARGIN, 1.5, BODY_W, 5.2, self.d.summary or "", size=20, min_size=11)
        return slide

    def propose(self, chunk: list[DeckLine], index: int, count: int) -> Slide:
        slide = self.new_slide()
        self.heading(slide, "What we propose" + (f" ({index} of {count})" if count > 1 else ""))
        rows = len(chunk) + 1
        frame = slide.shapes.add_table(
            rows, 5, Inches(MARGIN), Inches(1.5), Inches(BODY_W), Inches(0.4 * rows)
        )
        table = frame.table
        widths = (0.5, 5.6, 1.4, 2.4, 2.03)
        for col, inches in enumerate(widths):
            table.columns[col].width = Inches(inches)
        heads = ("#", "Description", "Quantity", "Unit price", "Line total")
        for col, head in enumerate(heads):
            self.cell(table.cell(0, col), head, bold=True, head=True, right=col >= 2)
        for row, line in enumerate(chunk, start=1):
            price = self.money(line.net_unit_price)
            if line.discount_percent > 0:
                price += f"\n{rules.plain_number(line.discount_percent)} % off"
            quantity = f"{rules.plain_number(line.quantity)} {line.unit}".strip()
            values = (
                str(line.position),
                line.description,
                quantity,
                price,
                self.money(line.line_subtotal),
            )
            for col, value in enumerate(values):
                self.cell(table.cell(row, col), value, right=col >= 2)
        return slide

    def cell(
        self,
        cell: _Cell,
        value: str,
        *,
        bold: bool = False,
        head: bool = False,
        right: bool = False,
    ) -> None:
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(self.accent if head else "ffffff")
        frame = cell.text_frame
        frame.word_wrap = True
        for index, part in enumerate(clean(value).split("\n")):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.alignment = PP_ALIGN.RIGHT if right else PP_ALIGN.LEFT
            run = paragraph.add_run()
            run.text = part
            run.font.name = FONT
            run.font.size = Pt(11 if head else 12)
            run.font.bold = bold
            run.font.color.rgb = _rgb(self.on_accent if head else "1b1f24")

    def investment(self) -> Slide:
        slide = self.new_slide()
        self.heading(slide, "Investment")
        d = self.d
        rows: list[tuple[str, str, bool]] = [
            ("Total before discount", self.money(d.gross_total), False)
        ]
        if d.discount_total != 0:
            rows.append(("Discount", self.money(-d.discount_total), False))
        rows += [
            ("Subtotal", self.money(d.subtotal), False),
            ("Tax", self.money(d.tax_total), False),
            ("Total", self.money(d.total), True),
        ]
        y = 1.6
        for label, value, strong in rows:
            size = 20 if strong else 15
            if strong:
                self.rect(slide, MARGIN, y - 0.05, 7.2, 0.03, self.accent)
                y += 0.1
            self.text(slide, MARGIN, y, 4.2, 0.5, label, size=size, bold=strong)
            self.text(
                slide,
                MARGIN + 4.2,
                y,
                3.0,
                0.5,
                value,
                size=size,
                bold=strong,
                align=PP_ALIGN.RIGHT,
            )
            y += 0.6
        until = f"This proposal is valid until {rules.long_date(d.valid_until)}."
        self.text(slide, MARGIN, 6.2, BODY_W, 0.4, until, size=16, bold=True, color=self.accent)
        return slide

    def terms(self) -> Slide:
        slide = self.new_slide()
        self.heading(slide, "Notes and terms")
        columns: list[tuple[str, str]] = []
        if (self.d.customer_note or "").strip():
            columns.append(("Notes for you", self.d.customer_note or ""))
        if self.b.terms_text.strip():
            columns.append(("Our standard terms", self.b.terms_text))
        gap = 0.6
        width = (BODY_W - gap * (len(columns) - 1)) / len(columns)
        for index, (title, body) in enumerate(columns):
            x = MARGIN + index * (width + gap)
            self.text(slide, x, 1.5, width, 0.4, title, size=15, bold=True, color=self.accent)
            self.text(slide, x, 2.05, width, 4.7, body, size=14, min_size=9)
        return slide

    def next_steps(self) -> Slide:
        slide = self.new_slide()
        self.heading(slide, "Next steps")
        steps = (
            f"Read this proposal and quote {self.d.number}.",
            "Tell us your questions or what you would like changed - we will update the quote.",
            "Accept the quote and we will confirm your order.",
        )
        y = 1.6
        for number, step in enumerate(steps, start=1):
            circle = slide.shapes.add_shape(
                MSO_SHAPE.OVAL, Inches(MARGIN), Inches(y), Inches(0.42), Inches(0.42)
            )
            circle.fill.solid()
            circle.fill.fore_color.rgb = _rgb(self.accent)
            circle.line.fill.background()
            self.text(
                slide, MARGIN, y + 0.06, 0.42, 0.3, str(number),
                size=14, bold=True, color=self.on_accent, align=PP_ALIGN.CENTER,
            )  # fmt: skip
            self.text(slide, MARGIN + 0.7, y, BODY_W - 0.7, 0.6, step, size=17)
            y += 0.95
        contact = self.b.contact_line.strip()
        if contact:
            self.text(
                slide, MARGIN, 5.2, BODY_W, 0.4, "Contact", size=14, bold=True, color=self.accent
            )
            self.text(slide, MARGIN, 5.7, BODY_W, 0.7, contact, size=18)
        return slide

    def build(self) -> bytes:
        framed: list[Slide] = []
        self.cover()
        if self.b.about_text.strip():
            framed.append(self.about())
        if (self.d.summary or "").strip():
            framed.append(self.summary_slide())
        chunks = rules.pages(self.d.lines)
        for index, chunk in enumerate(chunks, start=1):
            framed.append(self.propose(chunk, index, len(chunks)))
        framed.append(self.investment())
        if (self.d.customer_note or "").strip() or self.b.terms_text.strip():
            framed.append(self.terms())
        framed.append(self.next_steps())
        total = len(framed) + 1
        for number, slide in enumerate(framed, start=2):
            self.chrome(slide, number, total)
        moment = datetime(self.d.issued.year, self.d.issued.month, self.d.issued.day, tzinfo=UTC)
        props = self.prs.core_properties
        props.title = clean(f"{self.d.title} - {self.d.number}")[:200]
        props.author = clean(self.b.organisation)[:200]
        props.last_modified_by = "crm-lead"
        props.created = props.modified = moment.replace(tzinfo=None)
        props.revision = 1
        buffer = io.BytesIO()
        self.prs.save(buffer)
        return _tidy(buffer.getvalue())


# Parts of python-pptx's default template we do not want: a printer-settings blob and a thumbnail
# picture of a blank slide. Dropped with the relationships and content types that point at them.
_DROPPED_PARTS = ("ppt/printerSettings/", "docProps/thumbnail")
_DROPPED_RELATIONSHIP = re.compile(r"<Relationship [^>]*(printerSettings|thumbnail)[^>]*/>")
_DROPPED_DEFAULT = re.compile(r'<Default Extension="bin"[^>]*/>')


def _tidy(blob: bytes) -> bytes:
    """Write the same files again without the template leftovers and with a fixed timestamp in the
    archive, so the same data gives the same bytes (python-pptx stamps the current time)."""
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(blob)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            if info.filename.startswith(_DROPPED_PARTS):
                continue
            content = source.read(info.filename)
            if info.filename.endswith(".rels"):
                content = _DROPPED_RELATIONSHIP.sub("", content.decode("utf-8")).encode("utf-8")
            elif info.filename == "[Content_Types].xml":
                content = _DROPPED_DEFAULT.sub("", content.decode("utf-8")).encode("utf-8")
            fixed = zipfile.ZipInfo(info.filename, date_time=_FIXED_ZIP_TIME)
            fixed.compress_type = zipfile.ZIP_DEFLATED
            fixed.external_attr = info.external_attr
            target.writestr(fixed, content)
    return out.getvalue()


def render_pptx(data: DeckData) -> bytes:
    """The deck as ``.pptx`` bytes."""
    return _Deck(data).build()
