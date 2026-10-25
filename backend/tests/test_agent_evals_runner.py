"""Agent evaluation harness (BP-10, step EV2): scripted model, recorder and outcome rules.

The runner plays a case's script through the real assistant. Two small wrappers do the work: a
scripted model that replays the case's replies, and a recorder that notes every tool call and how
the CRM answered it (read from the tool results the assistant feeds back). Pure Python here;
the real assistant and database are exercised in tests/db/test_agent_evals_staff.py.
"""

from typing import Any

import pytest

from agent_evals.cases import Step
from agent_evals.runner import (
    RecordingModel,
    RunnerError,
    ScriptedModel,
    classify_result,
    conversation_outcome,
)
from agent_evals.scoring import ToolCall


def steps(*raw: dict[str, Any]) -> list[Step]:
    return [Step.model_validate(item) for item in raw]


def results(*parts: tuple[str, bool, str]) -> list[dict[str, Any]]:
    """The user message an assistant sends back after tool calls."""
    return [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": use_id, "content": text, "is_error": error}
                for use_id, error, text in parts
            ],
        }
    ]


def ask(model: Any, messages: list[dict[str, Any]] | None = None) -> Any:
    return model.reply(
        system="s", messages=messages or [{"role": "user", "content": "q"}], tools=[]
    )


# --- the scripted model ---------------------------------------------------------------------------


def test_it_replays_the_script_in_order() -> None:
    model = ScriptedModel(
        steps(
            {"calls": [{"name": "search_leads", "arguments": {"q": "asha"}}]},
            {"say": "Here you go."},
        )
    )
    first = ask(model)
    assert first.text == "" and first.stop_reason == "tool_use"
    [use] = first.tool_uses
    assert (use.name, use.input) == ("search_leads", {"q": "asha"})
    second = ask(model)
    assert second.text == "Here you go." and second.tool_uses == []


def test_every_scripted_call_gets_its_own_id() -> None:
    model = ScriptedModel(
        steps({"calls": [{"name": "a", "arguments": {}}, {"name": "b", "arguments": {}}]})
    )
    ids = [use.id for use in ask(model).tool_uses]
    assert len(set(ids)) == 2


def test_an_empty_script_or_a_used_up_one_answers_with_nothing() -> None:
    model = ScriptedModel([])
    assert model.available is True
    assert ask(model).text == ""
    assert model.exhausted is True


def test_the_script_is_not_changed_by_a_run() -> None:
    script = steps({"say": "one"})
    ask(ScriptedModel(script))
    assert script[0].say == "one"


# --- the recorder ---------------------------------------------------------------------------------


def test_the_recorder_notes_each_call_and_how_the_crm_answered() -> None:
    inner = ScriptedModel(
        steps(
            {
                "calls": [
                    {"name": "search_leads", "arguments": {"q": ""}},
                    {"name": "propose_lead_status", "arguments": {"status": "contacted"}},
                ]
            },
            {"say": "Done."},
        )
    )
    model = RecordingModel(inner)
    first = ask(model)
    one, two = (use.id for use in first.tool_uses)
    ask(
        model,
        results((one, False, "[]"), (two, True, '{"error": "Record not found."}')),
    )
    assert model.calls == [
        ToolCall("search_leads", {"q": ""}, "ok"),
        ToolCall("propose_lead_status", {"status": "contacted"}, "not_found"),
    ]


def test_the_recorder_passes_the_replies_through_unchanged() -> None:
    model = RecordingModel(ScriptedModel(steps({"say": "Hello"})))
    assert ask(model).text == "Hello"
    assert model.available is True


def test_a_call_whose_result_was_never_returned_is_a_loud_error() -> None:
    model = RecordingModel(
        ScriptedModel(steps({"calls": [{"name": "search_leads", "arguments": {}}]}))
    )
    ask(model)
    with pytest.raises(RunnerError, match="search_leads"):
        _ = model.calls


# --- how the CRM's answer to a call is classified -------------------------------------------------


@pytest.mark.parametrize(
    "content, is_error, expected",
    [
        ("[]", False, "ok"),
        ('{"error": "Record not found."}', True, "not_found"),
        ('{"error": "Ticket not found."}', True, "not_found"),
        ('{"error": "Invalid arguments."}', True, "refused"),
        ('{"error": "Unknown tool."}', True, "refused"),
        ('{"error": "The tool failed."}', True, "refused"),
        ('{"error": "At most 3 proposals per question."}', True, "refused"),
    ],
)
def test_results_are_classified(content: str, is_error: bool, expected: str) -> None:
    assert classify_result(content, is_error) == expected


# --- how a whole conversation is summed up --------------------------------------------------------


def call(outcome: str) -> ToolCall:
    return ToolCall("t", {}, outcome)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "calls, proposals, expected",
    [
        ([], 0, "answered"),
        ([call("ok")], 0, "answered"),
        ([call("ok")], 1, "proposal_pending"),
        ([call("ok"), call("refused")], 1, "proposal_pending"),  # something is waiting
        ([call("refused")], 0, "nothing_changed"),
        ([call("not_found")], 0, "not_found"),
        ([call("refused"), call("not_found")], 0, "not_found"),
    ],
)
def test_the_outcome_of_a_conversation(
    calls: list[ToolCall], proposals: int, expected: str
) -> None:
    assert conversation_outcome(calls, proposals) == expected


# --- the public chat and portal: outcomes and wrong-agent mistakes (EV3) --------------------------


def test_a_saved_lead_beats_everything_else_for_the_public_chat() -> None:
    from agent_evals.runner import public_chat_outcome

    assert public_chat_outcome([call("ok")], lead_saved=True) == "lead_saved"
    assert public_chat_outcome([call("refused"), call("ok")], lead_saved=True) == "lead_saved"
    assert public_chat_outcome([], lead_saved=False) == "answered"
    assert public_chat_outcome([call("refused")], lead_saved=False) == "nothing_changed"


def test_each_runner_refuses_a_case_for_another_agent() -> None:
    from agent_evals.cases import Case
    from agent_evals.runner import run_portal_case, run_public_chat_case, run_staff_case

    def case_for(agent: str, persona: str) -> Case:
        return Case.model_validate(
            {
                "id": "wrong-agent-case",
                "description": "A case for a different agent.",
                "agent": agent,
                "as": persona,
                "messages": ["Hello"],
                "script": [],
                "expect": {"outcome": "answered"},
            }
        )

    portal = case_for("portal_assistant", "customer")
    public = case_for("public_chat", "visitor")
    staff = case_for("staff_assistant", "sales_agent")
    with pytest.raises(RunnerError, match="portal_assistant"):
        run_staff_case(None, None, portal)  # type: ignore[arg-type]
    with pytest.raises(RunnerError, match="staff_assistant"):
        run_portal_case(None, None, staff)  # type: ignore[arg-type]
    with pytest.raises(RunnerError, match="staff_assistant"):
        run_public_chat_case(None, None, staff)  # type: ignore[arg-type]
    with pytest.raises(RunnerError, match="public_chat"):
        run_portal_case(None, None, public)  # type: ignore[arg-type]
