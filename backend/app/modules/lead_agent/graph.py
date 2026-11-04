"""The lead agent as a small LangGraph graph (ADR 0022, step LA1).

    read ─► decide ─► (nothing to do? stop) ─► propose ─► end

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

DEFAULT_MAX_STEPS = 6  # read, decide, propose need 3; the rest is slack for LA3's extra checks


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
    decide: Callable[[Any], Plan | None]  # facts -> a plan, or None for "nothing to suggest"
    propose: Callable[[Plan], Any]  # stores a PENDING proposal; never changes the lead


class State(TypedDict, total=False):
    facts: Any
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

    def decide(state: State) -> State:
        plan = ports.decide(state["facts"])
        return {"plan": plan} if plan is not None else {"outcome": "no_suggestion"}

    def propose(state: State) -> State:
        plan = state.get("plan")
        if plan is None:  # unreachable through after_decide; refuse rather than guess
            return {"outcome": "no_suggestion"}
        return {"proposal": ports.propose(plan), "outcome": "proposed"}

    def after_read(state: State) -> str:
        return "stop" if state.get("outcome") else "decide"

    def after_decide(state: State) -> str:
        return "stop" if state.get("outcome") else "propose"

    graph = StateGraph(State)
    graph.add_node("read", read)
    graph.add_node("decide", decide)
    graph.add_node("propose", propose)
    graph.add_edge(START, "read")
    graph.add_conditional_edges("read", after_read, {"stop": END, "decide": "decide"})
    graph.add_conditional_edges("decide", after_decide, {"stop": END, "propose": "propose"})
    graph.add_edge("propose", END)
    return graph.compile()


def run(ports: Ports, *, max_steps: int = DEFAULT_MAX_STEPS) -> Result:
    try:
        final: State = build(ports).invoke({}, config={"recursion_limit": max_steps})
    except GraphRecursionError as error:
        raise StepLimitError("The lead agent took too many steps and was stopped.") from error
    return Result(final["outcome"], final.get("plan"), final.get("proposal"))
