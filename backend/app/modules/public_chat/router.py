"""POST /api/v1/public/chat - the public website chat (ADR 0013).

No user login: only our Next.js server may call it, proven by the X-Public-Chat-Key header
(a long shared secret). Without it - or with the feature switched off - the answer is 404, as
if the endpoint didn't exist. The visitor's address arrives in X-Visitor-Ip from that server
and is trusted only together with the key. Thin layer: check the key, call the service,
commit once.
"""

import base64
import hmac
import ipaddress
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.identity.api import require_any_permission
from app.modules.public_chat import service
from app.modules.public_chat.schemas import (
    PublicChatReply,
    PublicChatRequest,
    PublicChatTranscript,
    PublicVoiceReply,
)
from app.modules.voice import api as voice_api

router = APIRouter(prefix="/public", tags=["public chat"])
# Staff side: signed-in users read a lead's website conversation (never visitors).
staff_router = APIRouter(prefix="/public-chat", tags=["public chat"])
Db = Annotated[Session, Depends(get_db_session)]
LeadReader = Annotated[
    Principal,
    Depends(require_any_permission(Permission.LEAD_READ_ALL, Permission.LEAD_READ_OWN)),
]


def require_web_server(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    key = settings.public_chat_server_key
    sent = request.headers.get("X-Public-Chat-Key", "")
    # compare_digest: the time taken doesn't reveal how much of the key was right.
    if (
        not settings.public_chat_enabled
        or key is None
        or not hmac.compare_digest(sent.encode(), key.get_secret_value().encode())
    ):
        raise service.PublicChatNotFoundError()
    return settings


def visitor_ip(request: Request) -> str:
    raw = request.headers.get("X-Visitor-Ip", "").strip()
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return "unknown"  # still limited, together with everyone else without an address


@router.post(
    "/chat",
    summary="A visitor's message to the website chat (only for the CRM's web server)",
    responses=problem_responses(404, 422, 429, 503),
)
def public_chat(
    data: PublicChatRequest,
    request: Request,
    session: Db,
    settings: Annotated[Settings, Depends(require_web_server)],
) -> PublicChatReply:
    reply = service.handle_message(
        session,
        settings,
        request.app.state.public_chat_model,
        data,
        visitor_ip=visitor_ip(request),
    )
    session.commit()
    return reply


ALLOWED_AUDIO = {
    "audio/webm",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/ogg",
    "application/octet-stream",
}


@router.post(
    "/voice/turn",
    summary="One spoken turn of the voice receptionist (only for the CRM's web server)",
    responses=problem_responses(404, 422, 429, 503),
)
async def public_voice_turn(
    request: Request,
    session: Db,
    settings: Annotated[Settings, Depends(require_web_server)],
    audio: Annotated[UploadFile, File()],
    language: Annotated[Literal["en", "hi", "te"], Form()] = "en",
    token: Annotated[str | None, Form(pattern=r"^[A-Za-z0-9_-]{40,100}$")] = None,
    # The version of the notice the visitor read before pressing Start. Required on the first
    # spoken turn; the server compares it with the version it currently requires.
    consent_version: Annotated[int | None, Form(ge=1, le=10_000)] = None,
    website: Annotated[str, Form(max_length=500)] = "",
) -> PublicVoiceReply:
    """Audio in, text and speech out. Order matters: everything that can refuse the visitor runs
    before the audio is sent to the speech service, so a refused visitor costs nothing."""
    provider = request.app.state.speech_provider
    if provider is None or not provider.available:
        raise service.ReceptionistUnavailableError()
    ip = visitor_ip(request)
    service.voice_precheck(
        session, settings, token=token, consent_version=consent_version, visitor_ip=ip
    )
    if audio.content_type not in ALLOWED_AUDIO:
        raise service.MessageRefusedError("This kind of audio is not supported.")
    data = await audio.read(settings.receptionist_max_audio_bytes + 1)
    if not data or len(data) > settings.receptionist_max_audio_bytes:
        raise service.MessageRefusedError("The recording is empty or too long.")
    heard_seconds = voice_api.seconds_heard(len(data))
    try:
        transcript = await provider.transcribe_timed(
            data, audio.filename or "turn.webm", audio.content_type or "", language
        )
        heard = transcript.text.strip()
    except voice_api.NoSpeechError:
        service.count_refused_turn(session, settings, heard_seconds)
        session.commit()
        raise service.HeardNothingError() from None
    except voice_api.SpeechProviderError:
        raise service.ReceptionistUnavailableError() from None
    if not heard:
        service.count_refused_turn(session, settings, heard_seconds)
        session.commit()
        raise service.HeardNothingError()
    try:
        turn = service.handle_voice_message(
            session,
            settings,
            request.app.state.public_chat_model,
            heard=heard,
            token=token,
            language=language,
            website=website,
            consent_version=consent_version,
            visitor_ip=ip,
            heard_seconds=heard_seconds,
            voice_tools=service.VoiceTools(request.app.state.embedder, request.app.state.reranker),
        )
    except service.MessageRefusedError:
        # The audio was recognised (and paid for) even though the words are refused.
        service.count_refused_turn(session, settings, heard_seconds)
        session.commit()
        raise
    audio_b64: str | None = None
    audio_type: str | None = None
    try:
        speech = await provider.synthesize(turn.reply.reply)
        audio_b64 = base64.b64encode(speech.audio).decode("ascii")
        audio_type = speech.media_type
        turn = service.add_spoken_seconds(
            session, settings, turn, voice_api.seconds_spoken(turn.reply.reply)
        )
    except voice_api.SpeechProviderError:
        pass  # the text still goes back; the page shows it and the call goes on
    session.commit()
    return PublicVoiceReply(
        token=turn.reply.token,
        heard=heard,
        reply=turn.reply.reply,
        lead_saved=turn.reply.lead_saved,
        audio_base64=audio_b64,
        audio_type=audio_type,
        seconds_left=turn.seconds_left,
        turns_left=turn.turns_left,
        call_ended=turn.call_ended,
    )


@staff_router.get(
    "/leads/{lead_id}/transcript",
    summary="The website chat that created a lead you may see (empty if there was none)",
    responses=problem_responses(404),
)
def lead_transcript(lead_id: uuid.UUID, principal: LeadReader, session: Db) -> PublicChatTranscript:
    return service.lead_transcript(session, principal, lead_id)
