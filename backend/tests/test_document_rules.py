"""Upload rules: allowed file types (by name AND content) and clean file names."""

import pytest

from app.modules.documents.rules import ALLOWED, clean_file_name, detect

PDF = b"%PDF-1.7 test"
PNG = b"\x89PNG\r\n\x1a\n...."


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("offer.pdf", "offer.pdf"),
        ("C:\\Users\\x\\..\\report.PDF", "report.PDF"),
        ("../../etc/passwd", "passwd"),
        ('bad<>:"|?*name.pdf', "bad_______name.pdf"),
        ("  spaced   out  .pdf  ", "spaced out.pdf"),
        ("line\nbreak\r\x00.pdf", "line_break__.pdf"),
        ("", "file"),
        (None, "file"),
        ("...", "file"),
        ("a" * 300 + ".pdf", "a" * 146 + ".pdf"),
    ],
)
def test_file_names_are_cleaned(raw: str | None, clean: str) -> None:
    assert clean_file_name(raw) == clean


@pytest.mark.parametrize(
    ("name", "head", "content_type"),
    [
        ("a.pdf", PDF, "application/pdf"),
        ("a.PDF", PDF, "application/pdf"),
        ("a.png", PNG, "image/png"),
        ("a.jpg", b"\xff\xd8\xff\xe0", "image/jpeg"),
        ("a.txt", "Grüße, plain text".encode(), "text/plain"),
        ("a.csv", b"a;b\n1;2\n", "text/csv"),
        ("a.docx", b"PK\x03\x04rest", ALLOWED[".docx"].content_type),
    ],
)  # fmt: skip
def test_allowed_files(name: str, head: bytes, content_type: str) -> None:
    kind = detect(name, head)
    assert kind is not None and kind.content_type == content_type


@pytest.mark.parametrize(
    ("name", "head"),
    [
        ("a.exe", b"MZ\x90\x00"),  # programs are never allowed
        ("a.html", b"<html><script>"),  # would run in a browser
        ("a.svg", b"<svg onload=alert(1)>"),  # SVG can carry scripts
        ("a.pdf", PNG),  # name says PDF, content doesn't
        ("a.png", PDF),
        ("a.txt", b"\x00\x01binary"),
        ("a.txt", b"\xff\xfe\xfa invalid utf-8"),
        ("no_extension", PDF),
        ("a.docx", b"not a zip"),
    ],
)
def test_refused_files(name: str, head: bytes) -> None:
    assert detect(name, head) is None
