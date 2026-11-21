"""Measure one spoken turn of the voice receptionist on FICTIONAL sentences (ADR 0038, VR1).

A visitor turn is: hear (speech-to-text) -> think (the model) -> speak (text-to-speech). This
script times each part, scores the hearing (word and character error rate, as in the call
trial) and estimates what a 5-minute call would cost. It is a MEASUREMENT only: nothing is
stored, no database is touched, and no limit is chosen by it - the owner sets the limits from
the numbers it prints.

Folder layout (fictional sentences only, never a real visitor):

    samples/q1.hi.txt     the words said, in Hindi / Telugu / English  (hi, te or en)
    samples/q1.hi.m4a     OPTIONAL real recording of someone reading them (mp3, m4a, wav ...)

Without a recording, ``--synthesize`` makes one with the text-to-speech voice. A synthetic voice is
clearer than a real caller on a phone in a noisy room, so its error rates are OPTIMISTIC: the
table says so. A real recording of a person is the fair test (see docs/call-trial-samples.md).

Run in CMD from the backend folder with the virtual environment active:

    python -m scripts.measure_receptionist_voice samples --engine scripted
    set CRM_RUN_LIVE_EVALS=1
    python -m scripts.measure_receptionist_voice samples --engine real --synthesize ^
        --stt-price-per-minute 0.006 --tts-price-per-1k-chars 0.015

``--engine scripted`` is free and only shows the table works. ``--engine real`` spends money
(speech and one short model answer per sample), so it refuses without ``CRM_RUN_LIVE_EVALS=1``.
Prices are YOUR numbers from the provider's price page (any one currency); the script invents
none. The model's own token cost is not included - read it on the AI agents page.
Only names, timings and rates are printed - never a key or a transcript.
"""

import argparse
import asyncio
import os
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from scripts.measure_call_transcription import (
    AUDIO,
    LANGUAGES,
    char_error_rate,
    percent,
    word_error_rate,
)

NAMES = {"hi": "Hindi", "te": "Telugu", "en": "English"}
CALL_SECONDS = 5 * 60  # the limits proposed in ADR 0038: 5 minutes ...
CALL_TURNS = 12  # ... and 12 turns
# Used only to size a turn when no recording length can be read (a short spoken sentence).
ASSUMED_VISITOR_SECONDS = 6.0


@dataclass(frozen=True)
class Item:
    name: str
    language: str
    reference: str
    audio: Path | None


def find_items(folder: Path) -> list[Item]:
    """``name.<language>.txt`` with an optional audio file of the same stem beside it."""
    items: list[Item] = []
    for text in sorted(folder.glob("*.txt")):
        stem, _, language = text.stem.rpartition(".")
        if not stem or language not in LANGUAGES:
            continue
        audio = next(
            (
                p
                for p in sorted(folder.iterdir())
                if p.stem == text.stem and p.suffix.lower() in AUDIO
            ),
            None,
        )
        items.append(Item(stem, language, text.read_text(encoding="utf-8"), audio))
    return items


@dataclass(frozen=True)
class Turn:
    name: str
    language: str
    voice: str  # "recording" or "synthetic"
    wer: float
    cer: float
    hear_s: float
    think_s: float  # until the model's first finished sentence
    speak_s: float  # text-to-speech of that first sentence
    visitor_seconds: float
    reply_chars: int

    @property
    def delay_s(self) -> float:
        """What the visitor waits between stopping to talk and hearing the first sound."""
        return self.hear_s + self.think_s + self.speak_s


def turn_cost(turn: Turn, *, stt_per_minute: Decimal, tts_per_1k_chars: Decimal) -> Decimal:
    """Speech cost of one turn. The model's tokens are not included."""
    return stt_per_minute * Decimal(str(turn.visitor_seconds)) / Decimal(60) + (
        tts_per_1k_chars * Decimal(turn.reply_chars) / Decimal(1000)
    )


def call_cost(per_turn: Decimal, turns: int = CALL_TURNS) -> Decimal:
    """A full call at the proposed limit of ``turns`` turns of the same size."""
    return per_turn * Decimal(turns)


