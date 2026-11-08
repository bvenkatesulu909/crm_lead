"""Playing a case through the real assistant (BP-10, steps EV2 and EV3).

The assistant under test is the real one - real tools, real permission checks, real database.
Only the language model is replaced by a script. Three agents can be played: the staff
assistant, the customer portal assistant and the public website chat. Two small wrappers do
the work:

* ``ScriptedModel`` replays the case's replies (some words and/or tool calls) in order;
* ``RecordingModel`` notes every tool call and how the CRM answered it. It reads that from the
  tool results the assistant feeds back to the model, so it needs no change to the assistant.

What the CRM answered is classified as ``ok``, ``not_found`` (a record the person may not see)
or ``refused`` (invalid arguments, an unknown tool, a limit, a denied permission).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from agent_evals.cases import CallOutcome, Case, Step
from agent_evals.scoring import ToolCall, Trajectory
from app.core.auth.principal import Principal
from app.core.config import Settings
from app.core.errors import DomainError
from app.modules.agents import api as agents_api
from app.modules.assistant import service as portal_service
from app.modules.assistant import staff_conversations, staff_service, staff_tools
from app.modules.assistant.llm import ChatModel, ModelReply, ToolUse
from app.modules.assistant.service import GuardrailError
from app.modules.lead_agent import api as lead_agent_api
from app.modules.public_chat import service as public_chat_service
from app.modules.public_chat.rules import RESTING_REPLY
from app.modules.public_chat.schemas import PublicChatRequest
from app.modules.qualifier import api as qualifier_api


class RunnerError(RuntimeError):
    """A case can't be played the way it is written (a mistake in the case, not a failure)."""


class ScriptedModel:
    """A model that replays a case's script. Used up, it answers with nothing."""

    available = True

    def __init__(self, steps: list[Step]) -> None:
        self._steps = list(steps)
        self._next = 0
        self._ids = 0
        self.asked = 0  # how often the model was asked, scripted or not

    @property
    def exhausted(self) -> bool:
        return self._next >= len(self._steps)

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        self.asked += 1
        if self.exhausted:
            return ModelReply("")
        step = self._steps[self._next]
        self._next += 1
        uses = []
        for call in step.calls:
            self._ids += 1
            uses.append(ToolUse(f"scripted-{self._ids}", call.name, dict(call.arguments)))
        return ModelReply(step.say, uses, stop_reason="tool_use" if uses else "end_turn")


def classify_result(content: str, is_error: bool) -> CallOutcome:
    """How the CRM answered one tool call, from the tool result the assistant sent back."""
    if not is_error:
        return "ok"
    return "not_found" if "not found" in content.casefold() else "refused"


@dataclass
class _Record:
    id: str
    name: str
    arguments: dict[str, Any]
    outcome: CallOutcome | None = None


class RecordingModel:
    """Wraps a model and records its tool calls with the CRM's answers."""

    def __init__(self, inner: ChatModel, *, drop_unanswered: bool = False) -> None:
        self._inner = inner
        self.available = bool(getattr(inner, "available", True))
        # With the agent registry in front (ADR 0016) a tool call the organisation did not allow
        # is removed before it reaches the CRM, so it never gets an answer: it is not a call.
        self._drop_unanswered = drop_unanswered
        self.asked = 0
        self._records: list[_Record] = []
        self._pending: dict[str, _Record] = {}

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        self.asked += 1
        self._resolve(messages)
        reply = self._inner.reply(system=system, messages=messages, tools=tools)
        for use in reply.tool_uses:
            record = _Record(
                use.id, use.name, dict(use.input) if isinstance(use.input, dict) else {}
            )
            self._records.append(record)
            self._pending[use.id] = record
        return reply

    def _resolve(self, messages: list[dict[str, Any]]) -> None:
        content = messages[-1].get("content") if messages else None
        if not isinstance(content, list):
            return
        for part in content:
            record = self._pending.pop(str(part.get("tool_use_id")), None)
            if part.get("type") == "tool_result" and record is not None:
                record.outcome = classify_result(
                    str(part.get("content", "")), bool(part.get("is_error"))
                )

    @property
    def calls(self) -> list[ToolCall]:
        waiting = [r.name for r in self._records if r.outcome is None]
        if waiting and not self._drop_unanswered:
            raise RunnerError(
                f"the result of the call(s) to {', '.join(waiting)} was never returned to the "
                "model, so the case ended too early; shorten the script (the assistant allows "
                "three tool rounds per question)"
            )
        return [ToolCall(r.name, r.arguments, r.outcome) for r in self._records if r.outcome]


