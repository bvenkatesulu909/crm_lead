"""The photo slide of the proposal deck (ADR 0039, PE5): pure, no database. Both renderers draw it
from ``DeckData.photos``; without photos there is no such slide; at most four photos; each picture
is drawn with its fixed caption. The pictures are counted back out of the finished files."""

import io
from dataclasses import replace

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pypdf import PdfReader

from app.modules.photo_enhancer import rules as photo_rules
from app.modules.proposal_decks.data import MAX_DECK_PHOTOS, DeckPhoto
from app.modules.proposal_decks.render import render_deck
from app.modules.proposal_decks.render_pptx import render_pptx
from tests.test_proposal_deck import data

CAPTION = photo_rules.DECK_CAPTION


def jpeg(
    colour: tuple[int, int, int] = (90, 120, 150), size: tuple[int, int] = (300, 200)
) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="JPEG")
    return out.getvalue()


def photos(count: int) -> tuple[DeckPhoto, ...]:
    return tuple(DeckPhoto(jpeg((40 * i % 255, 90, 160)), CAPTION) for i in range(count))


def pdf_pages(blob: bytes) -> list[str]:
    return [p.extract_text() for p in PdfReader(io.BytesIO(blob)).pages]


def pdf_images(blob: bytes) -> int:
    return sum(len(page.images) for page in PdfReader(io.BytesIO(blob)).pages)


def pptx_slides(blob: bytes) -> list[str]:
    return [
        "\n".join(s.text_frame.text for s in slide.shapes if s.has_text_frame)
        for slide in Presentation(io.BytesIO(blob)).slides
    ]


def pptx_pictures(blob: bytes) -> int:
    return sum(
        1
        for slide in Presentation(io.BytesIO(blob)).slides
        for shape in slide.shapes
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
    )


class TestSlide:
    def test_the_pdf_has_the_slide_only_with_photos(self) -> None:
        without = pdf_pages(render_deck(data(), compress=False))
        with_photos = pdf_pages(render_deck(replace(data(), photos=photos(2)), compress=False))
        assert len(with_photos) == len(without) + 1
        assert not any("The property" in p for p in without)
        assert sum("The property" in p for p in with_photos) == 1

    def test_the_powerpoint_has_the_slide_only_with_photos(self) -> None:
        without = pptx_slides(render_pptx(data()))
        with_photos = pptx_slides(render_pptx(replace(data(), photos=photos(2))))
        assert len(with_photos) == len(without) + 1
        assert not any("The property" in s for s in without)
        assert sum("The property" in s for s in with_photos) == 1

    @pytest.mark.parametrize("count", [1, 2, 3, 4])
    def test_every_photo_is_drawn_with_its_caption(self, count: int) -> None:
        blob = render_deck(replace(data(), photos=photos(count)), compress=False)
        base = pdf_images(render_deck(data(), compress=False))
        assert pdf_images(blob) == base + count
        [page] = [p for p in pdf_pages(blob) if "The property" in p]
        assert page.count(CAPTION) == count
        pptx = render_pptx(replace(data(), photos=photos(count)))
        assert pptx_pictures(pptx) == pptx_pictures(render_pptx(data())) + count
        [slide] = [s for s in pptx_slides(pptx) if "The property" in s]
        assert slide.count(CAPTION) == count

    def test_at_most_four_photos_are_drawn(self) -> None:
        assert MAX_DECK_PHOTOS == 4
        d = replace(data(), photos=photos(7))
        base = pdf_images(render_deck(data(), compress=False))
        assert pdf_images(render_deck(d, compress=False)) == base + 4
        assert pptx_pictures(render_pptx(d)) == pptx_pictures(render_pptx(data())) + 4

    def test_it_comes_before_the_lines_and_after_about_us(self) -> None:
        d = replace(data(), photos=photos(1))
        for titles in (
            [i for i, p in enumerate(pdf_pages(render_deck(d, compress=False)))],
            [i for i, _ in enumerate(pptx_slides(render_pptx(d)))],
        ):
            assert titles  # the decks still draw
        pages = pdf_pages(render_deck(d, compress=False))
        position = next(i for i, p in enumerate(pages) if "The property" in p)
        propose = next(i for i, p in enumerate(pages) if "What we propose" in p)
        about = next((i for i, p in enumerate(pages) if p.startswith("About")), -1)
        assert about < position < propose
        slides = pptx_slides(render_pptx(d))
        position = next(i for i, s in enumerate(slides) if "The property" in s)
        propose = next(i for i, s in enumerate(slides) if "What we propose" in s)
        assert position < propose

    def test_the_same_photos_give_the_same_bytes(self) -> None:
        d = replace(data(), photos=photos(3))
        assert render_deck(d) == render_deck(d)
        assert render_pptx(d) == render_pptx(d)

    def test_a_tall_photo_is_scaled_to_fit_not_stretched(self) -> None:
        tall = DeckPhoto(jpeg(size=(100, 400)), CAPTION)
        pdf = render_deck(replace(data(), photos=(tall,)), compress=False)
        [page] = [p for p in PdfReader(io.BytesIO(pdf)).pages if "The property" in p.extract_text()]
        [image] = page.images
        assert Image.open(io.BytesIO(image.data)).size == (100, 400)