def render(turns: list[Turn], stt_per_minute: Decimal, tts_per_1k_chars: Decimal) -> str:
    lines = [
        f"{'sample':<16}{'lang':<8}{'voice':<10}{'words':>8}{'chars':>8}"
        f"{'hear s':>8}{'think s':>9}{'speak s':>9}{'wait s':>8}"
    ]
    for t in turns:
        lines.append(
            f"{t.name[:15]:<16}{NAMES[t.language]:<8}{t.voice:<10}"
            f"{percent(t.wer):>8}{percent(t.cer):>8}"
            f"{t.hear_s:>8.1f}{t.think_s:>9.1f}{t.speak_s:>9.1f}{t.delay_s:>8.1f}"
        )
    for language in LANGUAGES:
        part = [t for t in turns if t.language == language]
        if part:
            lines.append(
                f"{'average':<16}{NAMES[language]:<8}{'':<10}"
                f"{percent(statistics.mean(t.wer for t in part)):>8}"
                f"{percent(statistics.mean(t.cer for t in part)):>8}"
                f"{statistics.mean(t.hear_s for t in part):>8.1f}"
                f"{statistics.mean(t.think_s for t in part):>9.1f}"
                f"{statistics.mean(t.speak_s for t in part):>9.1f}"
                f"{statistics.mean(t.delay_s for t in part):>8.1f}"
            )
    if turns:
        waits = sorted(t.delay_s for t in turns)
        lines.append(
            f"Wait before the first sound: median {statistics.median(waits):.1f} s, "
            f"slowest {waits[-1]:.1f} s ({len(turns)} turns)"
        )
    if any(t.voice == "synthetic" for t in turns):
        lines.append(
            "NOTE: 'synthetic' means the visitor's voice was made by text-to-speech. That is "
            "clearer than a real caller, so the error rates are optimistic."
        )
    if turns and (stt_per_minute or tts_per_1k_chars):
        mean_turn = statistics.mean(
            turn_cost(t, stt_per_minute=stt_per_minute, tts_per_1k_chars=tts_per_1k_chars)
            for t in turns
        )
        lines.append(
            f"Speech cost (your prices): {mean_turn:.4f} per turn, about "
            f"{call_cost(mean_turn):.3f} for a {CALL_TURNS}-turn call "
            f"(limit {CALL_SECONDS // 60} min). Model tokens are not included."
        )
    else:
        lines.append("No prices given: pass --stt-price-per-minute and --tts-price-per-1k-chars.")
    return "\n".join(lines)


_SYSTEM = (
    "You are an automated assistant of a real estate company speaking to a visitor by voice. "
    "Answer in the visitor's language and script, in at most two short sentences. "
    "Do not invent prices or availability."
)


def _think(model: Any, said: str, language: str) -> tuple[float, str]:
    """Seconds until the model's first finished sentence, and that sentence."""
    from app.modules.assistant.llm import stream_reply
    from app.modules.assistant.sentences import SentenceStream

    started = time.perf_counter()
    sentences = SentenceStream()
    for piece in stream_reply(
        model,
        system=f"{_SYSTEM} Language code: {language}.",
        messages=[{"role": "user", "content": said}],
        tools=[],
    ):
        done = sentences.feed(piece)
        if done:
            return time.perf_counter() - started, done[0]
    rest = sentences.flush()
    return time.perf_counter() - started, (rest[0] if rest else "")


class _ScriptedModel:
    available = True

    def reply(self, **_: object) -> Any:
        from app.modules.assistant.llm import ModelReply

        return ModelReply("Thank you. Our team will help you. Please share your number.")


class _ScriptedSpeech:
    """Stands in for the speech service without a key: 'hears' the reference, 'speaks' bytes."""

    def __init__(self) -> None:
        self.heard = ""

    async def transcribe_timed(
        self, data: bytes, filename: str, content_type: str, language: str
    ) -> Any:
        from app.modules.voice import api as voice_api

        return voice_api.TimedTranscript(text=self.heard, segments=[], engine="fake:scripted")

    async def synthesize(self, text: str) -> Any:
        from app.modules.voice.provider import SynthesizedSpeech

        return SynthesizedSpeech(audio=b"x")