def registry_outcome(error: Exception) -> str:
    """The outcome word for a call the agent registry refused (ADR 0016)."""
    return "over_budget" if isinstance(error, agents_api.AgentBudgetReachedError) else "agent_off"


def conversation_outcome(calls: list[ToolCall], proposals: int) -> str:
    """How a conversation ended, in the words of a case's ``expect.outcome``.

    Something waiting for approval beats everything; otherwise a record the person may not see
    is "not_found", any other failed call is "nothing_changed", and no failure is "answered".
    (A question stopped by the guardrails before the model is "refused" - see the runner.)"""
    if proposals > 0:
        return "proposal_pending"
    failed = [c for c in calls if c.outcome != "ok"]
    if any(c.outcome == "not_found" for c in failed):
        return "not_found"
    return "nothing_changed" if failed else "answered"


@dataclass(frozen=True)
class StaffRun:
    trajectory: Trajectory
    proposal_ids: list[uuid.UUID]


def run_staff_case(
    session: Session,
    principal: Principal,
    case: Case,
    *,
    expiry_days: int = 7,
    pending_limit: int = 20,
    model: ChatModel | None = None,
    limits: agents_api.Limits | None = None,
    settings: Settings | None = None,
) -> StaffRun:
    """Play a staff-assistant case as ``principal``. The case must already have its
    placeholders replaced. The session stays uncommitted: the caller decides what to keep.
    ``model`` is a real model; without one the case's script plays."""
    if case.agent != "staff_assistant":
        raise RunnerError(f"case '{case.id}' is for the {case.agent}, not the staff assistant")
    recorder = RecordingModel(
        model if model is not None else ScriptedModel(case.script),
        drop_unanswered=case.governance is not None,
    )
    try:
        if len(case.messages) == 1 and case.mode == "text":
            budget = staff_tools.ProposalBudget(
                expiry_days=expiry_days, pending_limit=pending_limit, settings=settings
            )
            answer, _ticket, _links, proposals = staff_service.answer(
                session,
                principal,
                recorder,
                question=case.messages[0],
                budget=budget,
                limits=limits,
            )
        else:
            answer, proposals = _staff_conversation(
                session, principal, case, recorder, expiry_days, pending_limit, limits, settings
            )
    except GuardrailError as exc:
        # Stopped before any model ran: the person is told why, nothing is called.
        return StaffRun(Trajectory([], exc.detail, "refused", recorder.asked), [])
    except (agents_api.AgentUnavailableError, agents_api.AgentBudgetReachedError) as exc:
        # Stopped by the agent registry (ADR 0016): the model is never reached.
        return StaffRun(Trajectory([], exc.detail, registry_outcome(exc), recorder.asked), [])
    calls = recorder.calls
    outcome = conversation_outcome(calls, len(proposals))
    return StaffRun(Trajectory(calls, answer, outcome, recorder.asked), [p.id for p in proposals])


def _staff_conversation(
    session: Session,
    principal: Principal,
    case: Case,
    model: ChatModel,
    expiry_days: int,
    pending_limit: int,
    limits: agents_api.Limits | None,
    settings: Settings | None = None,
) -> tuple[str, list[staff_tools.ProposalRef]]:
    """Several questions of one remembered conversation, each answer streamed (ADR 0023) - the
    path of ``POST /assistant/conversations/{id}/turns``. Returns the last answer and every
    proposal of the conversation."""
    conversation = staff_conversations.start(session, principal)
    answer = ""
    proposals: list[staff_tools.ProposalRef] = []
    for text in case.messages:
        # A new budget per question, as the API gives each turn.
        budget = staff_tools.ProposalBudget(
            expiry_days=expiry_days, pending_limit=pending_limit, settings=settings
        )
        prepared = staff_service.prepare(
            session,
            principal,
            model,
            question=text,
            history=staff_conversations.history(session, conversation),
            voice=case.mode == "voice",
            budget=budget,
            limits=limits,
            precheck=True,
        )
        finished: staff_service.Finished | None = None
        for event in staff_service.run(session, principal, prepared, stream=True):
            if isinstance(event, staff_service.Finished):
                finished = event
        if finished is None:  # pragma: no cover - run() always finishes
            raise RunnerError(f"case '{case.id}': the answer did not finish")
        staff_conversations.record(
            session, conversation, question=prepared.question, answer=finished.answer
        )
        answer = finished.answer
        proposals.extend(finished.proposals)
    return answer, proposals


