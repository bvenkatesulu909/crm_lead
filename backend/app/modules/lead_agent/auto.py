"""The automatic lead agent: look at a new website lead without anyone asking (ADR 0022, LA4).

Off by default (``CRM_LEAD_AGENT_AUTO_WEB_LEADS``). When on, the worker hands every
``public_chat.lead_captured`` event to this module, which runs the very same ``run_lead_agent`` as
the button, acting as the organisation's Automation identity. So every rule still applies: the
registry switch (the agent also starts OFF there), the token budget, the limits, the strict
check, the Sentinel, "someone else must approve", the audit.

An event may be delivered twice and a person may already have asked: a lead the agent has looked
at is skipped. Nothing here fails the event for a business reason (switched off, over a limit, an
unusable answer): those finish quietly. Only a model that is down is retried.
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
from app.modules.lead_agent import service
from app.modules.lead_agent.llm import model_for

logger = logging.getLogger(__name__)
EVENT = "public_chat.lead_captured"
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def run_for_event(
    session: Session,
    event: Event,
    settings: Settings,
    model_factory: Callable[[Settings], ChatModel] = model_for,
) -> bool:
    """Look at the lead of one event. True when the agent ran."""
    lead_id = uuid_of(event, "lead_id")
    if service.count_runs(session, event.tenant_id, LONG_AGO, lead_id):
        return False  # already looked at (this event delivered twice, or a person was first)
    automation = identity_api.automation_principal(session, event.tenant_id)
    identity_api.bind_reader(session, automation)  # the worker binds only the tenant
    try:
        service.run_lead_agent(
            session,
            automation,
            model_factory(settings),
            lead_id,
            limits=service.Limits.from_settings(settings),
            ai_limits=agents_api.Limits.from_settings(settings),
        )
    except AssistantUnavailableError:
        raise  # the model is down: let the outbox retry
    except DomainError as refusal:
        # Switched off, over a budget or a limit, an unusable answer ...: nothing to retry. Only
        # the code is logged - never the lead or what the model wrote.
        logger.info("automatic lead agent skipped", extra={"code": refusal.code})
        return False
    return True


def event_subscribers(
    settings: Settings,
    model_factory: Callable[[Settings], ChatModel] = model_for,
) -> dict[str, list[EventHandler]]:
    """{event name: [handler]}; empty while the setting is off, so the event just finishes."""
    if not settings.lead_agent_auto_web_leads:
        return {}

    def handle(session: Session, event: Event) -> None:
        run_for_event(session, event, settings, model_factory)

    return {EVENT: [handle]}


__all__ = ["EVENT", "event_subscribers", "run_for_event"]
