"""Pure rules of call recordings (ADR 0030): the vocabulary, what a file name and its first
bytes must look like, consent and size. No database, no network, no ffmpeg, no speech engine."""

import unicodedata
from datetime import datetime, timedelta

LANGUAGES = ("hi", "te", "en")
STATUSES = ("uploading", "queued", "processing", "ready", "failed", "expired")

# The type of an audio file follows its extension; its first bytes must agree (``looks_like``).
AUDIO_TYPES: dict[str, str] = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
    "amr": "audio/amr",
}
# How much of the start of a file is read to check what it really is.
HEAD_BYTES = 64
FILE_NAME_MAX = 150


class CallRuleError(ValueError):
    """A recording (or its file) that breaks a rule."""


class CallTypeError(CallRuleError):
    """The file type is not one of the allowed audio types."""


class CallTooLargeError(CallRuleError):
    """The recording is larger than the limit."""


def clean_file_name(raw: object) -> str:
    """The "save as" name: the last path segment, no control characters, at most 150 characters,
    with a stem and an extension. Names in any script are kept."""
    if not isinstance(raw, str):
        raise CallRuleError("The file name must be text.")
    last = raw.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in last if unicodedata.category(ch) != "Cc").strip()
    if not cleaned:
        raise CallRuleError("The file needs a name.")
    if len(cleaned) > FILE_NAME_MAX:
        raise CallRuleError(f"The file name is too long (at most {FILE_NAME_MAX} characters).")
    stem, dot, extension = cleaned.rpartition(".")
    if not dot or not stem.strip() or not extension:
        raise CallRuleError("The file name needs an extension such as .mp3.")
    return cleaned


def kind_of(file_name: str) -> str:
    """The audio type of a (cleaned) file name, from its extension."""
    extension = file_name.rpartition(".")[2].lower()
    if extension not in AUDIO_TYPES:
        raise CallTypeError(
            "This file type isn't allowed. Allowed: "
            + ", ".join(f".{e}" for e in AUDIO_TYPES)
            + "."
        )
    return extension


def looks_like(kind: str, head: bytes) -> bool:
    """Do the first bytes of a file match the type its name claims?"""
    if kind == "mp3":
        return head.startswith(b"ID3") or (
            len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0
        )
    if kind == "wav":
        return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    if kind == "ogg":
        return head.startswith(b"OggS")
    if kind == "m4a":
        return len(head) >= 12 and head[4:8] == b"ftyp"
    if kind == "webm":
        return head.startswith(b"\x1a\x45\xdf\xa3")
    if kind == "amr":
        return head.startswith(b"#!AMR")
    return False


def check_consent(value: object) -> None:
    """The buyer must have agreed to the call being recorded - an explicit True, nothing else."""
    if value is not True:
        raise CallRuleError("The buyer must have agreed to the call being recorded.")


def check_size(size: int, limit: int) -> None:
    if size < 1:
        raise CallRuleError("The recording is empty.")
    if size > limit:
        raise CallTooLargeError(f"The recording is larger than {limit // (1024 * 1024)} MB.")


def retention_cutoff(now: datetime, days: int) -> datetime:
    """Recordings added before this moment have passed their retention."""
    return now - timedelta(days=days)
