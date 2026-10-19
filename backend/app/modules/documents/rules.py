"""Upload rules: which files are allowed and how names are cleaned. Pure functions, unit-tested.

The file type is decided by the file's extension AND its first bytes ("magic number"), never by
the Content-Type the browser sends. The stored content type comes from this table, and
downloads are always sent as attachments with "nosniff", so a file can't run in the browser.
"""

import re
import unicodedata
from dataclasses import dataclass

_ZIP = (b"PK\x03\x04",)  # Office (docx/xlsx/pptx) and OpenDocument files are zip containers


@dataclass(frozen=True)
class FileKind:
    content_type: str
    magic: tuple[bytes, ...] | None  # None: must be plain UTF-8 text


ALLOWED: dict[str, FileKind] = {
    ".pdf": FileKind("application/pdf", (b"%PDF-",)),
    ".png": FileKind("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": FileKind("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": FileKind("image/jpeg", (b"\xff\xd8\xff",)),
    ".gif": FileKind("image/gif", (b"GIF87a", b"GIF89a")),
    ".txt": FileKind("text/plain", None),
    ".csv": FileKind("text/csv", None),
    ".docx": FileKind(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", _ZIP
    ),
    ".xlsx": FileKind("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _ZIP),
    ".pptx": FileKind(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation", _ZIP
    ),
    ".odt": FileKind("application/vnd.oasis.opendocument.text", _ZIP),
    ".ods": FileKind("application/vnd.oasis.opendocument.spreadsheet", _ZIP),
}
ALLOWED_LABEL = "PDF, images (PNG, JPG, GIF), text/CSV, Word, Excel, PowerPoint, OpenDocument"
MAX_NAME = 150
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


def clean_file_name(raw: str | None) -> str:
    """A safe display/download name: no folders, no control or reserved characters, at most
    150 characters, extension kept."""
    name = unicodedata.normalize("NFC", raw or "")
    name = re.split(r"[\\/]", name)[-1]  # "C:\\x\\..\\report.pdf" -> "report.pdf"
    name = _BAD_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        return "file"
    stem, dot, ext = name.rpartition(".")
    if dot and stem and len(ext) <= 10:
        return stem[: MAX_NAME - len(ext) - 1].rstrip(" .") + "." + ext
    return name[:MAX_NAME]


def extension(name: str) -> str:
    _, dot, ext = name.rpartition(".")
    return f".{ext.lower()}" if dot else ""


def detect(name: str, head: bytes) -> FileKind | None:
    """The allowed kind for this name and content, or None if the file isn't allowed."""
    kind = ALLOWED.get(extension(name))
    if kind is None:
        return None
    if kind.magic is None:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return None if b"\x00" in head else kind
    return kind if head.startswith(kind.magic) else None
