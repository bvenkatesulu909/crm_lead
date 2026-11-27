# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""The worker step of batch research (ADR 0042, BR3): one account per run, the hard cap, cancel,
partial failure, a lost account, a switch turned off mid-batch, retries, a dead step, isolation
between accounts, and the whole thing through the real worker. Only the model is scripted."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.core.mail import MemoryMailer
from app.core.outbox import Job, OutboxJob, PermanentJobError
from app.core.storage import MemoryFileStore
from app.modules.accounts.models import Account
from app.modules.agents import api as agents_api
from app.modules.assistant.llm import ModelReply, ToolUse
from app.modules.deal_desk.llm import FakeDealDeskModel
from app.modules.deal_desk.models import AccountBrief
from app.modules.deal_desk.research_rules import TOOL
from app.modules.identity.models import User
from app.modules.notifications.models import Notification
from app.modules.research_batches import api as batches_api
from app.modules.research_batches import service, worker
from app.modules.research_batches.models import ResearchBatch, ResearchBatchItem
from app.worker import WorkerServices, job_handlers, run_due_jobs
from tests.db.conftest import forget_request_user, session_factory_for
from tests.db.test_approvals import alpha
from tests.db.test_quotes_api import World, world
from tests.db.test_research_batch_service import (
    NOW,
    WORST,
    brief,
    make_settings,
    person,
    ready,
    rows,
    start,
    switch,
)


class Writer(FakeDealDeskModel):
    """The demo writer, counting calls, reporting tokens and keeping every prompt it was given."""

    def __init__(self, tokens: tuple[int, int] = (300, 200), mode: str = "ok") -> None:
        self.tokens = tokens
        self.mode = mode
        self.calls = 0
        self.prompts: list[str] = []
        self.message_counts: list[int] = []

    def reply(self, **kw: Any) -> ModelReply:
        self.calls += 1
        self.prompts.append(kw["system"])
        self.message_counts.append(len(kw["messages"]))
        if self.mode == "down":
            raise RuntimeError("the model is not reachable")
        if self.mode == "nosource":
            invented = {"text": "Invented.", "record_ids": [str(uuid.uuid4())]}
            made = ModelReply("", [ToolUse("w", TOOL, {"sentences": [invented]})])
        elif self.mode == "wrongshape":
            made = ModelReply("just words", [])
        else:
            made = super().reply(**kw)
        return ModelReply(
            made.text,
            made.tool_uses,
            made.stop_reason,
            {"input_tokens": self.tokens[0], "output_tokens": self.tokens[1]},
        )


def step(
    session: Session, world: World, batch: ResearchBatch, model: Any, **settings: Any
) -> worker.StepResult:
    return worker.run_step(session, alpha(world), batch.id, make_settings(**settings), model, NOW)


def items_of(session: Session, batch: ResearchBatch) -> list[ResearchBatchItem]:
    session.expire_all()
    return list(
        session.scalars(
            select(ResearchBatchItem)
            .where(ResearchBatchItem.batch_id == batch.id)
            .order_by(ResearchBatchItem.position)
        )
    )


def states(session: Session, batch: ResearchBatch) -> list[str]:
    return [i.status for i in items_of(session, batch)]


def audit_actions(session: Session) -> list[str]:
    return [a.action for a in session.scalars(select(AuditLog).order_by(AuditLog.occurred_at))]


@pytest.fixture
def batch(ready, world) -> ResearchBatch:
    created: ResearchBatch = start(ready, world, rows(world.ids["A1"], world.ids["A2"]), 2 * WORST)
    return created


# --- one account per step -----------------------------------------------------


def test_each_step_researches_exactly_one_account(ready, world, batch) -> None:
    writer = Writer()
    first = step(ready, world, batch, writer)
    assert first.more and first.ended is None and writer.calls == 1
    assert states(ready, batch) == ["done", "queued"]
    second = step(ready, world, batch, writer)
    assert not second.more and second.ended == "finished" and writer.calls == 2
    assert states(ready, batch) == ["done", "done"]
    ready.refresh(batch)
    assert batch.status == "finished" and batch.finished_at is not None


def test_every_item_points_at_its_own_stored_brief_and_counts_its_tokens(
    ready, world, batch
) -> None:
    writer = Writer(tokens=(300, 200))
    step(ready, world, batch, writer)
    step(ready, world, batch, writer)
    first, second = items_of(ready, batch)
    for account, item in ((world.ids["A1"], first), (world.ids["A2"], second)):
        stored = ready.get(AccountBrief, item.brief_id)
        assert stored is not None and stored.account_id == account
        assert (item.input_tokens, item.output_tokens) == (300, 200)
    ready.refresh(batch)
    assert batch.tokens_used == 1000


