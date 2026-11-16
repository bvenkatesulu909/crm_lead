"""Playing custom agents (ADR 0034, AB5; BP-10).

A case runs through the REAL ``custom_agents.run`` - permission, the agent (not archived), its
current version's dry run, the record only if the person may read it, the limits, the agent
registry, the strict check of the model's one tool call, the approval queue and its Sentinel, the
run record and the audit. Only the language model is scripted. Each message of a case is the id of
a record (a lead, an account or a deal, depending on what the agent reads) to run the agent on, in
order.

For every case the harness first has an administrator define the agent from the case's
``custom_agent`` setup, try it (a dry run) and switch it on - exactly the road an organisation
takes - inside a savepoint that is rolled back, so no agent leaks into the next case.

The checks only a database-level runner can make: nothing changed directly (no lead, no deal, no
activity); every proposal reported is stored and pending, was made by ``custom_agent`` naming THIS
agent, is one of the kinds its definition lists, has exactly the fields of that kind, is never
"converted" and holds no link; a run makes at most one proposal; every run and dry run is recorded
once and audited once, and a dry run never proposes.
"""

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent_evals.cases import (
    CallOutcome,
    Case,
    CustomAgentSetup,
    ScriptedCall,
    Step,
    substitute,
)
from agent_evals.runner import RunnerError, ScriptedModel, registry_outcome
from agent_evals.scoring import CaseResult, Check, ToolCall, Trajectory, score_case, with_checks
from agent_evals.world import Snapshot, World
from app.core.audit import AuditLog
from app.core.auth.principal import Principal
from app.core.db import bind_tenant
from app.core.errors import DomainError, NotFoundError
from app.modules.agents import api as agents_api
from app.modules.approvals.models import AgentAction
from app.modules.assistant.llm import ChatModel, ModelReply, ToolUse
from app.modules.custom_agents import api as custom_agents_api
from app.modules.custom_agents import rules, run, run_rules
from app.modules.custom_agents.models import CustomAgentRun

_LINK = re.compile(r"https?://|www\.", re.IGNORECASE)
# The fields a proposal of each kind may carry (the approvals module checks them too).
_FIELDS = {
    "lead.set_status": {"status"},
    "activity.create_task": {"subject", "due_in_days", "assignee_id"},
}
# Which placeholder is a record the admin's dry run can use, for each kind of record.
_TRIAL_RECORD = {"lead": "lead.own", "account": "account.own", "deal": "deal.own"}
_TRIAL_STEP = Step(
    calls=[
        ScriptedCall(
            name=run_rules.TOOL_NAME,
            arguments={"action": "none", "reason": "The setup dry run suggests nothing."},
        )
    ]
)


class _Recorder:
    """Passes calls on to the model and remembers what it asked for."""

    def __init__(self, inner: ChatModel) -> None:
        self._inner = inner
        self.available = bool(getattr(inner, "available", True))
        self.asked = 0
        self.uses: list[ToolUse] = []

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        self.asked += 1
        reply = self._inner.reply(system=system, messages=messages, tools=tools)
        self.uses.extend(reply.tool_uses)
        return reply


@dataclass(frozen=True)
class Prepared:
    agent_id: uuid.UUID
    key: str
    name: str
    kinds: list[str]
    record_type: str
    # The platform-wide limits to play with (the platform switch of this case).
    limits: agents_api.Limits


@dataclass(frozen=True)
class CustomRun:
    trajectory: Trajectory
    proposal_ids: list[uuid.UUID]
    # Runs (or dry runs) that finished and were recorded.
    finished: int


