"""The public website chat (ADR 0013, step PC3).

    visitor message ─► honeypot + guardrails ─► model available? ─► limits ─► conversation
        ─► model (≤ 2 tool rounds, one tool: save_lead) ─► plain-text answer (sanitised)

The service never commits; the router commits once. A visitor can never read CRM data: the only
tool saves a lead, and the answer holds just the reply text and "details saved: yes/no".
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.errors import DomainError, NotFoundError
from app.core.events import publish
from app.core.screening import screen
from app.modules.agents import api as agents_api
from app.modules.assistant import api as assistant_api
from app.modules.buyer_memory import api as buyer_memory_api
from app.modules.identity import api as identity_api
from app.modules.leads import api as leads_api
from app.modules.public_chat import repository, rules
from app.modules.public_chat.models import MESSAGE_MAX, PublicChatMessage, PublicChatSession
from app.modules.public_chat.schemas import (
    PublicChatReply,
    PublicChatRequest,
    PublicChatTranscript,
    TranscriptMessage,
)


class PublicChatNotFoundError(NotFoundError):
    """The feature is off, misconfigured, or the caller isn't our web server."""

    code = "not_found"

    def __init__(self) -> None:
        super().__init__("Not found.")


class ConversationNotFoundError(NotFoundError):
    code = "conversation_not_found"

    def __init__(self) -> None:
        super().__init__("This conversation doesn't exist any more. Please start a new one.")


class MessageRefusedError(DomainError):
    status_code = 422
    code = "message_refused"


class RateLimitedError(DomainError):
    status_code = 429
    code = "public_chat_rate_limited"

    def __init__(self) -> None:
        super().__init__("You have sent many messages. Please wait a while and try again.")


class BusyError(DomainError):
    status_code = 429
    code = "public_chat_busy"

    def __init__(self) -> None:
        super().__init__("The chat is very busy today. Please try again tomorrow or call us.")


class VoiceConsentRequiredError(DomainError):
    status_code = 422
    code = "voice_consent_required"

    def __init__(self) -> None:
        super().__init__("Please read the notice and press Start before talking.")


class ReceptionistUnavailableError(DomainError):
    """Switched off, out of budget or out of minutes: the page offers the typed chat instead."""

    status_code = 503
    code = "receptionist_unavailable"

    def __init__(self) -> None:
        super().__init__(rules.VOICE_RESTING_REPLY)


class VoiceLimitError(DomainError):
    status_code = 429
    code = "voice_limit_reached"


class HeardNothingError(DomainError):
    status_code = 422
    code = "voice_heard_nothing"

    def __init__(self) -> None:
        super().__init__("I could not hear anything. Please try again, or type your message.")


class LeadNotFoundError(NotFoundError):
    code = "lead_not_found"

    def __init__(self) -> None:
        # Same answer whether the lead doesn't exist, is another tenant's or isn't yours.
        super().__init__("Lead not found.")


def _now() -> datetime:
    return datetime.now(UTC)


def _check_limits(
    session: Session,
    settings: Settings,
    tenant_id: uuid.UUID,
    ip_hash: str,
    conversation: PublicChatSession | None,
) -> None:
    now = _now()
    since_day, since_hour = now - timedelta(days=1), now - timedelta(hours=1)
    if repository.visitor_messages_since(session, tenant_id, since_day) >= (
        settings.public_chat_messages_per_day
    ):
        raise BusyError()
    if repository.visitor_messages_since(session, tenant_id, since_hour, ip_hash=ip_hash) >= (
        settings.public_chat_messages_per_ip_hour
    ):
        raise RateLimitedError()
    if conversation is None:
        started = repository.sessions_started_since(session, tenant_id, ip_hash, since_hour)
        if started >= settings.public_chat_sessions_per_ip_hour:
            raise RateLimitedError()
    elif repository.visitor_messages_in(session, conversation) >= (
        settings.public_chat_messages_per_session
    ):
        raise RateLimitedError()


