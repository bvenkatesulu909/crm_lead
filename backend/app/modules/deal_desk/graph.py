"""The deal desk as a small LangGraph graph (ADR 0024, step DD2).

                ┌─► pricing ──┐
    read ───────┼─► account ──┼──► desk lead ──► propose ──► end
     (stop if   └─► momentum ─┘     (stop if no reviewer answered)
      not found)

The three reviewers run in the same step, in parallel. The graph owns no data and no model: it is
given functions (``Ports``) and only decides the order, the fan-out, the join and the step limit.
A reviewer's port must be safe to run in a thread of its own (no database work): the service gives
it the model call only and keeps the bookkeeping for afterwards. There is no node that writes to
the CRM: the last step can only call ``propose``, which stores a PENDING proposal.
LangGraph is imported here and in the lead agent's graph only (a guard test checks that).
"""

import operator
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from app.core.errors import DomainError
from app.modules.deal_desk.review import Brief, Finding, TaskPlan
from app.modules.deal_desk.rules import REVIEWERS, DealSheets, FactSheet, Reviewer

DEFAULT_MAX_STEPS = (
    8  # read, three reviewers in one step, lead, propose: 4 steps; the rest is slack
)


class StepLimitError(DomainError):
    status_code = 422
    code = "deal_desk_step_limit"


@dataclass(frozen=True)
class ReviewerAnswer:
    reviewer: Reviewer
    findings: list[Finding] | None  # None: the reviewer's answer was refused
    usage: dict[str, int] = field(default_factory=dict)
    reply: Any = None  # the raw reply, for the bookkeeping after the join


@dataclass(frozen=True)
class Ports:
    read: Callable[[], DealSheets | None]
    review: Callable[[Reviewer, FactSheet], ReviewerAnswer]  # thread-safe: no database work
    lead: Callable[[list[Finding], list[Reviewer]], Brief]
    propose: Callable[[TaskPlan], Any]


class State(TypedDict, total=False):
    sheets: DealSheets
    answers: Annotated[list[ReviewerAnswer], operator.add]
    brief: Brief
    proposals: list[Any]
    outcome: str


@dataclass(frozen=True)
class Result:
    outcome: str  # "reviewed" | "deal_not_found" | "no_reviewer_answered"
    answers: list[ReviewerAnswer]
    brief: Brief | None
    proposals: list[Any]


def build(ports: Ports) -> Any:
    def read(state: State) -> State:
        sheets = ports.read()
        return {"sheets": sheets} if sheets is not None else {"outcome": "deal_not_found"}

    def reviewer(name: Reviewer) -> Any:  # LangGraph's node type is narrower than Callable
        def node(state: State) -> State:
            return {"answers": [ports.review(name, state["sheets"].sheet(name))]}

        return node

    def desk_lead(state: State) -> State:
        answers = sorted(state.get("answers", []), key=lambda a: REVIEWERS.index(a.reviewer))
        answered = [a for a in answers if a.findings is not None]
        if not answered:
            return {"outcome": "no_reviewer_answered"}
        findings = [f for a in answered for f in (a.findings or [])]
        silent = [a.reviewer for a in answers if a.findings is None]
        return {"brief": ports.lead(findings, silent)}

    def propose(state: State) -> State:
        brief = state.get("brief")
        made = [ports.propose(task) for task in brief.tasks] if brief else []
        return {"proposals": made, "outcome": "reviewed"}

    def after_read(state: State) -> list[str] | str:
        return "stop" if state.get("outcome") else list(REVIEWERS)

    def after_lead(state: State) -> str:
        return "stop" if state.get("outcome") else "propose"

    graph = StateGraph(State)
    graph.add_node("read", read)
    for name in REVIEWERS:
        graph.add_node(name, reviewer(name))
    graph.add_node("desk_lead", desk_lead)
    graph.add_node("propose", propose)
    graph.add_edge(START, "read")
    graph.add_conditional_edges(
        "read", after_read, {"stop": END, **{name: name for name in REVIEWERS}}
    )
    # The join: the desk lead runs once, after ALL three reviewers.
    graph.add_edge(list(REVIEWERS), "desk_lead")
    graph.add_conditional_edges("desk_lead", after_lead, {"stop": END, "propose": "propose"})
    graph.add_edge("propose", END)
    return graph.compile()


def run(ports: Ports, *, max_steps: int = DEFAULT_MAX_STEPS) -> Result:
    try:
        final: State = build(ports).invoke({}, config={"recursion_limit": max_steps})
    except GraphRecursionError as error:
        raise StepLimitError("The deal desk took too many steps and was stopped.") from error
    answers = sorted(final.get("answers", []), key=lambda a: REVIEWERS.index(a.reviewer))
    return Result(final["outcome"], answers, final.get("brief"), final.get("proposals", []))
