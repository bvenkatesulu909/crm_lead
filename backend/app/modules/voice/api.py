"""Public interface of the speech provider for other modules (call recordings, ADR 0030)."""

from app.modules.voice.provider import (
    NoSpeechError,
    SpeechProvider,
    SpeechProviderError,
    TimedSegment,
    TimedTranscript,
    build_speech_provider,
)
from app.modules.voice.service import seconds_heard, seconds_spoken

__all__ = [
    "NoSpeechError",
    "SpeechProvider",
    "SpeechProviderError",
    "TimedSegment",
    "TimedTranscript",
    "build_speech_provider",
    "seconds_heard",
    "seconds_spoken",
]
