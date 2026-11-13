"""Cleaning a recording with ffmpeg (ADR 0030, CA3 of the ADR = step CA2 of the build).

Phone audio is noisy and quiet. Before it goes to the speech-to-text service it is turned into one
mono 16 kHz channel, low rumble and hiss are reduced and the loudness is levelled; the result is a
small mp3. The ORIGINAL file is never touched: the cleaned copy is stored next to it.

The two small tools (``ffprobe`` for the length, ``ffmpeg`` for the cleaning) run as separate
programs with a time limit, fed through temporary files that are always removed. Nothing a person
typed reaches a command line: the arguments are fixed here, and the file names are our own.
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

# What the speech service gets: mono, 16 kHz, 48 kbit/s mp3 (an hour is about 21 MB).
CLEAN_CONTENT_TYPE = "audio/mpeg"
CLEAN_SUFFIX = ".mp3"
FILTERS = "highpass=f=80,afftdn=nf=-25,loudnorm=I=-16:TP=-1.5:LRA=11"


class AudioUnreadableError(Exception):
    """ffmpeg could not decode the file (broken, cut off or not really audio)."""


class AudioToolMissingError(Exception):
    """ffmpeg / ffprobe is not installed on this machine: a set-up problem, retrying cannot help."""


class Cleaner(Protocol):
    def duration_seconds(self, data: bytes, file_name: str) -> float: ...

    def clean(self, data: bytes, file_name: str) -> bytes: ...


def probe_args(command: str, path: str) -> list[str]:
    return [
        command,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]


def clean_args(command: str, source: str, target: str) -> list[str]:
    return [
        command,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        source,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-af",
        FILTERS,
        "-c:a",
        "libmp3lame",
        "-b:a",
        "48k",
        "-y",
        target,
    ]


def parse_duration(output: str) -> float:
    """The number ffprobe prints. Anything else (empty, "N/A", negative) means unreadable."""
    first = output.strip().splitlines()[0].strip() if output.strip() else ""
    try:
        value = float(first)
    except ValueError:
        raise AudioUnreadableError("no length") from None
    if not (value >= 0) or value != value or value == float("inf"):
        raise AudioUnreadableError("no length")
    return value


def _suffix(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    return suffix if suffix in {".mp3", ".m4a", ".wav", ".ogg", ".webm", ".amr"} else ".bin"


class FfmpegCleaner:
    def __init__(
        self,
        *,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        timeout_seconds: int = 900,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._timeout = timeout_seconds

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(  # noqa: S603 - fixed arguments, our own temporary file names
                args,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except FileNotFoundError:
            raise AudioToolMissingError(args[0]) from None
        except subprocess.TimeoutExpired:
            raise AudioUnreadableError("took too long") from None

    def duration_seconds(self, data: bytes, file_name: str) -> float:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / f"in{_suffix(file_name)}"
            source.write_bytes(data)
            done = self._run(probe_args(self._ffprobe, str(source)))
        if done.returncode != 0:
            raise AudioUnreadableError("probe failed")
        return parse_duration(done.stdout)

    def clean(self, data: bytes, file_name: str) -> bytes:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / f"in{_suffix(file_name)}"
            target = Path(directory) / f"out{CLEAN_SUFFIX}"
            source.write_bytes(data)
            done = self._run(clean_args(self._ffmpeg, str(source), str(target)))
            if done.returncode != 0 or not target.exists() or target.stat().st_size == 0:
                logger.warning("ffmpeg could not clean a recording")
                raise AudioUnreadableError("clean failed")
            return target.read_bytes()
