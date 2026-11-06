"""Measure how long a spoken answer takes to START and to FINISH (ADR 0023, step VM5).

For a voice conversation what matters is the time until the first sentence can be spoken. This
asks the configured model a few short questions the way the voice mode does (streamed, with the
voice instructions) and prints, per run: seconds to the first finished sentence, seconds to the
whole answer, and the number of sentences.

Run in CMD from the backend folder with the virtual environment active:

    python -m scripts.measure_voice_latency                 (the scripted model: no cost)
    python -m scripts.measure_voice_latency --live --runs 3 (the model in backend\\.env)

``--live`` calls the real model: with a paid provider that costs a fraction of a cent per run, so
it is never the default. Only timings are printed - never the key. It measures the MODEL part (the
largest part of the delay); speech and the network to the browser come on top, and a question that
needs tools adds one more model call per tool round.
"""

import argparse
import statistics
import sys
import time

from app.core.config import Settings
from app.modules.assistant.llm import ModelReply, build_chat_model, stream_reply
from app.modules.assistant.sentences import SentenceStream
from app.modules.assistant.staff_service import SYSTEM, VOICE

QUESTIONS = (
    "In one or two sentences: what do I tell a buyer who asks if a flat is ready to move into?",
    "Briefly, how should I follow up with a lead who has not answered for a week?",
    "Give me one short tip for my first call with a new lead.",
)


class _ScriptedVoice:
    """Stands in for a model without a key: answers at once, in pieces."""

    available = True

    def reply(self, **_: object) -> ModelReply:
        return ModelReply("Sure. Here is a short answer. That is all.")


def measure(model: object, question: str) -> tuple[float, float, int]:
    started = time.perf_counter()
    first: float | None = None
    sentences = SentenceStream()
    count = 0
    pieces = stream_reply(
        model,  # type: ignore[arg-type]
        system=SYSTEM + "\n\n" + VOICE,
        messages=[{"role": "user", "content": question}],
        tools=[],
    )
    while True:
        try:
            piece = next(pieces)
        except StopIteration:
            break
        for _ in sentences.feed(piece):
            count += 1
            first = first if first is not None else time.perf_counter() - started
    count += len(sentences.flush())
    total = time.perf_counter() - started
    return (first if first is not None else total), total, count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="call the model in backend\\.env")
    parser.add_argument("--runs", type=int, default=1, help="how many times each question")
    args = parser.parse_args(argv)

    settings = Settings()
    if args.live:
        if settings.ai_provider == "fake":
            print("CRM_AI_PROVIDER is 'fake': there is no real model to measure.")
            return 1
        model: object = build_chat_model(settings)
        name = (
            settings.deepseek_model
            if settings.ai_provider == "deepseek"
            else settings.assistant_model
        )
        print(f"Provider: {settings.ai_provider} | model: {name}")
    else:
        model = _ScriptedVoice()
        print("Scripted model (no cost). Add --live to measure the real model.")

    firsts: list[float] = []
    totals: list[float] = []
    for question in QUESTIONS:
        for run in range(max(1, args.runs)):
            try:
                first, total, count = measure(model, question)
            except Exception as exc:  # noqa: BLE001 - report and go on
                print(f"  failed: {type(exc).__name__}")
                continue
            firsts.append(first)
            totals.append(total)
            print(
                f"  q{QUESTIONS.index(question) + 1} run {run + 1}: first sentence "
                f"{first:5.1f} s | whole answer {total:5.1f} s | {count} sentences"
            )
    if not firsts:
        return 1
    print(
        f"Median: first sentence {statistics.median(firsts):.1f} s, "
        f"whole answer {statistics.median(totals):.1f} s ({len(firsts)} answers)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