# --- the customer portal assistant (EV3) ----------------------------------------------------------


@dataclass(frozen=True)
class PortalRun:
    trajectory: Trajectory
    # Tickets the assistant prepared for the customer to confirm (nothing is created yet).
    pending_actions: int


def run_portal_case(
    session: Session,
    principal: Principal,
    case: Case,
    *,
    messages_per_hour: int = 1000,
    max_tool_rounds: int = 6,
    model: ChatModel | None = None,
    limits: agents_api.Limits | None = None,
) -> PortalRun:
    """Play a portal-assistant case as the customer ``principal``. Several messages continue
    one conversation. Placeholders must already be replaced."""
    if case.agent != "portal_assistant":
        raise RunnerError(f"case '{case.id}' is for the {case.agent}, not the portal_assistant")
    recorder = RecordingModel(
        model if model is not None else ScriptedModel(case.script),
        drop_unanswered=case.governance is not None,
    )
    conversation_id: uuid.UUID | None = None
    answer = ""
    pending = 0
    for text in case.messages:
        try:
            conversation = portal_service.send_message(
                session,
                principal,
                recorder,
                conversation_id=conversation_id,
                text=text,
                messages_per_hour=messages_per_hour,
                max_tool_rounds=max_tool_rounds,
                limits=limits,
            )
        except GuardrailError as exc:
            return PortalRun(Trajectory(recorder.calls, exc.detail, "refused", recorder.asked), 0)
        except (agents_api.AgentUnavailableError, agents_api.AgentBudgetReachedError) as exc:
            return PortalRun(
                Trajectory(recorder.calls, exc.detail, registry_outcome(exc), recorder.asked), 0
            )
        conversation_id = conversation.id
        answer = conversation.messages[-1].content if conversation.messages else ""
        pending = sum(1 for action in conversation.actions if action.status == "pending")
    calls = recorder.calls
    return PortalRun(
        Trajectory(calls, answer, conversation_outcome(calls, pending), recorder.asked), pending
    )


# --- the public website chat (EV3) ----------------------------------------------------------------


def public_chat_outcome(calls: list[ToolCall], *, lead_saved: bool) -> str:
    """A saved lead beats everything; otherwise like any other conversation (no proposals here)."""
    return "lead_saved" if lead_saved else conversation_outcome(calls, 0)


@dataclass(frozen=True)
class PublicRun:
    trajectory: Trajectory
    lead_saved: bool


def run_public_chat_case(
    session: Session,
    settings: Settings,
    case: Case,
    *,
    visitor_ip: str = "203.0.113.7",
    model: ChatModel | None = None,
) -> PublicRun:
    """Play a public-chat case as an anonymous visitor: each message continues one conversation
    (the token is kept like the website does). ``settings`` must switch the chat on for the
    organisation of the test world."""
    if case.agent != "public_chat":
        raise RunnerError(f"case '{case.id}' is for the {case.agent}, not the public_chat")
    recorder = RecordingModel(
        model if model is not None else ScriptedModel(case.script),
        drop_unanswered=case.governance is not None,
    )
    token: str | None = None
    answer = ""
    lead_saved = False
    for text in case.messages:
        try:
            reply = public_chat_service.handle_message(
                session,
                settings,
                recorder,
                PublicChatRequest(token=token, message=text),
                visitor_ip=visitor_ip,
            )
        except public_chat_service.MessageRefusedError as exc:
            # Stopped by the guardrails or the honeypot before any model ran.
            return PublicRun(
                Trajectory(recorder.calls, exc.detail, "refused", recorder.asked), lead_saved
            )
        token, answer, lead_saved = reply.token, reply.reply, reply.lead_saved
    calls = recorder.calls
    outcome = public_chat_outcome(calls, lead_saved=lead_saved)
    if answer == RESTING_REPLY:
        outcome = "agent_off"  # the registry stopped it (ADR 0016); the visitor sees one sentence
    return PublicRun(Trajectory(calls, answer, outcome, recorder.asked), lead_saved)


