"""Public interface of the speech provider for other modules (call recordings, ADR 0030)."""

from app.modules.voice.provider import (
    NoSpeechError,
    SpeechProvider,
    SpeechProviderError,
    TimedSegment,
    TimedTranscript,
    build_speech_provider,
)

__all__ = [
    "NoSpeechError",
    "SpeechProvider",
    "SpeechProviderError",
    "TimedSegment",
    "TimedTranscript",
    "build_speech_provider",
]
