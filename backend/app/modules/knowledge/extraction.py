"""Extract headings and paragraph blocks from PDF, DOCX, TXT and Markdown (RAG R1).

The result is a list of Sections. A Section keeps its heading path (for search quality and
citations) and its paragraphs as separate blocks (so a later answer can cite exact sentences).
"""

from dataclasses import dataclass
from io import BytesIO

from app.modules.knowledge.rules import extension


@dataclass(frozen=True)
class Section:
    heading_path: str
    blocks: list[str]
    page_from: int | None = None
    page_to: int | None = None


class ExtractionError(Exception):
    """The file cannot be read as text (corrupt or unsupported content)."""


def _paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs; single newlines inside a paragraph are joined."""
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            current.append(stripped)
        elif current:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    return [block for block in blocks if block.strip()]


def _markdown_sections(text: str) -> list[Section]:
    sections: list[Section] = []
    path: list[tuple[int, str]] = []
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            blocks.append(" ".join(current))
            current.clear()

    def emit() -> None:
        flush()
        if blocks:
            heading = " > ".join(title for _, title in path)
            sections.append(Section(heading, list(blocks)))
            blocks.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[hashes:].strip()
            if title and 1 <= hashes <= 6:
                emit()
                while path and path[-1][0] >= hashes:
                    path.pop()
                path.append((hashes, title))
                continue
        if not stripped:
            flush()
        else:
            current.append(stripped)
    emit()
    return sections


def _docx_sections(data: bytes) -> list[Section]:
    from docx import Document  # imported lazily: only needed for .docx

    document = Document(BytesIO(data))
    sections: list[Section] = []
    path: list[tuple[int, str]] = []
    blocks: list[str] = []

    def emit() -> None:
        if blocks:
            sections.append(Section(" > ".join(title for _, title in path), list(blocks)))
            blocks.clear()

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = (paragraph.style.name if paragraph.style is not None else "") or ""
        if style.startswith("Heading "):
            emit()
            try:
                level = int(style.split(" ", 1)[1])
            except ValueError:
                level = 1
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, text))
        elif style == "Title":
            emit()
            path = [(1, text)]
        else:
            blocks.append(text)
    emit()
    return sections


def _pdf_sections(data: bytes) -> list[Section]:
    from pypdf import PdfReader  # imported lazily: only needed for .pdf

    try:
        reader = PdfReader(BytesIO(data))
        sections: list[Section] = []
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            blocks = _paragraphs(text)
            if blocks:
                sections.append(Section("", blocks, number, number))
        return sections
    except Exception as exc:
        raise ExtractionError("The PDF could not be read.") from exc


def extract_sections(file_name: str, data: bytes) -> list[Section]:
    """Text sections of the file, or an empty list when it contains no readable text."""
    kind = extension(file_name)
    if kind == ".pdf":
        return _pdf_sections(data)
    if kind == ".docx":
        try:
            return _docx_sections(data)
        except Exception as exc:
            raise ExtractionError("The Word document could not be read.") from exc
    text = data.decode("utf-8", errors="strict")
    if kind in (".md", ".markdown"):
        sections = _markdown_sections(text)
    else:
        blocks = _paragraphs(text)
        sections = [Section("", blocks)] if blocks else []
    return sections


def page_count(sections: list[Section]) -> int:
    return max((section.page_to or 0 for section in sections), default=0)