def _save_lead(
    session: Session,
    tenant_id: uuid.UUID,
    conversation: PublicChatSession,
    arguments: Any,
    language: str = "en",
) -> tuple[str, bool]:
    """Run save_lead. Returns (content for the model, is_error)."""
    if conversation.lead_id is not None:
        return json.dumps({"saved": False, "already_saved": True}), False
    try:
        args = rules.SaveLeadArgs.model_validate(arguments)
    except ValidationError as exc:
        # Only field names and messages go back to the model, never the values.
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return f"The details are not complete or not valid ({problems}). Ask the visitor.", True
    # The tenant's Automation identity creates the lead (unassigned, audited by the leads
    # module). It reads all leads, so leads' RLS allows a lead without an owner.
    automation = identity_api.automation_principal(session, tenant_id)
    identity_api.bind_reader(session, automation)
    # What is stored is read later by staff and by their assistants, so it is cleaned at the door
    # (ADR 0018): hidden text, markup, images and links go, instructions are kept but reported.
    codes: list[str] = []

    def cleaned(text: str | None) -> tuple[str | None, list[str]]:
        if text is None:
            return None, []
        result = screen(text)
        found = [f.code for f in result.findings]
        codes.extend(c for c in found if c not in codes)
        return result.clean.strip(), found

    full_name, name_found = cleaned(args.full_name)
    if not full_name or len(full_name) < 2 or set(name_found) - rules.HARMLESS_NAME_FINDINGS:
        return "The name is not valid. Ask the visitor for their full name again.", True
    location, _ = cleaned(args.location)
    notes, _ = cleaned(args.notes)
    first_name, last_name = rules.split_name(full_name)
    conversation.lead_id = leads_api.create_lead_from_website(
        session,
        automation,
        first_name=first_name,
        last_name=last_name,
        phone=args.phone,
        email=args.email,
        property_type=args.property_type,
        budget_min_inr=args.budget_min_inr,
        budget_max_inr=args.budget_max_inr,
        location=location,
        notes=notes,
        preferred_language=language,
        cleaned_codes=codes,
    )
    session.flush()
    # What the visitor gave becomes buyer memory facts that cite this conversation (ADR 0028).
    buyer_memory_api.record_from_website_chat(
        session,
        automation,
        conversation.lead_id,
        conversation.id,
        property_type=args.property_type,
        budget_min_inr=args.budget_min_inr,
        budget_max_inr=args.budget_max_inr,
        location=location,
    )
    repository.count_event(session, tenant_id, _now().date(), leads=1)
    # Sales managers hear about it through the worker (notifications, ADR 0006): IDs only.
    publish(
        session,
        tenant_id,
        "public_chat.lead_captured",
        {"lead_id": str(conversation.lead_id), "session_id": str(conversation.id)},
    )
    return json.dumps({"saved": True}), False


def handle_message(
    session: Session,
    settings: Settings,
    model: assistant_api.ChatModel,
    data: PublicChatRequest,
    *,
    visitor_ip: str,
) -> PublicChatReply:
    """A typed message (ADR 0013)."""
    reply, _, _ = _handle(session, settings, model, data, visitor_ip=visitor_ip)
    return reply


