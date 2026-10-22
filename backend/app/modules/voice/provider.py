"""Speech provider abstraction (STT/TTS) for production voice (ADR 0012).

OpenAI-compatible audio API by default (Whisper transcription + speech synthesis); another
vendor can be added behind the same SpeechProvider protocol.
"""

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class SpeechProviderError(Exception):
    """The speech vendor failed or is not configured; the API maps this to 503."""


@dataclass(frozen=True)
class SynthesizedSpeech:
    audio: bytes
    media_type: str = "audio/mpeg"


class SpeechProvider(Protocol):
    available: bool

    async def transcribe(self, data: bytes, filename: str, content_type: str) -> str: ...

    async def synthesize(self, text: str) -> SynthesizedSpeech: ...


class OpenAISpeechProvider:
    """OpenAI-compatible /audio/transcriptions and /audio/speech."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        stt_model: str,
        tts_model: str,
        tts_voice: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.available = True
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._stt_model = stt_model
        self._tts_model = tts_model
        self._tts_voice = tts_voice
        self._client = client
        self._owned = client is None

    def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def transcribe(self, data: bytes, filename: str, content_type: str) -> str:
        try:
            response = await self._client_or_create().post(
                f"{self._base_url}/audio/transcriptions",
                headers=self._headers,
                data={"model": self._stt_model},
                files={"file": (filename, data, content_type or "application/octet-stream")},
            )
            response.raise_for_status()
            text = str(response.json().get("text", "")).strip()
        except Exception as exc:  # noqa: BLE001 - vendor errors must become a clean 503
            logger.warning("speech transcription failed", extra={"error": type(exc).__name__})
            raise SpeechProviderError("Speech transcription is unavailable.") from exc
        if not text:
            raise SpeechProviderError("No speech was detected.")
        return text

    async def synthesize(self, text: str) -> SynthesizedSpeech:
        try:
            response = await self._client_or_create().post(
                f"{self._base_url}/audio/speech",
                headers=self._headers,
                json={
                    "model": self._tts_model,
                    "voice": self._tts_voice,
                    "input": text,
                    "response_format": "mp3",
                },
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("speech synthesis failed", extra={"error": type(exc).__name__})
            raise SpeechProviderError("Speech synthesis is unavailable.") from exc
        return SynthesizedSpeech(audio=response.content, media_type="audio/mpeg")


class ElevenLabsSpeechProvider:
    """ElevenLabs Scribe transcription + TTS.

    Docs: /v1/speech-to-text (multipart) and /v1/text-to-speech/{voice_id}. The API key travels
    only in the server-side xi-api-key header.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        stt_model: str,
        tts_model: str,
        tts_voice: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.available = True
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._stt_model = stt_model
        self._tts_model = tts_model
        self._tts_voice = tts_voice
        self._client = client

    def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    @property
    def _headers(self) -> dict[str, str]:
        return {"xi-api-key": self._api_key}

    async def transcribe(self, data: bytes, filename: str, content_type: str) -> str:
        try:
            response = await self._client_or_create().post(
                f"{self._base_url}/speech-to-text",
                headers=self._headers,
                data={"model_id": self._stt_model},
                files={"file": (filename, data, content_type or "application/octet-stream")},
            )
            response.raise_for_status()
            text = str(response.json().get("text", "")).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("elevenlabs transcription failed", extra={"error": type(exc).__name__})
            raise SpeechProviderError("Speech transcription is unavailable.") from exc
        if not text:
            raise SpeechProviderError("No speech was detected.")
        return text

    async def synthesize(self, text: str) -> SynthesizedSpeech:
        try:
            response = await self._client_or_create().post(
                f"{self._base_url}/text-to-speech/{self._tts_voice}",
                headers={**self._headers, "Accept": "audio/mpeg"},
                json={"text": text, "model_id": self._tts_model},
                params={"output_format": "mp3_44100_128"},
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("elevenlabs synthesis failed", extra={"error": type(exc).__name__})
            raise SpeechProviderError("Speech synthesis is unavailable.") from exc
        return SynthesizedSpeech(audio=response.content, media_type="audio/mpeg")


class LocalSpeechProvider:
    """Free local speech: faster-whisper STT + Piper CLI TTS. Models load lazily."""

    def __init__(self, *, stt_model: str, tts_model_path: str, piper_command: str) -> None:
        self.available = True
        self._stt_model_name = stt_model
        self._tts_model_path = tts_model_path
        self._piper_command = piper_command
        self._whisper: Any = None

    def _model(self) -> Any:
        if self._whisper is None:
            import importlib

            WhisperModel = importlib.import_module("faster_whisper").WhisperModel

            self._whisper = WhisperModel(self._stt_model_name, device="cpu", compute_type="int8")
        return self._whisper

    async def transcribe(self, data: bytes, filename: str, content_type: str) -> str:
        import asyncio
        import tempfile
        from pathlib import Path

        def run() -> str:
            with tempfile.NamedTemporaryFile(
                suffix=Path(filename).suffix or ".webm", delete=False
            ) as handle:
                handle.write(data)
                path = Path(handle.name)
            try:
                segments, _ = self._model().transcribe(str(path), language="en")
                return " ".join(segment.text.strip() for segment in segments).strip()
            finally:
                path.unlink(missing_ok=True)

        try:
            text = await asyncio.to_thread(run)
        except Exception as exc:  # noqa: BLE001
            logger.warning("local transcription failed", extra={"error": type(exc).__name__})
            raise SpeechProviderError("Local speech transcription is unavailable.") from exc
        if not text:
            raise SpeechProviderError("No speech was detected.")
        return text

    async def synthesize(self, text: str) -> SynthesizedSpeech:
        import asyncio
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        if not self._tts_model_path:
            raise SpeechProviderError("No local Piper voice is configured.")

        def run() -> bytes:
            if shutil.which(self._piper_command) is None:
                raise RuntimeError("piper executable not found")
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "speech.wav"
                subprocess.run(  # noqa: S603 - configured local executable
                    [
                        self._piper_command,
                        "--model",
                        self._tts_model_path,
                        "--output_file",
                        str(output),
                    ],
                    input=text.encode("utf-8"),
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                return output.read_bytes()

        try:
            audio = await asyncio.to_thread(run)
        except Exception as exc:  # noqa: BLE001
            logger.warning("local synthesis failed", extra={"error": type(exc).__name__})
            raise SpeechProviderError("Local speech synthesis is unavailable.") from exc
        return SynthesizedSpeech(audio=audio, media_type="audio/wav")


def build_speech_provider(settings: Settings) -> SpeechProvider | None:
    if not settings.voice_enabled:
        return None
    if settings.voice_provider == "local":
        return LocalSpeechProvider(
            stt_model=settings.voice_stt_model,
            tts_model_path=settings.voice_tts_model,
            piper_command=settings.voice_piper_command,
        )
    if settings.voice_api_key is None:
        return None
    provider = (
        ElevenLabsSpeechProvider
        if settings.voice_provider == "elevenlabs"
        else OpenAISpeechProvider
    )
    return provider(
        api_key=settings.voice_api_key.get_secret_value(),
        base_url=settings.voice_base_url,
        stt_model=settings.voice_stt_model,
        tts_model=settings.voice_tts_model,
        tts_voice=settings.voice_tts_voice,
    )
