"""Upload rules for knowledge files (RAG R1).

The type is decided by the file extension AND its first bytes, never by the browser's
Content-Type. Only text-extractable formats are accepted: PDF, DOCX, TXT and Markdown.
"""

import unicodedata
from dataclasses import dataclass

# "PK" + 0x03 0x04 - the zip signature shared by DOCX (Office Open XML).
_ZIP = (bytes([0x50, 0x4B, 0x03, 0x04]),)
MAX_NAME = 150
# Same limit as the documents module; the service also receives the configured limit.
MAX_BYTES = 20 * 1024 * 1024
_RESERVED = set('<>:"/|?*')


@dataclass(frozen=True)
class FileKind:
    content_type: str
    magic: tuple[bytes, ...] | None  # None: must be plain UTF-8 text


ALLOWED: dict[str, FileKind] = {
    ".pdf": FileKind("application/pdf", (b"%PDF-",)),
    ".docx": FileKind(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", _ZIP
    ),
    ".txt": FileKind("text/plain", None),
    ".md": FileKind("text/markdown", None),
    ".markdown": FileKind("text/markdown", None),
}
ALLOWED_LABEL = "PDF, Word (.docx), plain text (.txt) or Markdown (.md)"


def extension(name: str) -> str:
    _, dot, ext = name.rpartition(".")
    return f".{ext.lower()}" if dot else ""


def clean_file_name(raw: str | None) -> str:
    """A safe display name: no folders, control or reserved characters, at most 150 chars."""
    name = unicodedata.normalize("NFC", raw or "")
    # A backslash is written as chr(92) so this module contains no escape sequences.
    name = name.replace(chr(92), "/").split("/")[-1]
    kept: list[str] = []
    for character in name:
        code = ord(character)
        kept.append("_" if character in _RESERVED or code < 32 or code == 127 else character)
    name = " ".join("".join(kept).split()).strip(" .")
    if not name:
        return "document"
    stem, dot, ext = name.rpartition(".")
    if dot and stem and len(ext) <= 10:
        return stem[: MAX_NAME - len(ext) - 1].rstrip(" .") + "." + ext
    return name[:MAX_NAME]


def title_from(name: str) -> str:
    stem = name.rsplit(".", 1)[0].strip() or name
    return stem[:200]


def detect(name: str, head: bytes) -> FileKind | None:
    """The accepted kind for this name/content, or None when the file cannot be ingested."""
    kind = ALLOWED.get(extension(name))
    if kind is None or not head:
        return None
    if kind.magic is None:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return None if 0 in head else kind
    return kind if head.startswith(kind.magic) else None
