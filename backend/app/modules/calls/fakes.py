"""A scripted cleaner and speech service for tests and local demos (``CRM_CALLS_ENGINE=fake``).

Nothing is cleaned and no vendor is called: the audio is passed through, its length is guessed from
its size, and the transcript is a fixed fictional sentence in the language the rep chose. Refused in
production (see ``Settings``): a transcript that did not come from the recording must never be shown
to a rep as if it had.
"""

from app.modules.voice import api as voice_api

TRANSCRIPTS: dict[str, tuple[str, list[tuple[float, float, str]]]] = {
    "hi": (
        "नमस्ते, मुझे हैदराबाद में तीन बेडरूम का फ्लैट चाहिए। बजट एक करोड़ बीस लाख है।",
        [
            (0.0, 3.0, "नमस्ते, मुझे हैदराबाद में तीन बेडरूम का फ्लैट चाहिए।"),
            (3.0, 6.5, "बजट एक करोड़ बीस लाख है।"),
        ],
    ),
    "te": (
        "నమస్కారం, నాకు కోకాపేటలో ఫ్లాట్ కావాలి. బడ్జెట్ ఒక కోటి ఇరవై లక్షలు.",
        [
            (0.0, 3.0, "నమస్కారం, నాకు కోకాపేటలో ఫ్లాట్ కావాలి."),
            (3.0, 6.5, "బడ్జెట్ ఒక కోటి ఇరవై లక్షలు."),
        ],
    ),
    "en": (
        "Hello, I am looking for a three bedroom flat in Kokapet. "
        "My budget is one point two crore.",
        [
            (0.0, 3.0, "Hello, I am looking for a three bedroom flat in Kokapet."),
            (3.0, 6.5, "My budget is one point two crore."),
        ],
    ),
}


class ScriptedCleaner:
    def duration_seconds(self, data: bytes, file_name: str) -> float:
        return float(max(1, len(data) // 1000))

    def clean(self, data: bytes, file_name: str) -> bytes:
        return data


class ScriptedSpeech:
    async def transcribe_timed(
        self, data: bytes, filename: str, content_type: str, language: str
    ) -> voice_api.TimedTranscript:
        text, segments = TRANSCRIPTS.get(language, TRANSCRIPTS["en"])
        return voice_api.TimedTranscript(
            text=text,
            segments=[voice_api.TimedSegment(a, b, t) for a, b, t in segments],
            engine="fake:scripted",
        )
