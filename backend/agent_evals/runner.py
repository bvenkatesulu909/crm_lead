"""Playing a case through the real assistant (BP-10, step EV2).

The assistant under test is the real one - real tools, real permission checks, real database.
Only the language model is replaced by a script. Two small wrappers do the work:

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
from app.modules.assistant import staff_service, staff_tools
from app.modules.assistant.llm import ChatModel, ModelReply, ToolUse
from app.modules.assistant.service import GuardrailError


class RunnerError(RuntimeError):
    """A case can't be played the way it is written (a mistake in the case, not a failure)."""


class ScriptedModel:
    """A model that replays a case's script. Used up, it answers with nothing."""

    available = True

    def __init__(self, steps: list[Step]) -> None:
        self._steps = list(steps)
        self._next = 0
        self._ids = 0

    @property
    def exhausted(self) -> bool:
        return self._next >= len(self._steps)

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
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

    def __init__(self, inner: ChatModel) -> None:
        self._inner = inner
        self._records: list[_Record] = []
        self._pending: dict[str, _Record] = {}

    @property
    def available(self) -> bool:
        return bool(getattr(self._inner, "available", True))

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
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
        if waiting:
            raise RunnerError(
                f"the result of the call(s) to {', '.join(waiting)} was never returned to the "
                "model, so the case ended too early; shorten the script (the assistant allows "
                "three tool rounds per question)"
            )
        return [ToolCall(r.name, r.arguments, r.outcome) for r in self._records if r.outcome]


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
) -> StaffRun:
    """Play a staff-assistant case as ``principal``. The case must already have its
    placeholders replaced. The session stays uncommitted: the caller decides what to keep."""
    if case.agent != "staff_assistant":
        raise RunnerError(f"case '{case.id}' is for the {case.agent}, not the staff assistant")
    if len(case.messages) != 1:
        raise RunnerError(f"case '{case.id}': the staff assistant answers one question at a time")
    recorder = RecordingModel(ScriptedModel(case.script))
    budget = staff_tools.ProposalBudget(expiry_days=expiry_days, pending_limit=pending_limit)
    try:
        answer, _ticket, _links, proposals = staff_service.answer(
            session, principal, recorder, question=case.messages[0], budget=budget
        )
    except GuardrailError as exc:
        # Stopped before any model ran: the person is told why, nothing is called.
        return StaffRun(Trajectory(calls=[], answer=exc.detail, outcome="refused"), [])
    calls = recorder.calls
    outcome = conversation_outcome(calls, len(proposals))
    return StaffRun(Trajectory(calls, answer, outcome), [p.id for p in proposals])