def _handle(
    session: Session,
    settings: Settings,
    model: assistant_api.ChatModel,
    data: PublicChatRequest,
    *,
    visitor_ip: str,
    channel: str = "text",
    consent_version: int | None = None,
) -> tuple[PublicChatReply, PublicChatSession, uuid.UUID]:
    """One visitor message, typed or heard. Channel "web_voice" adds the spoken-number check, the
    voice prompt rules and the receptionist's own registry entry (ADR 0038)."""
    voice = channel == "web_voice"
    slug = settings.public_chat_tenant_slug
    key = settings.public_chat_server_key
    tenant = identity_api.active_tenant_by_slug(session, slug) if slug else None
    if tenant is None or key is None:
        raise PublicChatNotFoundError()
    tenant_id, organisation = tenant

    if data.website.strip():
        raise MessageRefusedError("Your message could not be sent.")
    decision = assistant_api.inspect_input(data.message)
    if not decision.allowed:
        raise MessageRefusedError(decision.reason)
    message = decision.clean
    if voice and rules.spoken_number_refusal(message):
        raise MessageRefusedError(rules.VOICE_NO_SECRETS_REPLY)
    if not model.available:
        raise assistant_api.AssistantUnavailableError(
            "The chat is not available right now. Please call us or try again later."
        )

    bind_tenant(session, tenant_id)
    ip_hash = rules.hash_ip(visitor_ip, key.get_secret_value())
    conversation: PublicChatSession | None = None
    token = data.token
    if token is not None:
        conversation = repository.find_session(session, tenant_id, rules.hash_token(token))
        if conversation is None:
            raise ConversationNotFoundError()
    _check_limits(session, settings, tenant_id, ip_hash, conversation)
    if conversation is None or token is None:
        token = rules.new_token()
        conversation = PublicChatSession(
            tenant_id=tenant_id,
            token_hash=rules.hash_token(token),
            visitor_ip_hash=ip_hash,
            channel=channel,
            voice_consent_at=_now() if voice else None,
            voice_consent_version=consent_version if voice else None,
        )
        session.add(conversation)
        session.flush()
        # Anonymous, and kept after the conversation itself is cleaned up (docs/pilot-report.md).
        repository.count_event(session, tenant_id, _now().date(), started=1)

    if voice and conversation.channel != "web_voice":
        # A typed conversation that goes on by voice: the consent was checked before the audio
        # was sent, and is recorded now (the database refuses a voice channel without it).
        conversation.channel = "web_voice"
        conversation.voice_consent_at = _now()
        conversation.voice_consent_version = consent_version
    session.add(
        PublicChatMessage(
            tenant_id=tenant_id,
            session_id=conversation.id,
            role="visitor",
            content=message[:MESSAGE_MAX],
        )
    )
    session.flush()
    messages: list[dict[str, Any]] = [
        {"role": "user" if m.role == "visitor" else "assistant", "content": m.content}
        for m in repository.recent_messages(session, conversation, rules.HISTORY_MESSAGES)
    ]
    system = rules.SYSTEM_PROMPT.format(
        organisation=organisation, language_rule=rules.LANGUAGE_RULES[data.language]
    )

    if voice:
        system += "\n" + rules.VOICE_RULES.format(organisation=organisation)

    # The spoken receptionist is its own registry entry: its own switch, budget and tool filter.
    model = agents_api.governed(
        model,
        session,
        tenant_id,
        "receptionist" if voice else "public_chat",
        agents_api.Limits.from_settings(settings),
    )
    answer = rules.FALLBACK_REPLY
    for _ in range(rules.MAX_TOOL_ROUNDS + 1):
        try:
            reply = model.reply(system=system, messages=messages, tools=[rules.SAVE_LEAD_TOOL])
        except (agents_api.AgentUnavailableError, agents_api.AgentBudgetReachedError):
            # Switched off or over budget (ADR 0016): the page keeps working, nothing is saved.
            answer = rules.VOICE_RESTING_REPLY if voice else rules.RESTING_REPLY
            break
        if not reply.tool_uses:
            answer = assistant_api.sanitise_output(reply.text or rules.FALLBACK_REPLY)
            break
        messages.append({"role": "assistant", "content": reply.as_content()})
        results = []
        for use in reply.tool_uses:
            if use.name == "save_lead":
                content, is_error = _save_lead(
                    session, tenant_id, conversation, use.input, data.language
                )
            else:
                content, is_error = "This tool doesn't exist. Only save_lead is available.", True
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": use.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": results})

    session.add(
        PublicChatMessage(
            tenant_id=tenant_id,
            session_id=conversation.id,
            role="assistant",
            content=answer[:MESSAGE_MAX],
        )
    )
    conversation.updated_at = _now()
    session.flush()
    result = PublicChatReply(token=token, reply=answer, lead_saved=conversation.lead_id is not None)
    return result, conversation, tenant_id


# --- the spoken turn (ADR 0038, step VR2) -----------------------------------------------------


@dataclass(frozen=True)
class VoiceTurn:
    reply: PublicChatReply
    conversation_id: uuid.UUID
    tenant_id: uuid.UUID
    seconds_left: int
    turns_left: int
    call_ended: bool


def _website_tenant(session: Session, settings: Settings) -> uuid.UUID:
    slug = settings.public_chat_tenant_slug
    tenant = identity_api.active_tenant_by_slug(session, slug) if slug else None
    if tenant is None or settings.public_chat_server_key is None:
        raise PublicChatNotFoundError()
    bind_tenant(session, tenant[0])
    return tenant[0]


def voice_precheck(
    session: Session,
    settings: Settings,
    *,
    token: str | None,
    consent_version: int | None,
    visitor_ip: str,
) -> None:
    """Everything that can be refused BEFORE any audio is sent to the speech service, so a refused
    visitor costs nothing: the organisation's switch, budget and minutes, the visitor's consent
    (the notice they read), the per-address and per-call limits. Writes nothing."""
    tenant_id = _website_tenant(session, settings)
    now = _now()
    try:
        agents_api.check_can_call(
            session, tenant_id, "receptionist", agents_api.Limits.from_settings(settings), now
        )
    except (agents_api.AgentUnavailableError, agents_api.AgentBudgetReachedError):
        raise ReceptionistUnavailableError() from None
    today = now.date()
    month_start = today.replace(day=1)
    if (
        repository.voice_seconds_between(session, tenant_id, today, today)
        >= settings.receptionist_minutes_per_day * 60
        or repository.voice_seconds_between(session, tenant_id, month_start, today)
        >= settings.receptionist_minutes_per_month * 60
    ):
        raise ReceptionistUnavailableError()

    conversation: PublicChatSession | None = None
    if token is not None:
        conversation = repository.find_session_unlocked(session, tenant_id, rules.hash_token(token))
        if conversation is None:
            raise ConversationNotFoundError()
    if conversation is None or conversation.channel != "web_voice":
        # The first spoken turn of a conversation: the visitor must have pressed Start after
        # reading THIS version of the notice. No press, no microphone.
        if consent_version != settings.receptionist_notice_version:
            raise VoiceConsentRequiredError()
    if conversation is None:
        key = settings.public_chat_server_key
        if key is None:  # _website_tenant checked it already
            raise PublicChatNotFoundError()
        ip_hash = rules.hash_ip(visitor_ip, key.get_secret_value())
        calls = repository.sessions_started_since(
            session, tenant_id, ip_hash, now - timedelta(days=1), channel="web_voice"
        )
        if calls >= settings.receptionist_calls_per_ip_day:
            raise VoiceLimitError("You have made several calls today. Please try again tomorrow.")
    elif (
        conversation.voice_turns >= settings.receptionist_max_turns
        or conversation.voice_seconds >= settings.receptionist_max_call_seconds
    ):
        raise VoiceLimitError(
            "This call has reached its time limit. Please leave your number or call us."
        )


