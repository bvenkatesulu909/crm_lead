"""The worker step of batch research (ADR 0042, step BR3): ONE account per run.

    batch still running? ─► cancelled? ─► gates (switches, month, the batch's own cap)
    ─► next queued account ─► still readable by the starter? ─► single-account research
    (deal_desk.run_research, as the starter) ─► item ends ─► next step, or the batch ends

Every run does at most one model call, so a stop (cancel, cap, switch) takes effect before the next
account and a crashed worker resumes at the next unfinished one. Running a step twice is harmless:
a batch that is no longer running, or an item that already ended, is left alone.

The research itself is the single-account function, called as the person who started the batch, so
access, citations, cleaning and the registry's metering are exactly those of the single button.
Nothing here reads an account's data or builds a prompt.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.config import Settings
from app.core.events import publish
from app.core.outbox import DeadJobHandler, Job, JobHandler, PermanentJobError
from app.modules.accounts import api as accounts_api
from app.modules.agents import api as agents_api
from app.modules.assistant.api import ChatModel
from app.modules.deal_desk import api as deal_desk_api
from app.modules.identity import api as identity_api
from app.modules.research_batches import repository, rules
from app.modules.research_batches.models import ResearchBatch, ResearchBatchItem
from app.modules.research_batches.service import (
    BATCHES,
    ENTITY,
    RESEARCH,
    enqueue_step,
    worst_case,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3  # tries for one account when the model is temporarily unavailable
_AGENT_STOPS = (agents_api.AgentUnavailableError, agents_api.AgentBudgetReachedError)


class RetryStep(Exception):
    """The model was unavailable: the outbox runs this step again after its back-off."""


@dataclass(frozen=True)
class StepResult:
    more: bool  # another step should run
    ended: str | None = None  # the batch's end state, when this step ended it


# --- ending a batch -------------------------------------------------------------------


def _used(
    session: Session, tenant_id: uuid.UUID, settings: Settings, now: datetime
) -> tuple[int, int]:
    state = agents_api.effective(
        session, tenant_id, RESEARCH, agents_api.Limits.from_settings(settings), now
    )
    return state.input_tokens, state.output_tokens


def _finish(
    session: Session, batch: ResearchBatch, outcome: str, now: datetime, actor: Principal | None
) -> StepResult:
    """Every account that never started becomes ``not_run``; then the batch ends, is audited and
    the person who started it is told (ids and counts only)."""
    items = repository.items(session, batch.tenant_id, batch.id)
    for item in items:
        if item.status in ("queued", "running"):
            item.status, item.finished_at = "not_run", now
    batch.status, batch.finished_at = outcome, now
    session.flush()
    counts = rules.counts(i.status for i in items)
    changes: dict[str, Any] = {"outcome": outcome, "tokens_used": batch.tokens_used, **counts}
    # When the starter is gone the entry is still written, by the organisation's Automation
    # identity (the audit log always names an actor).
    who = actor or identity_api.automation_principal(session, batch.tenant_id)
    record_audit(
        session,
        who,
        action=f"research_batch.{outcome}",
        entity_type=ENTITY,
        entity_id=batch.id,
        changes=changes,
    )
    publish(
        session,
        batch.tenant_id,
        "research_batch.finished",
        {
            "batch_id": str(batch.id),
            "outcome": outcome,
            "accounts": batch.account_count,
            "done": counts["done"] + counts["reused"],
            "requested_by_user_id": str(batch.created_by_user_id),
        },
    )
    return StepResult(more=False, ended=outcome)


# --- one step -------------------------------------------------------------------------


def run_step(
    session: Session,
    tenant_id: uuid.UUID,
    batch_id: uuid.UUID,
    settings: Settings,
    model: ChatModel,
    now: datetime | None = None,
) -> StepResult:
    when = now or datetime.now(UTC)
    batch = repository.get(session, tenant_id, batch_id, lock=True)
    if batch is None:
        raise PermanentJobError("the research batch no longer exists")
    if batch.status != "running":
        return StepResult(more=False)  # already ended: a repeated step does nothing

    starter = identity_api.staff_principal(session, tenant_id, batch.created_by_user_id)
    if starter is None:  # left the organisation, deactivated, or the organisation is suspended
        return _finish(session, batch, "stopped_error", when, None)
    identity_api.bind_reader(session, starter)

    if batch.cancel_requested:
        return _finish(session, batch, "cancelled", when, starter)

    limits = agents_api.Limits.from_settings(settings)
    try:
        agents_api.check_can_call(session, tenant_id, BATCHES, limits, when)
        agents_api.check_can_call(session, tenant_id, RESEARCH, limits, when)
    except _AGENT_STOPS:
        return _finish(session, batch, "stopped_budget", when, starter)
    # The hard cap: even this account's worst case must still fit.
    if not rules.may_start_next(batch.tokens_used, worst_case(settings), batch.token_cap):
        return _finish(session, batch, "stopped_budget", when, starter)

    items = repository.items(session, tenant_id, batch_id)
    queued = [i for i in items if i.status == "queued"]
    if not queued:
        return _finish(session, batch, "finished", when, starter)
    item = queued[0]
    item.status, item.started_at, item.attempts = "running", when, item.attempts + 1
    session.flush()

    ended = _research_one(session, starter, batch, item, settings, model, when)
    if ended == "stop_budget":
        return _finish(session, batch, "stopped_budget", when, starter)
    session.flush()
    if any(i.status == "queued" for i in items):
        return StepResult(more=True)
    return _finish(session, batch, "finished", when, starter)


def _research_one(
    session: Session,
    starter: Principal,
    batch: ResearchBatch,
    item: ResearchBatchItem,
    settings: Settings,
    model: ChatModel,
    when: datetime,
) -> str | None:
    """Research one account and record how it went. ``"stop_budget"`` when a gate closed after
    the item was picked (the item goes back to the queue and is marked not run by the finish)."""
    tenant_id = batch.tenant_id
    if not accounts_api.is_readable_account(session, starter, item.account_id):
        item.status, item.finished_at = "skipped", when  # access was lost since the list was made
        return None

    before = _used(session, tenant_id, settings, when)
    brief_id: uuid.UUID | None = None
    failure: str | None = None
    skipped = False
    try:
        brief = deal_desk_api.run_research(
            session,
            starter,
            model,
            item.account_id,
            limits=deal_desk_api.Limits.from_settings(settings),
            ai_limits=agents_api.Limits.from_settings(settings),
            now=when,
        )
        brief_id = brief.id
    except deal_desk_api.AccountNotFoundError:
        skipped = True
    except deal_desk_api.ResearchRateLimitedError:
        failure = "rate_limited"
    except deal_desk_api.ResearchNoSourceError:
        failure = "no_sourced_sentence"
    except deal_desk_api.ResearchInvalidError:
        failure = "answer_refused"
    except _AGENT_STOPS:
        item.status = "queued"  # not started after all
        return "stop_budget"
    except Exception as error:  # a model that is down, a timeout: try again later
        logger.warning("research batch step failed: %s", type(error).__name__)
        if item.attempts < MAX_ATTEMPTS:
            item.status = "queued"
            session.flush()
            raise RetryStep from None
        failure = "unavailable"

    after = _used(session, tenant_id, settings, when)
    item.input_tokens = max(0, after[0] - before[0])
    item.output_tokens = max(0, after[1] - before[1])
    batch.tokens_used += item.input_tokens + item.output_tokens  # also for a refused answer
    item.finished_at = when
    if skipped:
        item.status = "skipped"
    elif failure is not None:
        rules.check_failure("failed", failure)
        item.status, item.failure_code = "failed", failure
    else:
        item.status, item.brief_id = "done", brief_id
    return None


# --- the worker's handlers ------------------------------------------------------------


def _parse(job: Job) -> tuple[uuid.UUID, uuid.UUID]:
    try:
        return uuid.UUID(str(job.payload["tenant_id"])), uuid.UUID(str(job.payload["batch_id"]))
    except (KeyError, ValueError) as error:
        raise PermanentJobError("payload of the research batch job is not valid") from error


def job_handler(settings: Settings, model: ChatModel) -> JobHandler:
    """One step per job; a step that leaves work behind queues the next one."""

    def handle(session: Session, job: Job) -> None:
        tenant_id, batch_id = _parse(job)
        if tenant_id != job.tenant_id:
            raise PermanentJobError("payload of the research batch job is not valid")
        result = run_step(session, tenant_id, batch_id, settings, model)
        if result.more:
            enqueue_step(session, tenant_id, batch_id)

    return handle


def dead_job_handler() -> DeadJobHandler:
    """The step gave up for good: the batch ends as an error and the rest is not run."""

    def handle(session: Session, job: Job, error: str) -> None:
        try:
            tenant_id, batch_id = _parse(job)
        except PermanentJobError:
            return
        batch = repository.get(session, tenant_id, batch_id, lock=True)
        if batch is None or batch.status != "running":
            return
        for item in repository.items(session, tenant_id, batch_id):
            if item.status == "running":
                item.status, item.failure_code = "failed", "error"
                item.finished_at = datetime.now(UTC)
        _finish(session, batch, "stopped_error", datetime.now(UTC), None)

    return handle
