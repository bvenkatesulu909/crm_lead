"""Chunking rules from ADR 0011: ~1,600 characters, one-paragraph overlap, heading path kept.

Pure functions: deterministic and independent of the database, so they are unit-tested directly.
"""

import re
from dataclasses import dataclass

from app.modules.knowledge.extraction import Section

CHUNKING_VERSION = "1"
TARGET_CHARS = 1_600
MIN_CHARS = 200
OVERLAP_PARAGRAPHS = 1


@dataclass(frozen=True)
class Chunk:
    heading_path: str
    blocks: list[str]
    page_from: int | None = None
    page_to: int | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.blocks)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def embedding_text(self) -> str:
        return f"{self.heading_path}\n{self.text}" if self.heading_path else self.text


def _split_long(paragraph: str, target: int = TARGET_CHARS) -> list[str]:
    if len(paragraph) <= target:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    pieces: list[str] = []
    buffer = ""
    for sentence in sentences:
        if not sentence:
            continue
        if buffer and len(buffer) + 1 + len(sentence) > target:
            pieces.append(buffer)
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}".strip()
    if buffer:
        pieces.append(buffer)
    result: list[str] = []
    for piece in pieces:
        while len(piece) > target:
            result.append(piece[:target])
            piece = piece[target:]
        if piece:
            result.append(piece)
    return result or [paragraph[:target]]


def chunk_sections(sections: list[Section]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in sections:
        buffer: list[str] = []
        size = 0
        for block in section.blocks:
            for paragraph in _split_long(block):
                if buffer and size + len(paragraph) + 1 > TARGET_CHARS:
                    chunks.append(
                        Chunk(section.heading_path, buffer, section.page_from, section.page_to)
                    )
                    buffer = buffer[-OVERLAP_PARAGRAPHS:] if OVERLAP_PARAGRAPHS else []
                    size = sum(len(item) + 1 for item in buffer)
                    # The carried paragraph may itself be close to the target; drop the
                    # overlap rather than produce an oversized chunk.
                    if buffer and size + len(paragraph) + 1 > TARGET_CHARS:
                        buffer = []
                        size = 0
                buffer.append(paragraph)
                size += len(paragraph) + 1
        if buffer and any(item.strip() for item in buffer):
            chunks.append(Chunk(section.heading_path, buffer, section.page_from, section.page_to))

    merged: list[Chunk] = []
    for chunk in chunks:
        if (
            merged
            and chunk.char_count < MIN_CHARS
            and merged[-1].heading_path == chunk.heading_path
        ):
            previous = merged[-1]
            merged[-1] = Chunk(
                previous.heading_path,
                previous.blocks + chunk.blocks,
                previous.page_from or chunk.page_from,
                chunk.page_to or previous.page_to,
            )
        else:
            merged.append(chunk)
    return merged
