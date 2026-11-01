"""The automatic Qualifier: assess a new website lead without anyone asking (docs/qualifier.md).

Off by default (``CRM_QUALIFIER_AUTO_WEB_LEADS``). When it is on, the worker hands every
``public_chat.lead_captured`` event (ADR 0006, 0013) to this module, which runs the very same
``assess_lead`` as the Qualify button, acting as the organisation's Automation identity. So every
rule still applies: the registry switch and token budget, the limits, the strict check, the
Sentinel, "someone else must approve", the audit. The proposal's requester is the Automation
identity, so any manager may approve it (nobody is excluded as "the asker").

An event may be delivered twice and a person may already have asked: a lead that has been assessed
is skipped. Nothing here can fail the event for a business reason (no procedure, switched off,
over a limit): those finish quietly. Only a model that is down is retried.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.events import Event, EventHandler, uuid_of
from app.modules.agents import api as agents_api
from app.modules.assistant.api import AssistantUnavailableError, ChatModel
from app.modules.identity import api as identity_api
from app.modules.qualifier import assess, repository
from app.modules.qualifier.llm import model_for

logger = logging.getLogger(__name__)
EVENT = "public_chat.lead_captured"
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def run_for_event(
    session: Session,
    event: Event,
    settings: Settings,
    model_factory: Callable[[Settings], ChatModel] = model_for,
) -> bool:
    """Assess the lead of one event. True when an assessment was made."""
    lead_id = uuid_of(event, "lead_id")
    if repository.count_assessments(session, event.tenant_id, since=LONG_AGO, lead_id=lead_id):
        return False  # already assessed (this event delivered twice, or a person was first)
    automation = identity_api.automation_principal(session, event.tenant_id)
    identity_api.bind_reader(session, automation)  # the worker binds only the tenant
    try:
        assess.assess_lead(
            session,
            automation,
            model_factory(settings),
            lead_id,
            limits=assess.Limits.from_settings(settings),
            ai_limits=agents_api.Limits.from_settings(settings),
        )
    except AssistantUnavailableError:
        raise  # the model is down: let the outbox retry
    except DomainError as refusal:
        # No procedure, switched off, over a budget or a limit, an unusable answer ...: nothing
        # to retry. Only the code is logged - never the lead or what the model wrote.
        logger.info("automatic qualification skipped", extra={"code": refusal.code})
        return False
    return True


def event_subscribers(
    settings: Settings,
    model_factory: Callable[[Settings], ChatModel] = model_for,
) -> dict[str, list[EventHandler]]:
    """{event name: [handler]}; empty while the setting is off, so the event just finishes."""
    if not settings.qualifier_auto_web_leads:
        return {}

    def handle(session: Session, event: Event) -> None:
        run_for_event(session, event, settings, model_factory)

    return {EVENT: [handle]}


__all__ = ["EVENT", "event_subscribers", "run_for_event"]