@contextmanager
def custom_agent_setup(
    session: Session, world: World, case: Case, values: dict[str, str]
) -> Iterator[Prepared]:
    """Have an administrator define, try and switch on the agent the case plays, the way the
    case's governance says; undone afterwards."""
    setup = case.custom_agent or CustomAgentSetup()
    nested = session.begin_nested()
    try:
        own = setup.owner == "own_organisation"
        admin = world.principal("tenant_admin") if own else world.other_admin()
        governance = case.governance
        limits = agents_api.Limits(
            governance.platform_disabled if governance else False,
            world.settings.agent_default_monthly_tokens,
        )
        usual = agents_api.Limits(False, world.settings.agent_default_monthly_tokens)
        now = datetime.now(UTC)
        record_type = rules.RECORD_TYPE_OF[setup.read_sets[0]]
        world.bind(admin)
        view = custom_agents_api.create_agent(
            session,
            admin,
            name=setup.name,
            purpose=setup.purpose,
            instruction=setup.instruction,
            read_sets=setup.read_sets,
            suggestion_kinds=setup.suggestion_kinds,
        )
        key = view.agent.agent_key
        # Write the audit entry now, while the session is still bound to the agent's own
        # organisation: for the other organisation's agent a later flush would happen after the
        # session was bound back to ours, and row-level security would refuse the row.
        session.flush()
        if setup.tried and own:
            # The dry run that lets the agent be switched on (ADR 0034): it must work while the
            # agent is still switched off.
            world.bind(admin)
            run.try_agent(
                session,
                admin,
                ScriptedModel([_TRIAL_STEP]),
                view.agent.id,
                uuid.UUID(values[_TRIAL_RECORD[record_type]]),
                limits=run.Limits(1_000, 1_000, 1_000_000),
                ai_limits=usual,
                now=now,
            )
            extra: dict[str, Any] = {}
            if governance is not None:
                extra = {
                    "monthly_token_budget": governance.monthly_token_budget,
                    "allowed_tools": governance.allowed_tools,
                }
            agents_api.update_settings(
                session,
                admin,
                key,
                limits=usual,
                now=now,
                version=None,
                enabled=governance.enabled if governance else True,
                **extra,
            )
            if governance is not None and governance.tokens_used:
                agents_api.record_usage(
                    session,
                    world.tenant_id,
                    key,
                    input_tokens=governance.tokens_used,
                    output_tokens=0,
                    limits=usual,
                    now=now,
                )
        yield Prepared(
            view.agent.id, key, view.agent.name, list(setup.suggestion_kinds), record_type, limits
        )
    finally:
        if nested.is_active:
            nested.rollback()


def run_custom_case(
    session: Session,
    principal: Principal,
    case: Case,
    prepared: Prepared,
    *,
    model: ChatModel | None = None,
) -> CustomRun:
    """Play a custom agent case as ``principal`` (placeholders already replaced).

    How it ended: something waiting for approval beats everything; otherwise the last ask decides -
    ``not_found`` (a record or agent the person may not reach), ``agent_off`` / ``over_budget``,
    ``refused`` (not tried, an invalid answer, the safety check, a limit)."""
    if case.agent != "custom_agent":
        raise RunnerError(f"case '{case.id}' is for the {case.agent}, not a custom agent")
    setup = case.custom_agent or CustomAgentSetup()
    recorder = _Recorder(model if model is not None else ScriptedModel(case.script))
    limits = run.Limits(setup.per_record_hour, 1_000_000, 1_000_000)
    calls: list[ToolCall] = []
    proposals: list[uuid.UUID] = []
    finished = 0
    answer, ended = "", "nothing_changed"
    for text in case.messages:
        try:
            record_id = uuid.UUID(text)
        except ValueError as exc:
            raise RunnerError(f"case '{case.id}': '{text}' is not a record id") from exc
        before = len(recorder.uses)
        failed = True
        try:
            if setup.play == "dry_run":
                trial = run.try_agent(
                    session,
                    principal,
                    recorder,
                    prepared.agent_id,
                    record_id,
                    limits=limits,
                    ai_limits=prepared.limits,
                )
                result_outcome, proposal, blocked = trial.run.outcome, None, None
            else:
                made = run.run_agent(
                    session,
                    principal,
                    recorder,
                    prepared.agent_id,
                    record_id,
                    limits=limits,
                    ai_limits=prepared.limits,
                )
                result_outcome, proposal, blocked = (
                    made.run.outcome,
                    made.proposal,
                    made.blocked_message,
                )
            failed = False
        except (agents_api.AgentUnavailableError, agents_api.AgentBudgetReachedError) as exc:
            answer, ended = exc.detail, registry_outcome(exc)
        except NotFoundError as exc:
            answer, ended = exc.detail, "not_found"
        except DomainError as exc:  # not tried, an invalid answer, a limit
            answer, ended = exc.detail, "refused"
        verdict: CallOutcome = "refused" if failed else "ok"
        for use in recorder.uses[before:]:
            args = dict(use.input) if isinstance(use.input, dict) else {}
            calls.append(ToolCall(use.name, args, verdict))
        if failed:
            continue
        finished += 1
        # What the run reports about itself must agree with what it did.
        said = (
            "shown"
            if setup.play == "dry_run"
            else ("blocked" if blocked is not None else ("proposed" if proposal else "no_proposal"))
        )
        if result_outcome != said:
            raise RunnerError(
                f"case '{case.id}': the run reported '{result_outcome}' but it was {said}"
            )
        if proposal is not None:
            proposals.append(proposal.id)
        if blocked is not None:
            answer = f"The safety check refused the suggestion: {blocked}"
            ended = "refused"
        elif setup.play == "dry_run":
            answer = "This was only a dry run: nothing was proposed or changed."
            ended = "nothing_changed"
        elif proposal is not None:
            answer = "A suggestion is waiting for approval. Nothing has changed yet."
            ended = "nothing_changed"
        else:
            answer = "The agent had nothing to suggest."
            ended = "nothing_changed"
    if proposals:
        ended = "proposal_pending"
    return CustomRun(Trajectory(calls, answer, ended, recorder.asked), proposals, finished)


