"""Server-side speech provider abstraction (STT/TTS)."""

import asyncio
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.modules.voice.provider import (
    ElevenLabsSpeechProvider,
    OpenAISpeechProvider,
    SpeechProviderError,
    build_speech_provider,
)


def _provider(handler) -> OpenAISpeechProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAISpeechProvider(
        api_key="test-key",
        base_url="https://speech.test/v1",
        stt_model="stt",
        tts_model="tts",
        tts_voice="alloy",
        client=client,
    )


def test_transcribe_calls_the_vendor_and_returns_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"text": "  Where is my order?  "})

    result = asyncio.run(_provider(handler).transcribe(b"audio", "a.webm", "audio/webm"))
    assert result == "Where is my order?"


def test_synthesize_returns_audio_bytes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/speech"
        return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"})

    speech = asyncio.run(_provider(handler).synthesize("Your order ships Friday."))
    assert speech.audio == b"ID3audio"
    assert speech.media_type == "audio/mpeg"


def test_vendor_failure_becomes_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(SpeechProviderError):
        asyncio.run(_provider(handler).transcribe(b"audio", "a.webm", "audio/webm"))


def test_provider_is_absent_without_a_key():
    settings = cast(
        Settings,
        SimpleNamespace(voice_enabled=True, voice_provider="openai", voice_api_key=None),
    )
    assert build_speech_provider(settings) is None
    settings = cast(
        Settings,
        SimpleNamespace(
            voice_enabled=True,
            voice_provider="openai",
            voice_api_key=SecretStr("key"),
            voice_base_url="https://speech.test/v1",
            voice_stt_model="stt",
            voice_tts_model="tts",
            voice_tts_voice="alloy",
        ),
    )
    assert build_speech_provider(settings) is not None


def test_elevenlabs_transcribe_and_synthesize():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["xi-api-key"] == "el-key"
        if request.url.path == "/v1/speech-to-text":
            return httpx.Response(200, json={"text": "hello"})
        assert request.url.path == "/v1/text-to-speech/voice123"
        return httpx.Response(200, content=b"ID3el", headers={"content-type": "audio/mpeg"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ElevenLabsSpeechProvider(
        api_key="el-key",
        base_url="https://api.elevenlabs.io/v1",
        stt_model="scribe_v1",
        tts_model="eleven_multilingual_v2",
        tts_voice="voice123",
        client=client,
    )
    assert asyncio.run(provider.transcribe(b"audio", "a.webm", "audio/webm")) == "hello"
    assert asyncio.run(provider.synthesize("hi")).audio == b"ID3el"


def test_build_selects_elevenlabs():
    settings = cast(
        Settings,
        SimpleNamespace(
            voice_enabled=True,
            voice_provider="elevenlabs",
            voice_api_key=SecretStr("el-key"),
            voice_base_url="https://api.elevenlabs.io/v1",
            voice_stt_model="scribe_v1",
            voice_tts_model="eleven_multilingual_v2",
            voice_tts_voice="voice123",
        ),
    )
    assert isinstance(build_speech_provider(settings), ElevenLabsSpeechProvider)