# --- the Qualifier (QA5) ------------------------------------------------------------------------


class _UseRecorder:
    """Wraps a model and keeps the tool calls it made. The Qualifier's one tool is never answered
    in a conversation (nothing is fed back), so the outcome of a call is decided afterwards from
    what the assessment did with it (see ``run_qualifier_case``)."""

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
class QualifierRun:
    trajectory: Trajectory
    proposal_ids: list[uuid.UUID]
    # Assessments the Qualifier stored (one per successful ask).
    assessments: int


def run_qualifier_case(
    session: Session,
    principal: Principal,
    case: Case,
    *,
    model: ChatModel | None = None,
    limits: agents_api.Limits | None = None,
    qualifier_limits: qualifier_api.Limits | None = None,
) -> QualifierRun:
    """Play a Qualifier case as ``principal``: each message is the id of a lead to assess, in
    order, through the REAL ``assess_lead`` (permission, procedure, record-level read, limits,
    registry, strict check, Sentinel, approvals). Placeholders must already be replaced.

    How it ended: something waiting for approval beats everything; otherwise the last ask decides
    - ``not_found`` (a lead the person may not read), ``agent_off`` / ``over_budget`` (registry),
    ``refused`` (invalid answer, limit, or the safety check), ``nothing_changed`` (no procedure,
    or nothing worth proposing)."""
    if case.agent != "qualifier":
        raise RunnerError(f"case '{case.id}' is for the {case.agent}, not the qualifier")
    recorder = _UseRecorder(model if model is not None else ScriptedModel(case.script))
    # The cases are not about the rate limits (a case that is can say so with two messages for
    # one lead: the per-lead limit is the real one); the development data may hold assessments.
    asking = qualifier_limits or qualifier_api.Limits(
        per_lead_hour=1, per_user_hour=100_000, per_tenant_day=1_000_000
    )
    calls: list[ToolCall] = []
    proposals: list[uuid.UUID] = []
    assessments = 0
    answer = ""
    ended = "nothing_changed"
    for text in case.messages:
        try:
            lead_id = uuid.UUID(text)
        except ValueError as exc:
            raise RunnerError(f"case '{case.id}': '{text}' is not a lead id") from exc
        before = len(recorder.uses)
        failed: str | None = None
        try:
            result = qualifier_api.assess_lead(
                session, principal, recorder, lead_id, limits=asking, ai_limits=limits
            )
        except (agents_api.AgentUnavailableError, agents_api.AgentBudgetReachedError) as exc:
            answer, ended, failed = exc.detail, registry_outcome(exc), "agent"
        except qualifier_api.LeadNotFoundError as exc:
            answer, ended, failed = exc.detail, "not_found", "lead"
        except qualifier_api.NoActiveProcedureError as exc:
            answer, ended, failed = exc.detail, "nothing_changed", "procedure"
        except (qualifier_api.AssessmentInvalidError, qualifier_api.RateLimitedError) as exc:
            answer, ended, failed = exc.detail, "refused", "answer"
        except DomainError as exc:  # for example a permission refusal
            answer, ended, failed = exc.detail, "refused", "other"
        # A call the Qualifier accepted is "ok"; one it refused (a wrong answer, or a tool the
        # organisation took away) is "refused". A call that never got as far is still listed.
        verdict: CallOutcome = "ok" if failed is None else "refused"
        for use in recorder.uses[before:]:
            args = dict(use.input) if isinstance(use.input, dict) else {}
            calls.append(ToolCall(use.name, args, verdict))
        if failed is not None:
            continue
        assessments += 1
        if result.proposal is not None:
            proposals.append(result.proposal.id)
        if result.blocked_message is not None:
            answer = f"The safety check refused the proposal: {result.blocked_message}"
            ended = "refused"
        else:
            decision = result.assessment.decision
            waiting = (
                "A proposal is waiting for approval."
                if result.proposal
                else "Nothing needed to be proposed."
            )
            answer = f"Decision: {decision}. {waiting} " + " ".join(result.assessment.reasons)
            ended = "nothing_changed"
    if proposals:
        ended = "proposal_pending"
    return QualifierRun(Trajectory(calls, answer, ended, recorder.asked), proposals, assessments)