def test_a_step_on_an_ended_batch_does_nothing(ready, world, batch) -> None:
    writer = Writer()
    step(ready, world, batch, writer)
    step(ready, world, batch, writer)
    result = step(ready, world, batch, writer)
    assert result == worker.StepResult(more=False) and writer.calls == 2


def test_the_step_of_a_made_up_batch_is_a_permanent_error(ready, world) -> None:
    with pytest.raises(PermanentJobError):
        worker.run_step(ready, alpha(world), uuid.uuid4(), make_settings(), Writer(), NOW)


def test_finishing_is_audited_and_announced(ready, world, batch) -> None:
    writer = Writer()
    step(ready, world, batch, writer)
    step(ready, world, batch, writer)
    assert "research_batch.finished" in audit_actions(ready)
    entry = ready.scalars(
        select(AuditLog).where(AuditLog.action == "research_batch.finished")
    ).one()
    assert entry.changes["done"] == 2 and entry.changes["outcome"] == "finished"
    assert "Quote A1" not in str(entry.changes)
    jobs = [
        j for j in ready.scalars(select(OutboxJob)) if j.kind == "event.research_batch.finished"
    ]
    assert len(jobs) == 1 and jobs[0].payload["data"]["batch_id"] == str(batch.id)


# --- cancel -------------------------------------------------------------------


def test_a_cancel_stops_before_the_next_account_and_keeps_what_is_done(ready, world, batch) -> None:
    writer = Writer()
    step(ready, world, batch, writer)
    ready.execute(update(ResearchBatch).values(cancel_requested=True))
    result = step(ready, world, batch, writer)
    assert result.ended == "cancelled" and writer.calls == 1
    assert states(ready, batch) == ["done", "not_run"]
    assert "research_batch.cancelled" in audit_actions(ready)


def test_a_cancel_before_the_first_account_runs_nothing(ready, world, batch) -> None:
    ready.execute(update(ResearchBatch).values(cancel_requested=True))
    writer = Writer()
    assert step(ready, world, batch, writer).ended == "cancelled"
    assert writer.calls == 0 and states(ready, batch) == ["not_run", "not_run"]


# --- the hard stop ------------------------------------------------------------


def test_the_cap_stops_the_batch_before_an_account_whose_worst_case_would_pass_it(
    ready, world
) -> None:
    # A month budget of 10,024 holds the cap to 10,024 (one account's worst case is 9,024).
    switch(ready, world, "account_research", True, monthly_token_budget=WORST + 1000)
    batch = start(ready, world, rows(world.ids["A1"], world.ids["A2"]), 2 * WORST)
    assert batch.token_cap == WORST + 1000
    writer = Writer(tokens=(5000, 2000))  # 7,000 used: 7,000 + 9,024 would pass 10,024
    assert step(ready, world, batch, writer).more
    result = step(ready, world, batch, writer)
    assert result.ended == "stopped_budget" and writer.calls == 1
    assert states(ready, batch) == ["done", "not_run"]
    ready.refresh(batch)
    assert batch.tokens_used == 7000 <= batch.token_cap


def test_switching_account_research_off_mid_batch_stops_it(ready, world, batch) -> None:
    writer = Writer()
    step(ready, world, batch, writer)
    switch(ready, world, "account_research", False)
    assert step(ready, world, batch, writer).ended == "stopped_budget"
    assert writer.calls == 1 and states(ready, batch) == ["done", "not_run"]


def test_switching_the_batch_feature_off_mid_batch_stops_it(ready, world, batch) -> None:
    writer = Writer()
    step(ready, world, batch, writer)
    switch(ready, world, "research_batches", False)
    assert step(ready, world, batch, writer).ended == "stopped_budget"
    assert writer.calls == 1


def test_a_used_up_month_stops_the_batch(ready, world, batch) -> None:
    writer = Writer(tokens=(300, 200))
    step(ready, world, batch, writer)
    switch(ready, world, "account_research", True, monthly_token_budget=400)
    assert step(ready, world, batch, writer).ended == "stopped_budget"
    assert writer.calls == 1


