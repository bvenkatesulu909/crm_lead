"""The fake speech service (local runs and the browser journeys, ADR 0038): it hears the audio's own
bytes as text, speaks a few fixed bytes, and can never run in production."""

import asyncio

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.voice.provider import (
    FakeSpeechProvider,
    NoSpeechError,
    build_speech_provider,
)
from tests.conftest import UNREACHABLE_DATABASE_URL

BASE: dict[str, object] = {
    "_env_file": None,
    "database_url": UNREACHABLE_DATABASE_URL,
    "oidc_issuer": "https://auth.example.test/realms/crm",
    "files_s3_secure": True,
}


def test_it_hears_the_bytes_as_text() -> None:
    heard = asyncio.run(
        FakeSpeechProvider().transcribe_timed(
            b"I am Ravi, phone 98480 12345", "turn.webm", "audio/webm", "en"
        )
    )
    assert heard.text == "I am Ravi, phone 98480 12345"
    assert heard.engine == "fake:text"


def test_it_hears_telugu_and_hindi_too() -> None:
    for words in ("నమస్కారం", "नमस्ते"):
        heard = asyncio.run(
            FakeSpeechProvider().transcribe_timed(words.encode(), "t.webm", "audio/webm", "te")
        )
        assert heard.text == words


def test_empty_audio_is_no_speech() -> None:
    with pytest.raises(NoSpeechError):
        asyncio.run(FakeSpeechProvider().transcribe_timed(b"  \n", "t.webm", "audio/webm", "en"))


def test_it_speaks_a_few_fixed_bytes() -> None:
    speech = asyncio.run(FakeSpeechProvider().synthesize("Hello"))
    assert speech.audio == b"ID3-fake-audio" and speech.media_type == "audio/mpeg"


def test_it_is_built_when_the_provider_is_fake() -> None:
    settings = Settings(environment="development", voice_provider="fake", **BASE)  # type: ignore[arg-type]
    assert isinstance(build_speech_provider(settings), FakeSpeechProvider)


def test_it_is_not_built_when_voice_is_disabled() -> None:
    settings = Settings(
        environment="development",
        voice_provider="fake",
        voice_enabled=False,
        **BASE,  # type: ignore[arg-type]
    )
    assert build_speech_provider(settings) is None


def test_it_can_never_run_in_production() -> None:
    with pytest.raises(ValidationError, match="speech provider"):
        Settings(environment="production", voice_provider="fake", **BASE)  # type: ignore[arg-type]