# --- the lead agent (ADR 0022, step LA5) --------------------------------------------------------


@dataclass(frozen=True)
class LeadAgentRun:
    trajectory: Trajectory
    proposal_ids: list[uuid.UUID]
    # Runs the agent finished (each one is audited as "lead_agent.ran").
    runs: int


def run_lead_agent_case(
    session: Session,
    principal: Principal,
    case: Case,
    *,
    model: ChatModel | None = None,
    limits: agents_api.Limits | None = None,
    agent_limits: lead_agent_api.Limits | None = None,
) -> LeadAgentRun:
    """Play a lead-agent case as ``principal``: each message is the id of a lead to look at, in
    order, through the REAL ``run_lead_agent`` (permission, record-level read, limits, registry,
    the graph and its read-only looks, strict check, Sentinel, approvals). Placeholders must
    already be replaced.

    How it ended: something waiting for approval beats everything; otherwise the last ask decides
    - ``not_found``, ``agent_off`` / ``over_budget``, ``refused`` (invalid answer, limit, the
    safety check or a permission), ``nothing_changed`` (nothing worth suggesting, or no
    qualification steps written)."""
    if case.agent != "lead_agent":
        raise RunnerError(f"case '{case.id}' is for the {case.agent}, not the lead agent")
    recorder = _UseRecorder(model if model is not None else ScriptedModel(case.script))
    # As for the Qualifier: the per-lead limit is the real one; the daily one is not the subject.
    asking = agent_limits or lead_agent_api.Limits(per_lead_hour=1, per_tenant_day=1_000_000)
    calls: list[ToolCall] = []
    proposals: list[uuid.UUID] = []
    runs = 0
    answer = ""
    ended = "nothing_changed"
    for text in case.messages:
        try:
            lead_id = uuid.UUID(text)
        except ValueError as exc:
            raise RunnerError(f"case '{case.id}': '{text}' is not a lead id") from exc
        before = len(recorder.uses)
        failed = True
        try:
            result = lead_agent_api.run_lead_agent(
                session, principal, recorder, lead_id, limits=asking, ai_limits=limits
            )
            failed = False
        except (agents_api.AgentUnavailableError, agents_api.AgentBudgetReachedError) as exc:
            answer, ended = exc.detail, registry_outcome(exc)
        except lead_agent_api.LeadNotFoundError as exc:
            answer, ended = exc.detail, "not_found"
        except qualifier_api.NoActiveProcedureError as exc:
            answer, ended = exc.detail, "nothing_changed"  # no steps written: nothing to judge by
        except DomainError as exc:  # an invalid answer, a limit, a permission
            answer, ended = exc.detail, "refused"
        verdict: CallOutcome = "refused" if failed else "ok"
        for use in recorder.uses[before:]:
            args = dict(use.input) if isinstance(use.input, dict) else {}
            calls.append(ToolCall(use.name, args, verdict))
        if failed:
            continue
        runs += 1
        if result.proposal is not None:
            proposals.append(result.proposal.id)
        if result.blocked_message is not None:
            answer = f"The safety check refused the suggestion: {result.blocked_message}"
            ended = "refused"
        elif result.proposal is not None:
            answer = "A suggestion is waiting for approval. Nothing has changed yet."
            ended = "nothing_changed"
        else:
            answer, ended = "The lead agent suggests no change.", "nothing_changed"
    if proposals:
        ended = "proposal_pending"
    return LeadAgentRun(Trajectory(calls, answer, ended, recorder.asked), proposals, runs)