def test_the_ai_platform_switch_stops_the_batch(ready, world, batch) -> None:
    writer = Writer()
    result = step(ready, world, batch, writer, ai_disabled=True)
    assert result.ended == "stopped_budget" and writer.calls == 0


# --- partial failure ----------------------------------------------------------


def test_one_failed_account_never_stops_the_others(ready, world, batch) -> None:
    bad = Writer(mode="nosource")
    step(ready, world, batch, bad)
    good = Writer()
    result = step(ready, world, batch, good)
    assert result.ended == "finished"
    first, second = items_of(ready, batch)
    assert (first.status, first.failure_code) == ("failed", "no_sourced_sentence")
    assert second.status == "done" and second.failure_code is None
    ready.refresh(batch)
    assert batch.status == "finished"  # a finished batch can contain failures


def test_a_failed_call_still_counts_the_tokens_it_used(ready, world, batch) -> None:
    step(ready, world, batch, Writer(tokens=(400, 100), mode="nosource"))
    first = items_of(ready, batch)[0]
    assert (first.input_tokens, first.output_tokens) == (400, 100)
    ready.refresh(batch)
    assert batch.tokens_used == 500


def test_an_answer_of_the_wrong_shape_is_refused_and_named(ready, world, batch) -> None:
    step(ready, world, batch, Writer(mode="wrongshape"))
    first = items_of(ready, batch)[0]
    assert (first.status, first.failure_code) == ("failed", "answer_refused")
    assert (
        ready.scalar(select(AccountBrief.id).where(AccountBrief.account_id == world.ids["A1"]))
        is None
    )


def test_an_account_researched_a_moment_ago_fails_as_rate_limited_not_silently(
    ready, world
) -> None:
    ready.add(brief(world, "A1", timedelta(minutes=10)))
    # The one-per-hour limit counts the audit entries of earlier briefs, as the single button does.
    ready.add(
        AuditLog(
            tenant_id=alpha(world),
            actor_subject="sub-alpha.manager",
            action="account_research.written",
            entity_type="account",
            entity_id=world.ids["A1"],
            changes={},
        )
    )
    ready.flush()
    batch = start(ready, world, rows(world.ids["A1"], again=True), WORST)
    step(ready, world, batch, Writer())
    assert items_of(ready, batch)[0].failure_code == "rate_limited"


def test_an_account_the_starter_can_no_longer_read_is_skipped_without_a_model_call(
    ready, world, batch
) -> None:
    ready.execute(update(Account).where(Account.id == world.ids["A1"]).values(deleted_at=NOW))
    writer = Writer()
    step(ready, world, batch, writer)
    assert states(ready, batch) == ["skipped", "queued"] and writer.calls == 0


# --- retries ------------------------------------------------------------------


def test_a_model_that_is_down_is_retried_then_recorded_and_the_batch_goes_on(
    ready, world, batch
) -> None:
    down = Writer(mode="down")
    for attempt in (1, 2):
        with pytest.raises(worker.RetryStep):
            step(ready, world, batch, down)
        first = items_of(ready, batch)[0]
        assert first.status == "queued" and first.attempts == attempt
    step(ready, world, batch, down)  # the third try is the last: it is recorded
    first = items_of(ready, batch)[0]
    assert (first.status, first.failure_code, first.attempts) == ("failed", "unavailable", 3)
    assert states(ready, batch)[1] == "queued"  # the next account is still to come
    assert step(ready, world, batch, Writer()).ended == "finished"


# --- the starter and a dead step ----------------------------------------------


def test_a_starter_who_left_stops_the_batch_as_an_error(ready, world, batch) -> None:
    ready.execute(
        update(User).where(User.id == world.users["alpha.manager"].id).values(is_active=False)
    )
    writer = Writer()
    result = step(ready, world, batch, writer)
    assert result.ended == "stopped_error" and writer.calls == 0
    assert states(ready, batch) == ["not_run", "not_run"]
    entry = ready.scalars(
        select(AuditLog).where(AuditLog.action == "research_batch.stopped_error")
    ).one()
    # Written by the Automation identity: the person is gone, but the log always names an actor.
    assert entry.actor_subject.startswith("automation:")
    assert entry.actor_user_id != world.users["alpha.manager"].id


