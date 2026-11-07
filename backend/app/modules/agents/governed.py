"""The governed model: the one gate in front of every model call (ADR 0016, step AG2).

``governed(model, session, tenant_id, "staff_assistant", limits)`` returns an object that looks
like the model it wraps. Before EVERY ``reply()`` it asks the registry (platform switch, agent on,
month's tokens under the budget); a "no" is raised before the wrapped model is touched, so a
conversation switched off in the middle stops at its next step. It offers the model only the
tools the organisation allows, drops any other tool call the model makes, and adds the call's
tokens to the month's total.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.observability.metrics import AI_DROPPED_TOOL_CALLS, AI_REFUSALS, ai_agent
from app.modules.agents import service
from app.modules.agents.service import (
    AgentBudgetReachedError,
    AgentUnavailableError,
    Limits,
)
from app.modules.assistant.api import ChatModel, ModelReply, TextStream, stream_reply


def _now() -> datetime:
    return datetime.now(UTC)


class GovernedModel:
    def __init__(
        self,
        inner: ChatModel,
        session: Session,
        tenant_id: uuid.UUID,
        agent_key: str,
        limits: Limits,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._inner = inner
        self._session = session
        self._tenant_id = tenant_id
        self._key = agent_key
        self._limits = limits
        self._clock = clock
        # What happened in this conversation, for the caller (and the AG3 notification).
        self.dropped_tools: list[str] = []
        self.warning_due = False

    @property
    def available(self) -> bool:
        return bool(self._inner.available)

    @available.setter
    def available(self, value: bool) -> None:
        self._inner.available = value  # the interface says "settable"; it is the model's flag

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        now, offered, removed = self._before(tools)
        # The model counts its own calls (tokens, time, cost); this says for WHICH agent.
        with ai_agent(self._key):
            reply = self._inner.reply(system=system, messages=messages, tools=offered)
        return self._after(reply, now, removed)

    def stream_reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> TextStream:
        """The same gate around a streamed call (ADR 0023): checked before the first piece,
        counted after the last one."""
        now, offered, removed = self._before(tools)
        pieces = stream_reply(self._inner, system=system, messages=messages, tools=offered)
        while True:
            # The agent label is set around each step, never across a ``yield``: the server may
            # resume a stream in another thread's context, where an open label could not be reset.
            with ai_agent(self._key):
                try:
                    piece = next(pieces)
                except StopIteration as done:
                    reply: ModelReply = done.value
                    break
            yield piece
        return self._after(reply, now, removed)

    def precheck(self) -> None:
        """Ask the registry now (and refuse like a call would), without calling the model - for a
        streamed answer, which must be refused before its first byte, not halfway through."""
        self._before([])

    def _before(
        self, tools: list[dict[str, Any]]
    ) -> tuple[datetime, list[dict[str, Any]], set[str]]:
        now = self._clock()
        try:
            state = service.check_can_call(
                self._session, self._tenant_id, self._key, self._limits, now
            )
        except AgentUnavailableError:
            AI_REFUSALS.labels(agent=self._key, reason=self._reason()).inc()
            raise
        except AgentBudgetReachedError:
            AI_REFUSALS.labels(agent=self._key, reason="budget").inc()
            raise
        allowed = set(state.allowed_tools)
        offered = [tool for tool in tools if tool.get("name") in allowed]
        return now, offered, set(state.agent.tools) - allowed

    def _after(self, reply: ModelReply, now: datetime, removed: set[str]) -> ModelReply:
        result = service.record_usage(
            self._session,
            self._tenant_id,
            self._key,
            input_tokens=int(reply.usage.get("input_tokens", 0) or 0),
            output_tokens=int(reply.usage.get("output_tokens", 0) or 0),
            limits=self._limits,
            now=now,
        )
        self.warning_due = self.warning_due or result.crossed_warning
        # A tool of this agent that the organisation removed is dropped here. A name the agent
        # never had passes through: the feature's own dispatcher refuses it and tells the model.
        kept = [use for use in reply.tool_uses if use.name not in removed]
        for use in reply.tool_uses:
            if use.name in removed:
                self.dropped_tools.append(use.name)
                AI_DROPPED_TOOL_CALLS.labels(agent=self._key).inc()
        if len(kept) == len(reply.tool_uses):
            return reply
        return ModelReply(
            reply.text,
            kept,
            stop_reason="tool_use" if kept else "end_turn",
            usage=reply.usage,
        )

    def _reason(self) -> str:
        return "platform" if self._limits.platform_disabled else "disabled"


def governed(
    model: ChatModel,
    session: Session,
    tenant_id: uuid.UUID,
    agent_key: str,
    limits: Limits,
    *,
    clock: Callable[[], datetime] = _now,
) -> GovernedModel:
    """Wrap ``model`` for one agent of one organisation. Wrapping twice returns the same gate."""
    if isinstance(model, GovernedModel):
        return model
    return GovernedModel(model, session, tenant_id, agent_key, limits, clock)
