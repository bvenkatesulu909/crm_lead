"""Authenticated server-side STT/TTS gateway (/api/v1/voice)."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile

from app.core.auth.principal import Principal
from app.core.errors import DomainError, problem_responses
from app.modules.assistant.guardrails import sanitise_output
from app.modules.identity.dependencies import get_principal
from app.modules.voice.provider import SpeechProvider, SpeechProviderError
from app.modules.voice.schemas import SpeechRequest, TranscriptionRead

Audio = Annotated[UploadFile, File()]
Me = Annotated[Principal, Depends(get_principal)]

ALLOWED_AUDIO = {
    "audio/webm",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/ogg",
    "application/octet-stream",
}

router = APIRouter(prefix="/voice", tags=["voice"], responses=problem_responses(401, 403))


class VoiceUnavailableError(DomainError):
    status_code = 503
    code = "voice_unavailable"


def _provider(request: Request) -> SpeechProvider:
    provider: SpeechProvider | None = request.app.state.speech_provider
    if provider is None or not provider.available:
        raise VoiceUnavailableError("The voice service is not configured.")
    return provider


def _require_person(principal: Principal) -> None:
    if principal.user_type not in ("staff", "customer"):
        raise VoiceUnavailableError("The voice service is for staff and customers.")


@router.post("/transcribe", summary="Transcribe recorded speech to text")
async def transcribe(
    request: Request,
    principal: Me,
    file: Audio,
) -> TranscriptionRead:
    _require_person(principal)
    provider = _provider(request)
    settings = request.app.state.settings
    if file.content_type not in ALLOWED_AUDIO:
        raise VoiceUnavailableError("Unsupported audio format.")
    data = await file.read(settings.voice_max_upload_bytes + 1)
    if len(data) > settings.voice_max_upload_bytes:
        raise VoiceUnavailableError("The recording is too long.")
    if not data:
        raise VoiceUnavailableError("The recording is empty.")
    try:
        text = await provider.transcribe(
            data, file.filename or "audio.webm", file.content_type or ""
        )
    except SpeechProviderError as exc:
        raise VoiceUnavailableError(str(exc)) from exc
    return TranscriptionRead(text=text)


@router.post(
    "/speak",
    summary="Synthesize an answer as speech",
    response_class=Response,
    responses={200: {"content": {"audio/mpeg": {}}}},
)
async def speak(request: Request, principal: Me, body: SpeechRequest) -> Response:
    _require_person(principal)
    provider = _provider(request)
    text = sanitise_output(body.text)
    try:
        speech = await provider.synthesize(text)
    except SpeechProviderError as exc:
        raise VoiceUnavailableError(str(exc)) from exc
    return Response(
        content=speech.audio,
        media_type=speech.media_type,
        headers={"Cache-Control": "no-store"},
    )