def measure(
    item: Item,
    speech: Any,
    model: Any,
    *,
    synthesize: bool,
    seconds_of: Callable[[bytes, str], float],
    run: Callable[[Any], Any],
) -> Turn:
    if isinstance(speech, _ScriptedSpeech):
        speech.heard = item.reference
    if item.audio is not None:
        data, name, voice = item.audio.read_bytes(), item.audio.name, "recording"
    elif synthesize:
        data = run(speech.synthesize(item.reference)).audio
        name, voice = "synthetic.mp3", "synthetic"
    else:
        raise ValueError(f"{item.name}: no recording; add one or pass --synthesize")

    started = time.perf_counter()
    result = run(speech.transcribe_timed(data, name, "application/octet-stream", item.language))
    hear = time.perf_counter() - started
    think, first = _think(model, result.text, item.language)
    started = time.perf_counter()
    run(speech.synthesize(first or "ok"))
    speak = time.perf_counter() - started
    try:
        visitor_seconds = float(seconds_of(data, name))
    except Exception:  # noqa: BLE001 - no ffprobe: use the size of a short spoken sentence
        visitor_seconds = ASSUMED_VISITOR_SECONDS
    return Turn(
        item.name,
        item.language,
        voice,
        word_error_rate(item.reference, result.text),
        char_error_rate(item.reference, result.text),
        hear,
        think,
        speak,
        visitor_seconds,
        len(first),
    )


def _assumed_seconds(data: bytes, name: str) -> float:
    return ASSUMED_VISITOR_SECONDS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--engine", choices=("scripted", "real"), default="scripted")
    parser.add_argument("--synthesize", action="store_true")
    parser.add_argument("--stt-price-per-minute", type=Decimal, default=Decimal(0))
    parser.add_argument("--tts-price-per-1k-chars", type=Decimal, default=Decimal(0))
    args = parser.parse_args(argv)

    if not args.folder.is_dir():
        print(f"No such folder: {args.folder}")
        return 2
    items = find_items(args.folder)
    if not items:
        print("No samples found. Name them like q1.hi.txt (hi, te or en).")
        return 2

    speech: Any
    model: Any
    seconds_of: Callable[[bytes, str], float]
    if args.engine == "real":
        if os.environ.get("CRM_RUN_LIVE_EVALS") != "1":
            print("Refusing to spend money: set CRM_RUN_LIVE_EVALS=1 to run the real engine.")
            return 2
        from app.core.config import get_settings
        from app.modules.assistant.llm import build_chat_model
        from app.modules.calls import audio
        from app.modules.voice import api as voice_api

        settings = get_settings()
        if settings.ai_provider == "fake":
            print("CRM_AI_PROVIDER is 'fake': there is no real model to measure.")
            return 2
        speech = voice_api.build_speech_provider(settings, stt_model=settings.calls_stt_model)
        if speech is None:
            print("No speech service is set up (CRM_VOICE_* in backend\\.env).")
            return 2
        model = build_chat_model(settings)
        seconds_of = audio.FfmpegCleaner(
            ffmpeg=settings.calls_ffmpeg_command, ffprobe=settings.calls_ffprobe_command
        ).duration_seconds
        print(f"Speech: {settings.voice_provider} | model: {settings.ai_provider}")
    else:
        speech, model, seconds_of = _ScriptedSpeech(), _ScriptedModel(), _assumed_seconds
        print("Scripted engines (no cost, the numbers mean nothing). Add --engine real.")

    # ONE event loop for the whole run: a provider keeps its HTTP client between calls, and a
    # client made in one loop cannot be used in another ("event loop is closed").
    loop = asyncio.new_event_loop()
    turns: list[Turn] = []
    for item in items:
        try:
            turns.append(
                measure(
                    item,
                    speech,
                    model,
                    synthesize=args.synthesize,
                    seconds_of=seconds_of,
                    run=loop.run_until_complete,
                )
            )
        except Exception as exc:  # noqa: BLE001 - report which sample failed, go on
            # Only our own sample problem is spelled out; a provider error shows its type only,
            # because its text could carry request details.
            detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            print(f"  {item.name}.{item.language} failed: {detail}")
    loop.close()
    if not turns:
        return 1
    print(render(turns, args.stt_price_per_minute, args.tts_price_per_1k_chars))
    return 0


if __name__ == "__main__":
    sys.exit(main())