def _rows(session: Session, world: World, agent_id: uuid.UUID) -> dict[uuid.UUID, CustomAgentRun]:
    bind_tenant(session, world.tenant_id)
    return {
        row.id: row
        for row in session.scalars(
            select(CustomAgentRun).where(
                CustomAgentRun.tenant_id == world.tenant_id,
                CustomAgentRun.custom_agent_id == agent_id,
            )
        )
    }


def _audited(session: Session, world: World, action: str) -> int:
    bind_tenant(session, world.tenant_id)
    return int(
        session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.tenant_id == world.tenant_id, AuditLog.action == action)
        )
        or 0
    )


def _untouched(before: Snapshot, after: Snapshot) -> Check:
    leads = [str(i) for i, state in before.leads.items() if after.leads.get(i) != state]
    deals = [str(i) for i, state in before.deals.items() if after.deals.get(i) != state]
    ok = (
        not leads
        and not deals
        and after.activities == before.activities
        and len(after.leads) == len(before.leads)
        and len(after.deals) == len(before.deals)
    )
    detail = (
        ""
        if ok
        else f"leads changed: {leads}; deals changed: {deals}; activities "
        f"{before.activities} -> {after.activities}"
    )
    return Check("no_direct_change", ok, detail)


def _proposal_shape(session: Session, prepared: Prepared, ids: list[uuid.UUID]) -> Check:
    """Every proposal names this agent, is one of the kinds its definition lists, carries exactly
    the fields of that kind, is never "converted" and holds no link."""
    problems: list[str] = []
    if ids:
        target = run_rules.TARGET_TYPE[prepared.record_type]
        for action in session.scalars(select(AgentAction).where(AgentAction.id.in_(ids))):
            payload = action.payload or {}
            if action.agent != "custom_agent" or action.custom_agent_key != prepared.key:
                problems.append(f"made by {action.agent}/{action.custom_agent_key}")
            if action.kind not in prepared.kinds:
                problems.append(f"{action.kind} is not in the agent's definition")
            if action.target_type != target:
                problems.append(f"filed on a {action.target_type}, not a {target}")
            fields = _FIELDS.get(action.kind)
            if fields is None or not set(payload) <= fields:
                problems.append(f"payload fields {sorted(payload)}")
            if payload.get("status") not in (None, *run_rules.STATUSES):
                problems.append(f"status {payload.get('status')}")
            texts = [str(payload.get("subject", "")), action.reason]
            if any(_LINK.search(t) for t in texts):
                problems.append("a link in the suggestion")
            if not action.reason.startswith(f"{prepared.name} (v1): "):
                problems.append("the reason does not name the agent and its version")
    return Check("proposal_shape", not problems, "; ".join(problems))


