"""The lead agent graph (ADR 0022, step LA1): pure tests with scripted functions, no database."""

import re
from pathlib import Path

import pytest

from app.modules.lead_agent import api as lead_agent
from app.modules.lead_agent.graph import build

PLAN = lead_agent.Plan("lead.set_status", "lead", {"status": "qualified"}, "Budget and area given")


class Calls:
    def __init__(self, facts: object | None = "facts", plan: lead_agent.Plan | None = PLAN):
        self.log: list[str] = []
        self.context: dict[str, object] = {}
        self.facts, self.plan = facts, plan

    def ports(self) -> lead_agent.Ports:
        def read() -> object | None:
            self.log.append("read")
            return self.facts

        def web_evidence(facts: object) -> list[str]:
            self.log.append("web_check")
            return ["evidence"]

        def duplicates(facts: object) -> int:
            self.log.append("duplicate_check")
            return 2

        def decide(facts: object, context: dict[str, object]) -> lead_agent.Plan | None:
            self.log.append("decide")
            self.context = context
            return self.plan

        def propose(plan: lead_agent.Plan) -> str:
            self.log.append("propose")
            return "proposal-1"

        return lead_agent.Ports(read, web_evidence, duplicates, decide, propose)


def test_it_reads_decides_then_proposes_in_that_order() -> None:
    calls = Calls()
    result = lead_agent.run(calls.ports())
    assert calls.log == ["read", "web_check", "duplicate_check", "decide", "propose"]
    assert (result.outcome, result.plan, result.proposal) == ("proposed", PLAN, "proposal-1")


def test_the_two_read_only_looks_reach_the_decision() -> None:
    calls = Calls()
    lead_agent.run(calls.ports())
    assert calls.context == {"web_evidence": ["evidence"], "other_leads_with_same_contact": 2}


def test_a_lead_the_asker_cannot_see_stops_before_any_decision() -> None:
    calls = Calls(facts=None)
    result = lead_agent.run(calls.ports())
    assert calls.log == ["read"]
    assert result.outcome == "lead_not_found" and result.proposal is None


def test_nothing_to_suggest_proposes_nothing() -> None:
    calls = Calls(plan=None)
    result = lead_agent.run(calls.ports())
    assert calls.log == ["read", "web_check", "duplicate_check", "decide"]
    assert result.outcome == "no_suggestion" and result.proposal is None


def test_the_step_limit_stops_it_before_it_can_propose() -> None:
    calls = Calls()
    with pytest.raises(lead_agent.StepLimitError):
        lead_agent.run(calls.ports(), max_steps=4)
    assert "propose" not in calls.log


def test_an_error_in_a_step_is_not_swallowed() -> None:
    calls = Calls()
    ports = calls.ports()

    def refuse(plan: lead_agent.Plan) -> str:
        raise RuntimeError("blocked by the Sentinel")

    with pytest.raises(RuntimeError):
        lead_agent.run(
            lead_agent.Ports(ports.read, ports.web_evidence, ports.duplicates, ports.decide, refuse)
        )


def test_the_graph_has_exactly_five_steps_and_none_that_writes() -> None:
    nodes = set(build(Calls().ports()).get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"read", "web_check", "duplicate_check", "decide", "propose"}


def test_langgraph_is_imported_by_the_lead_agent_module_only() -> None:
    app = Path(__file__).resolve().parents[1] / "app"
    pattern = re.compile(r"^\s*(from|import)\s+langgraph", re.M)
    users = {
        path.relative_to(app).parts[:3]
        for path in app.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    }
    assert users == {("modules", "lead_agent", "graph.py")}
