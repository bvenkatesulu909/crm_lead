"""The lead agent as a small LangGraph graph (ADR 0022, step LA1).

    read ─► web evidence ─► duplicate check ─► decide ─► (nothing to do? stop) ─► propose ─► end

The graph itself owns no data and no model: it is given three functions (``Ports``) and only decides
the ORDER, the stopping and the step limit. The last step can only call ``propose`` - there is no
node that writes to the CRM, so the agent can suggest and never act. LangGraph is imported here and
nowhere else (a guard test checks that); removing it means deleting this folder.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from app.core.errors import DomainError

DEFAULT_MAX_STEPS = 8  # the five steps need 5; the rest is slack


class StepLimitError(DomainError):
    status_code = 422
    code = "lead_agent_step_limit"


@dataclass(frozen=True)
class Plan:
    """One suggested change, exactly what the approvals module's ``propose`` takes."""

    kind: str
    target_type: str
    payload: dict[str, Any]
    reason: str


@dataclass(frozen=True)
class Ports:
    """What the graph may use. Each is a plain function, so tests give scripted ones and the real
    wiring (LA2) gives ones that go through the module APIs, the registry and the Sentinel."""

    read: Callable[[], Any | None]  # the lead's facts, or None if the asker may not see it
    # Two READ-ONLY looks at the lead (LA3): the web evidence already on file and how many other
    # leads share its contact details. Each returns plain data for the model to read.
    web_evidence: Callable[[Any], Any]
    duplicates: Callable[[Any], Any]
    # (facts, extra context) -> a plan, or None for "nothing to suggest"
    decide: Callable[[Any, dict[str, Any]], Plan | None]
    propose: Callable[[Plan], Any]  # stores a PENDING proposal; never changes the lead


class State(TypedDict, total=False):
    facts: Any
    context: dict[str, Any]
    plan: Plan | None
    proposal: Any
    outcome: str


@dataclass(frozen=True)
class Result:
    outcome: str  # "proposed" | "no_suggestion" | "lead_not_found"
    plan: Plan | None
    proposal: Any


def build(ports: Ports) -> Any:
    def read(state: State) -> State:
        facts = ports.read()
        return {"facts": facts} if facts is not None else {"outcome": "lead_not_found"}

    def web_check(state: State) -> State:
        return {"context": {"web_evidence": ports.web_evidence(state["facts"])}}

    def duplicate_check(state: State) -> State:
        context = {
            **state["context"],
            "other_leads_with_same_contact": ports.duplicates(state["facts"]),
        }
        return {"context": context}

    def decide(state: State) -> State:
        plan = ports.decide(state["facts"], state["context"])
        return {"plan": plan} if plan is not None else {"outcome": "no_suggestion"}

    def propose(state: State) -> State:
        plan = state.get("plan")
        if plan is None:  # unreachable through after_decide; refuse rather than guess
            return {"outcome": "no_suggestion"}
        return {"proposal": ports.propose(plan), "outcome": "proposed"}

    def after_read(state: State) -> str:
        return "stop" if state.get("outcome") else "web_check"

    def after_decide(state: State) -> str:
        return "stop" if state.get("outcome") else "propose"

    graph = StateGraph(State)
    graph.add_node("read", read)
    graph.add_node("web_check", web_check)
    graph.add_node("duplicate_check", duplicate_check)
    graph.add_node("decide", decide)
    graph.add_node("propose", propose)
    graph.add_edge(START, "read")
    graph.add_conditional_edges("read", after_read, {"stop": END, "web_check": "web_check"})
    graph.add_edge("web_check", "duplicate_check")
    graph.add_edge("duplicate_check", "decide")
    graph.add_conditional_edges("decide", after_decide, {"stop": END, "propose": "propose"})
    graph.add_edge("propose", END)
    return graph.compile()


def run(ports: Ports, *, max_steps: int = DEFAULT_MAX_STEPS) -> Result:
    try:
        final: State = build(ports).invoke({}, config={"recursion_limit": max_steps})
    except GraphRecursionError as error:
        raise StepLimitError("The lead agent took too many steps and was stopped.") from error
    return Result(final["outcome"], final.get("plan"), final.get("proposal"))