def handle_voice_message(
    session: Session,
    settings: Settings,
    model: assistant_api.ChatModel,
    *,
    heard: str,
    token: str | None,
    language: str,
    website: str,
    consent_version: int | None,
    visitor_ip: str,
    heard_seconds: int,
) -> VoiceTurn:
    """What the visitor said, as text, through the same pipeline as a typed message. Adds the
    heard seconds to the call and to the organisation's day. The reply's spoken seconds are added
    by ``add_spoken_seconds`` once the speech exists."""
    data = PublicChatRequest.model_validate(
        {"token": token, "message": heard, "website": website, "language": language}
    )
    reply, conversation, tenant_id = _handle(
        session,
        settings,
        model,
        data,
        visitor_ip=visitor_ip,
        channel="web_voice",
        consent_version=consent_version,
    )
    conversation.voice_turns += 1
    conversation.voice_seconds += heard_seconds
    repository.count_event(session, tenant_id, _now().date(), voice_seconds=heard_seconds)
    session.flush()
    return _turn(settings, reply, conversation, tenant_id)


def _turn(
    settings: Settings,
    reply: PublicChatReply,
    conversation: PublicChatSession,
    tenant_id: uuid.UUID,
) -> VoiceTurn:
    seconds_left = max(0, settings.receptionist_max_call_seconds - conversation.voice_seconds)
    turns_left = max(0, settings.receptionist_max_turns - conversation.voice_turns)
    ended = seconds_left == 0 or turns_left == 0
    return VoiceTurn(reply, conversation.id, tenant_id, seconds_left, turns_left, ended)


def add_spoken_seconds(
    session: Session, settings: Settings, turn: VoiceTurn, seconds: int
) -> VoiceTurn:
    """Count the seconds of the spoken reply (an estimate) against the call and the day."""
    bind_tenant(session, turn.tenant_id)
    conversation = repository.get_session(session, turn.tenant_id, turn.conversation_id)
    if conversation is None:  # cannot happen inside the same transaction
        return turn
    conversation.voice_seconds += seconds
    repository.count_event(session, turn.tenant_id, _now().date(), voice_seconds=seconds)
    session.flush()
    return _turn(settings, turn.reply, conversation, turn.tenant_id)


def count_refused_turn(session: Session, settings: Settings, heard_seconds: int) -> None:
    """A refused spoken turn (a card number said aloud, nothing heard) still cost speech
    recognition: count its seconds against the organisation's day so it cannot be repeated for
    free. The caller commits."""
    tenant_id = _website_tenant(session, settings)
    repository.count_event(session, tenant_id, _now().date(), voice_seconds=heard_seconds)


# --- staff: the conversation on the lead page (step PC4) -------------------------------------


def lead_transcript(
    session: Session, principal: Principal, lead_id: uuid.UUID
) -> PublicChatTranscript:
    """The website conversation of a lead the principal may see (the leads module decides)."""
    if principal.tenant_id is None or not leads_api.is_readable_lead(session, principal, lead_id):
        raise LeadNotFoundError()
    conversation = repository.session_of_lead(session, principal.tenant_id, lead_id)
    if conversation is None:
        return PublicChatTranscript(started_at=None, messages=[])
    return PublicChatTranscript(
        started_at=conversation.created_at,
        channel="web_voice" if conversation.channel == "web_voice" else "text",
        voice_seconds=conversation.voice_seconds,
        messages=[
            TranscriptMessage.model_validate(m)
            for m in repository.all_messages(session, conversation)
        ],
    )


# --- worker: privacy clean-up (step PC4) ------------------------------------------------------


def delete_stale_conversations(
    session: Session, now: datetime, *, tenant_id: uuid.UUID, retention_days: int
) -> int:
    """Conversations that never became a lead are kept ``retention_days`` after their last
    message, then deleted (ADR 0013). Those that became a lead stay with the lead."""
    return repository.delete_stale(session, tenant_id, now - timedelta(days=retention_days))
