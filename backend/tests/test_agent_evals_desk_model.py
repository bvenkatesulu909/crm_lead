"""The deal desk's scripted model (ADR 0024, step DD5): replies are picked by the role the prompt
names, never by the order of the calls - the three reviewers run at the same time."""

import threading

import pytest

from agent_evals.cases import ScriptedCall, Step
from agent_evals.desk import DeskRecorder, DeskScriptedModel, role_of
from agent_evals.runner import RunnerError
from app.modules.deal_desk import review
from app.modules.deal_desk.rules import Fact, FactSheet


def sheet(name: str) -> FactSheet:
    import uuid

    return FactSheet(name, (Fact("x", "A fact.", "opportunity", uuid.uuid4()),))  # type: ignore[arg-type]


def step(role: str, marker: str) -> Step:
    return Step(role=role, calls=[ScriptedCall(name="submit_findings", arguments={"m": marker})])


def test_the_role_is_read_from_our_own_prompts() -> None:
    for name in ("pricing", "account", "momentum"):
        assert role_of(review.reviewer_prompt(sheet(name))) == name
    assert role_of(review.lead_prompt([], [])) == "lead"
    with pytest.raises(RunnerError):
        role_of("Some other prompt.")


def test_each_role_gets_its_own_steps_in_any_order() -> None:
    model = DeskScriptedModel(
        [step("pricing", "p1"), step("momentum", "m1"), step("pricing", "p2"), step("lead", "l1")]
    )

    def ask(name: str) -> object:
        if name == "lead":
            system = review.lead_prompt([], [])
        else:
            system = review.reviewer_prompt(sheet(name))
        reply = model.reply(system=system, messages=[], tools=[])
        return reply.tool_uses[0].input["m"] if reply.tool_uses else None

    assert ask("lead") == "l1"
    assert ask("momentum") == "m1"
    assert ask("pricing") == "p1"
    assert ask("pricing") == "p2"
    assert ask("pricing") is None  # used up: answers with nothing
    assert ask("account") is None  # no steps at all


def test_a_step_without_a_role_is_a_mistake_in_the_case() -> None:
    with pytest.raises(RunnerError):
        DeskScriptedModel([Step(say="hello")])


def test_the_recorder_keeps_calls_per_role_from_several_threads() -> None:
    recorder = DeskRecorder(
        DeskScriptedModel([step(name, name) for name in ("pricing", "account", "momentum")])
    )
    threads = [
        threading.Thread(
            target=recorder.reply,
            kwargs={"system": review.reviewer_prompt(sheet(name)), "messages": [], "tools": []},
        )
        for name in ("momentum", "account", "pricing")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    taken = recorder.take()
    assert recorder.asked == 3
    assert {role: [u.input["m"] for u in uses] for role, uses in taken.items() if uses} == {
        "pricing": ["pricing"],
        "account": ["account"],
        "momentum": ["momentum"],
    }
    assert all(not uses for uses in recorder.take().values())  # forgotten after a take