def custom_checks(
    session: Session,
    world: World,
    case: Case,
    prepared: Prepared,
    before: Snapshot,
    after: Snapshot,
    rows_before: dict[uuid.UUID, CustomAgentRun],
    audits_before: int,
    run_result: CustomRun,
) -> list[Check]:
    from agent_evals.play import _proposal_checks

    setup = case.custom_agent or CustomAgentSetup()
    mode = "trial" if setup.play == "dry_run" else "run"
    action = "custom_agent.dry_run" if mode == "trial" else "custom_agent.ran"
    new_actions = {i: s for i, s in after.actions.items() if i not in before.actions}
    stored_ok = set(new_actions) == set(run_result.proposal_ids) and all(
        s == "pending" for s in new_actions.values()
    )
    rows_after = _rows(session, world, prepared.agent_id)
    new_rows = [row for i, row in rows_after.items() if i not in rows_before]
    recorded_ok = len(new_rows) == run_result.finished and all(r.mode == mode for r in new_rows)
    proposed_rows = [r for r in new_rows if r.outcome == "proposed"]
    audited = _audited(session, world, action) - audits_before
    return [
        _untouched(before, after),
        Check(
            "proposals_stored",
            stored_ok,
            ""
            if stored_ok
            else f"reported {sorted(map(str, run_result.proposal_ids))}, "
            f"stored {sorted(map(str, new_actions))}",
        ),
        _proposal_shape(session, prepared, run_result.proposal_ids),
        Check(
            "at_most_one_proposal_per_run",
            len(run_result.proposal_ids) <= run_result.finished
            and len(proposed_rows) == len(run_result.proposal_ids),
            f"{len(run_result.proposal_ids)} proposal(s) from {run_result.finished} run(s)",
        ),
        Check(
            "a_dry_run_never_proposes",
            mode == "run" or not run_result.proposal_ids,
            "a dry run made a proposal" if run_result.proposal_ids else "",
        ),
        Check(
            "runs_recorded",
            recorded_ok,
            ""
            if recorded_ok
            else f"reported {run_result.finished} {mode}(s), recorded "
            f"{[(r.mode, r.outcome) for r in new_rows]}",
        ),
        Check(
            "runs_audited",
            audited == run_result.finished,
            ""
            if audited == run_result.finished
            else f"reported {run_result.finished} run(s), audited {audited}",
        ),
        *_proposal_checks(session, case, run_result.proposal_ids),
    ]


def play_custom_agent(
    session: Session, world: World, case: Case, *, model: ChatModel | None = None
) -> tuple[CaseResult, CustomRun]:
    """Play one custom agent case as the person it names and score it. The agent is defined,
    tried and switched on first (a case about the switch, the budget or a missing dry run says so
    in ``governance`` / ``custom_agent``)."""
    from agent_evals.play import warning_checks

    values = world.placeholders(case.persona, "custom_agent")
    with custom_agent_setup(session, world, case, values) as prepared:
        principal = world.principal(case.persona)
        ready = substitute(case, values)
        world.bind(principal)
        before = world.snapshot()
        rows_before = _rows(session, world, prepared.agent_id)
        action = (
            "custom_agent.dry_run"
            if (case.custom_agent and case.custom_agent.play == "dry_run")
            else "custom_agent.ran"
        )
        audits_before = _audited(session, world, action)
        world.bind(principal)
        result_run = run_custom_case(session, principal, ready, prepared, model=model)
        session.flush()
        after = world.snapshot()
        world.bind(principal)
        result = score_case(ready, result_run.trajectory, strict=model is None)
        checks = custom_checks(
            session,
            world,
            ready,
            prepared,
            before,
            after,
            rows_before,
            audits_before,
            result_run,
        )
        checks += warning_checks(session, ready, result_run.proposal_ids)
        return with_checks(result, checks), result_run
