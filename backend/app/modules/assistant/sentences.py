"""Cut a streamed answer into whole, cleaned sentences (ADR 0023, step VM1).

A model streams its answer in small pieces ("Your ti", "cket is op", "en. It was..."). To speak
the first sentence early we must send it on as soon as it is COMPLETE - but never a piece of a
sentence, because the exit cleaning of ADR 0018 (links to other sites and images removed, secret
markers refused) only works on whole text: a link split over two pieces would slip through if each
piece were cleaned on its own.

So the stream is held back until a sentence ends (". ", "! ", "? " or a line break) AND no
bracket of a Markdown link or image is still open. Each finished sentence is then cleaned with the
same ``sanitise_output`` the whole answer gets. A sentence that trips a secret marker becomes the
fixed safe answer and the stream stops there: nothing after it is sent.
"""

import re
from dataclasses import dataclass, field

from app.modules.assistant.guardrails import MAX_OUTPUT_CHARS, SAFE_OUTPUT, sanitise_output

# The end of a sentence: punctuation followed by white space, or a line break.
_END = re.compile(r"[.!?…](?=\s)|\n")


# How much text may wait for an open bracket to close before it is cut anyway.
HOLD_LIMIT = 600


def _brackets_open(text: str) -> bool:
    """True while a Markdown link or image ``[text](address)`` is not finished."""
    return text.count("[") > text.count("]") or text.count("(") > text.count(")")


@dataclass
class SentenceStream:
    """Feed it the model's pieces; it hands back finished, cleaned sentences."""

    _buffer: str = ""
    _seen: int = 0
    blocked: bool = False  # a sentence was refused: the rest of the answer is not sent
    full: bool = False  # the length cap was reached: what came after it is dropped
    sent: list[str] = field(default_factory=list)

    def feed(self, piece: str) -> list[str]:
        if self.blocked or self.full or not piece:
            return []
        room = MAX_OUTPUT_CHARS - self._seen
        self._seen += len(piece)
        self._buffer += piece[: max(0, room)]
        out: list[str] = []
        while True:
            cut = self._next_cut()
            if cut is None:
                break
            sentence, self._buffer = self._buffer[:cut], self._buffer[cut:]
            out.extend(self._emit(sentence))
            if self.blocked:
                break
        if self._seen >= MAX_OUTPUT_CHARS and not self.blocked:
            # The whole answer is capped at the same length as a non-streamed one.
            out.extend(self.flush())
            self.full = True
        return out

    def flush(self) -> list[str]:
        """The rest of the text when the model has finished."""
        if self.blocked or self.full:
            return []
        rest, self._buffer = self._buffer, ""
        return self._emit(rest)

    def _next_cut(self) -> int | None:
        ends = [match.end() for match in _END.finditer(self._buffer)]
        for cut in ends:
            if not _brackets_open(self._buffer[:cut]):
                return cut
        # A stray "(" must not hold back the whole answer. Past this length the sentence is cut
        # anyway: the cleaning also removes a bare or half-written address, so nothing leaks.
        if ends and len(self._buffer) > HOLD_LIMIT:
            return ends[0]
        return None

    def _emit(self, sentence: str) -> list[str]:
        if not sentence.strip():
            return []
        clean = sanitise_output(sentence)
        if clean == SAFE_OUTPUT:
            self.blocked = True
        self.sent.append(clean)
        return [clean]