def test_a_step_job_that_dies_ends_the_batch_and_marks_the_running_account(
    ready, world, batch
) -> None:
    item = items_of(ready, batch)[0]
    item.status = "running"
    ready.flush()
    job = Job(
        id=uuid.uuid4(),
        tenant_id=alpha(world),
        kind=service.STEP_JOB,
        payload={"batch_id": str(batch.id), "tenant_id": str(alpha(world))},
        attempt=5,
    )
    worker.dead_job_handler()(ready, job, "gave up")
    assert states(ready, batch) == ["failed", "not_run"]
    assert items_of(ready, batch)[0].failure_code == "error"
    ready.refresh(batch)
    assert batch.status == "stopped_error"


@pytest.mark.parametrize(
    "payload",
    [{}, {"batch_id": "x", "tenant_id": "y"}, {"batch_id": str(uuid.uuid4())}],
)
def test_a_step_job_with_a_bad_payload_is_permanent(ready, world, payload) -> None:
    job = Job(
        id=uuid.uuid4(), tenant_id=alpha(world), kind=service.STEP_JOB, payload=payload, attempt=1
    )
    with pytest.raises(PermanentJobError):
        worker.job_handler(make_settings(), Writer())(ready, job)


def test_a_step_job_naming_another_organisation_is_permanent(ready, world, batch) -> None:
    other = world.users["beta.admin"].tenant_id
    job = Job(
        id=uuid.uuid4(),
        tenant_id=other,
        kind=service.STEP_JOB,
        payload={"batch_id": str(batch.id), "tenant_id": str(alpha(world))},
        attempt=1,
    )
    with pytest.raises(PermanentJobError):
        worker.job_handler(make_settings(), Writer())(ready, job)


# --- isolation between accounts -----------------------------------------------


def test_no_prompt_holds_anything_of_another_account_and_every_call_starts_fresh(
    ready, world, batch
) -> None:
    writer = Writer()
    step(ready, world, batch, writer)
    step(ready, world, batch, writer)
    first, second = writer.prompts
    # The opportunities O1 / O2 and the accounts' names belong to one account each.
    assert "Quote A1" in first or "O1" in first
    assert "Quote A2" not in first and "O2" not in first
    assert "Quote A2" in second or "O2" in second
    assert "Quote A1" not in second and "O1" not in second
    for account_id in (world.ids["A1"], world.ids["A2"]):
        other = world.ids["A2"] if account_id == world.ids["A1"] else world.ids["A1"]
        prompt = first if account_id == world.ids["A1"] else second
        assert str(other) not in prompt
    # One fresh conversation per call: nothing carried over.
    assert writer.message_counts == [1, 1]


# --- starting queues the first step -------------------------------------------


def step_jobs(session: Session) -> list[OutboxJob]:
    return [j for j in session.scalars(select(OutboxJob)) if j.kind == service.STEP_JOB]


def test_starting_queues_exactly_one_step_with_ids_only(ready, world, batch) -> None:
    (job,) = step_jobs(ready)
    assert job.payload == {"batch_id": str(batch.id), "tenant_id": str(alpha(world))}
    assert job.tenant_id == alpha(world)


def test_a_batch_that_is_all_reused_queues_no_step(ready, world) -> None:
    ready.add(brief(world, "A1", timedelta(hours=1)))
    ready.flush()
    start(ready, world, rows(world.ids["A1"]), 0)
    assert step_jobs(ready) == []


# --- through the real worker --------------------------------------------------


def test_the_real_worker_researches_the_whole_batch_and_tells_the_starter(
    ready, world, db_connection, batch
) -> None:
    config = make_settings(ai_provider="fake")
    factory = session_factory_for(db_connection)
    handlers = job_handlers(WorkerServices(config, MemoryFileStore(), MemoryMailer()))
    with factory() as fresh, fresh.begin():
        forget_request_user(fresh)
    run_due_jobs(factory, handlers, config)
    bind_tenant(ready, alpha(world))
    assert states(ready, batch) == ["done", "done"]
    ready.refresh(batch)
    assert batch.status == "finished" and batch.tokens_used >= 0
    note = ready.scalars(
        select(Notification).where(Notification.user_id == world.users["alpha.manager"].id)
    ).all()
    mine = [n for n in note if n.type == "research_batch.finished"]
    assert len(mine) == 1
    assert mine[0].link == f"/research-batches/{batch.id}"
    assert mine[0].title == "Research of 2 accounts finished: 2 researched"
    # Nobody else was told.
    others = ready.scalars(
        select(Notification).where(Notification.type == "research_batch.finished")
    ).all()
    assert [n.user_id for n in others] == [world.users["alpha.manager"].id]
