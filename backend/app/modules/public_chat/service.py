"""The public website chat (ADR 0013, step PC3).

    visitor message ─► honeypot + guardrails ─► model available? ─► limits ─► conversation
        ─► model (≤ 2 tool rounds, one tool: save_lead) ─► plain-text answer (sanitised)

The service never commits; the router commits once. A visitor can never read CRM data: the only
tool saves a lead, and the answer holds just the reply text and "details saved: yes/no".
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.errors import DomainError, NotFoundError
from app.core.events import publish
from app.modules.agents import api as agents_api
from app.modules.assistant import api as assistant_api
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
    first_name, last_name = rules.split_name(args.full_name)
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
        location=args.location,
        notes=args.notes,
    )
    session.flush()
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
            tenant_id=tenant_id, token_hash=rules.hash_token(token), visitor_ip_hash=ip_hash
        )
        session.add(conversation)
        session.flush()

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
    system = rules.SYSTEM_PROMPT.format(organisation=organisation)

    model = agents_api.governed(
        model, session, tenant_id, "public_chat", agents_api.Limits.from_settings(settings)
    )
    answer = rules.FALLBACK_REPLY
    for _ in range(rules.MAX_TOOL_ROUNDS + 1):
        try:
            reply = model.reply(system=system, messages=messages, tools=[rules.SAVE_LEAD_TOOL])
        except (agents_api.AgentUnavailableError, agents_api.AgentBudgetReachedError):
            # Switched off or over budget (ADR 0016): the page keeps working, nothing is saved.
            answer = rules.RESTING_REPLY
            break
        if not reply.tool_uses:
            answer = assistant_api.sanitise_output(reply.text or rules.FALLBACK_REPLY)
            break
        messages.append({"role": "assistant", "content": reply.as_content()})
        results = []
        for use in reply.tool_uses:
            if use.name == "save_lead":
                content, is_error = _save_lead(session, tenant_id, conversation, use.input)
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
    return PublicChatReply(token=token, reply=answer, lead_saved=conversation.lead_id is not None)


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
