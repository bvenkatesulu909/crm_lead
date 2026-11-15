"""Measure how well call transcription does on FICTIONAL sample calls (ADR 0030, CA3).

Put short test recordings in one folder, each with the words that were really said:

    samples/visit1.hi.mp3      samples/visit1.hi.txt      (Hindi, or Hindi mixed with English)
    samples/visit2.te.m4a      samples/visit2.te.txt      (Telugu, or Telugu mixed with English)
    samples/visit3.en.wav      samples/visit3.en.txt      (English)

The middle part of the name is the language code the rep would choose (hi, te or en). Use made-up
conversations only - never a real buyer's call.

Run in CMD from the backend folder with the virtual environment active:

    python -m scripts.measure_call_transcription samples --engine scripted
    set CRM_RUN_LIVE_EVALS=1
    python -m scripts.measure_call_transcription samples --engine real --also-original

``--engine scripted`` costs nothing and only shows that the table works (it "hears" a fixed
sentence). ``--engine real`` needs ffmpeg installed and the speech service of backend\\.env, and it
spends a little money per minute of audio, so it refuses to run without ``CRM_RUN_LIVE_EVALS=1``.
``--also-original`` also sends the UNCLEANED audio, which shows whether the cleaning helps.

Printed per sample: language, the word error rate and the character error rate (0 % = perfect; the
character rate is the fairer one for Hindi and Telugu, whose word boundaries are fuzzy), and the
seconds the transcription took. Only numbers and sample names are printed - never a key or a
transcript. The error rates ignore capitals, punctuation and extra spaces.
"""

import argparse
import asyncio
import os
import statistics
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

LANGUAGES = ("hi", "te", "en")
AUDIO = (".mp3", ".m4a", ".wav", ".ogg", ".webm", ".amr")


def normalize(text: str) -> str:
    """Lower case, one form of each character, no punctuation, single spaces.

    Letters, digits and COMBINING MARKS are kept: in Hindi and Telugu the vowel signs and the
    virama are marks, and dropping them would change the words. Everything else (punctuation,
    symbols, the Hindi danda) becomes a space."""
    text = unicodedata.normalize("NFC", text).casefold()
    kept = (
        c if unicodedata.category(c)[0] in {"L", "N", "M"} or c.isspace() else " " for c in text
    )
    return " ".join("".join(kept).split())


def _distance(a: list[str], b: list[str]) -> int:
    """The smallest number of insertions, deletions and replacements that turn ``a`` into ``b``."""
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        current = [i]
        for j, y in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def word_error_rate(reference: str, heard: str) -> float:
    """Wrong words divided by the words that were said. 0.0 is perfect; it can exceed 1.0."""
    said = normalize(reference).split()
    got = normalize(heard).split()
    if not said:
        return 0.0 if not got else 1.0
    return _distance(said, got) / len(said)


def char_error_rate(reference: str, heard: str) -> float:
    said = list(normalize(reference).replace(" ", ""))
    got = list(normalize(heard).replace(" ", ""))
    if not said:
        return 0.0 if not got else 1.0
    return _distance(said, got) / len(said)


@dataclass(frozen=True)
class Sample:
    name: str
    language: str
    audio: Path
    reference: Path


def find_samples(folder: Path) -> list[Sample]:
    """``name.<language>.<audio extension>`` with a ``name.<language>.txt`` beside it."""
    found: list[Sample] = []
    for audio in sorted(folder.iterdir()):
        if audio.suffix.lower() not in AUDIO:
            continue
        stem, _, language = audio.stem.rpartition(".")
        if not stem or language not in LANGUAGES:
            continue
        reference = audio.with_suffix(".txt")
        if reference.is_file():
            found.append(Sample(stem, language, audio, reference))
    return found


@dataclass(frozen=True)
class Row:
    name: str
    language: str
    variant: str  # "cleaned" or "original"
    wer: float
    cer: float
    seconds: float


def percent(value: float) -> str:
    return f"{value * 100:5.1f} %"


def render(rows: list[Row]) -> str:
    lines = [f"{'sample':<22}{'lang':<6}{'audio':<10}{'words':>9}{'chars':>9}{'seconds':>9}"]
    for r in rows:
        lines.append(
            f"{r.name[:21]:<22}{r.language:<6}{r.variant:<10}"
            f"{percent(r.wer):>9}{percent(r.cer):>9}{r.seconds:>9.1f}"
        )
    for variant in sorted({r.variant for r in rows}):
        for language in LANGUAGES:
            part = [r for r in rows if r.variant == variant and r.language == language]
            if part:
                lines.append(
                    f"{'average':<22}{language:<6}{variant:<10}"
                    f"{percent(statistics.mean(r.wer for r in part)):>9}"
                    f"{percent(statistics.mean(r.cer for r in part)):>9}"
                    f"{statistics.mean(r.seconds for r in part):>9.1f}"
                )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--engine", choices=("scripted", "real"), default="scripted")
    parser.add_argument("--also-original", action="store_true")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"No such folder: {args.folder}")
        return 2
    samples = find_samples(args.folder)
    if not samples:
        print("No samples found. Name them like visit1.hi.mp3 with visit1.hi.txt beside them.")
        return 2

    from app.core.config import get_settings
    from app.modules.calls import audio, fakes
    from app.modules.voice import api as voice_api

    settings = get_settings()
    if args.engine == "real":
        if os.environ.get("CRM_RUN_LIVE_EVALS") != "1":
            print("Refusing to spend money: set CRM_RUN_LIVE_EVALS=1 to run the real engine.")
            return 2
        provider = voice_api.build_speech_provider(settings, stt_model=settings.calls_stt_model)
        if provider is None:
            print("No speech service is set up (CRM_VOICE_* in backend\\.env).")
            return 2
        cleaner: audio.Cleaner = audio.FfmpegCleaner(
            ffmpeg=settings.calls_ffmpeg_command, ffprobe=settings.calls_ffprobe_command
        )
    else:
        provider = fakes.ScriptedSpeech()  # type: ignore[assignment]
        cleaner = fakes.ScriptedCleaner()

    rows: list[Row] = []
    for sample in samples:
        reference = sample.reference.read_text(encoding="utf-8")
        original = sample.audio.read_bytes()
        variants = [("cleaned", None)] + ([("original", original)] if args.also_original else [])
        for variant, raw in variants:
            data = raw if raw is not None else cleaner.clean(original, sample.audio.name)
            started = time.perf_counter()
            result = asyncio.run(
                provider.transcribe_timed(  # type: ignore[union-attr]
                    data,
                    sample.audio.name if raw is not None else f"call{audio.CLEAN_SUFFIX}",
                    "application/octet-stream" if raw is not None else audio.CLEAN_CONTENT_TYPE,
                    sample.language,
                )
            )
            rows.append(
                Row(
                    sample.name,
                    sample.language,
                    variant,
                    word_error_rate(reference, result.text),
                    char_error_rate(reference, result.text),
                    time.perf_counter() - started,
                )
            )
    print(render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
