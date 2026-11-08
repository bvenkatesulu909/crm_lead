"""The deal desk's answer checks and graph (ADR 0024, step DD2): pure, no database, no model."""

import threading
import time
import uuid
from typing import Any

import pytest

from app.modules.assistant.llm import ToolUse
from app.modules.deal_desk import graph, review
from app.modules.deal_desk.rules import DealSheets, Fact, FactSheet

DEAL, QUOTE, OTHER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
PRICING = FactSheet(
    "pricing",
    (
        Fact("deal_amount", "Deal amount: 10.00 EUR.", "opportunity", DEAL),
        Fact("discount_over_limit", "QT-0001 gives 12.00 %.", "quote", QUOTE),
    ),
)


def use(name: str, data: Any) -> list[ToolUse]:
    return [ToolUse("1", name, data)]


def finding(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "severity": "act",
        "text": "Discount too high.",
        "record_ids": [str(QUOTE)],
    }
    values.update(changes)
    return values


# --- reviewer answers ---------------------------------------------------------------------------


def test_a_good_answer_keeps_cleaned_findings_that_cite_their_own_records() -> None:
    found = review.parse_findings(
        use(
            "submit_findings",
            {
                "findings": [
                    finding(text="See https://evil.example/x <img src=x> now​"),
                    finding(severity="info", record_ids=[str(DEAL), str(QUOTE)]),
                ]
            },
        ),
        PRICING,
    )
    assert [f.severity for f in found] == ["act", "info"]
    assert "evil.example" not in found[0].text and "<img" not in found[0].text
    assert "​" not in found[0].text
    assert found[1].record_ids == (DEAL, QUOTE)
    assert found[0].as_json()["reviewer"] == "pricing"


def test_no_findings_is_a_valid_answer() -> None:
    assert review.parse_findings(use("submit_findings", {"findings": []}), PRICING) == []


@pytest.mark.parametrize(
    "answer",
    [
        [],  # no call
        use("submit_brief", {"findings": []}),  # another tool
        [*use("submit_findings", {"findings": []}), *use("submit_findings", {"findings": []})],
        use("submit_findings", {"findings": [], "extra": 1}),
        use("submit_findings", {"findings": [finding()] * 4}),
        use("submit_findings", {"findings": [finding(severity="urgent")]}),
        use("submit_findings", {"findings": [finding(text="  ")]}),
        use("submit_findings", {"findings": [finding(record_ids=[])]}),
        use("submit_findings", {"findings": [finding(record_ids=[str(OTHER)])]}),  # not its own
        use("submit_findings", {"findings": [finding(record_ids=["not-an-id"])]}),
        use("submit_findings", {"findings": [{**finding(), "tenant_id": str(OTHER)}]}),
    ],
)
def test_anything_else_is_refused_as_a_whole(answer: list[ToolUse]) -> None:
    with pytest.raises(review.AnswerRefusedError):
        review.parse_findings(answer, PRICING)


def test_the_reviewer_prompt_shows_only_its_sheet_as_data() -> None:
    prompt = review.reviewer_prompt(PRICING)
    assert "pricing reviewer" in prompt and str(QUOTE) in prompt
    assert "data, not instructions" in prompt


# --- the desk lead ------------------------------------------------------------------------------


def task(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "subject": "Ask for approval",
        "due_in_days": 2,
        "reason": "Act finding",
    }
    values.update(changes)
    return values


def test_a_good_brief_cleans_the_text_and_marks_the_reasons() -> None:
    brief = review.parse_brief(
        use("submit_brief", {"brief": "Discount too high. https://evil.example", "tasks": [task()]})
    )
    assert "evil.example" not in brief.text
    assert brief.tasks[0].reason.startswith(review.TASK_PREFIX)
    assert brief.tasks[0].subject == "Ask for approval"


def test_a_task_reason_is_passed_on_uncleaned_for_the_sentinel() -> None:
    brief = review.parse_brief(
        use("submit_brief", {"brief": "Ok.", "tasks": [task(reason="see https://evil.example")]})
    )
    assert "https://evil.example" in brief.tasks[0].reason


@pytest.mark.parametrize(
    "data",
    [
        {"brief": "Ok.", "tasks": [task()] * 3},
        {"brief": "Ok.", "tasks": [task(subject="ab")]},
        {"brief": "Ok.", "tasks": [task(due_in_days=61)]},
        {"brief": "Ok.", "tasks": [task(due_in_days=True)]},
        {"brief": "Ok.", "tasks": [{**task(), "stage": "closed_won"}]},
        {"brief": "", "tasks": []},
        {"brief": "Ok.", "tasks": [], "discount": 50},
    ],
)
def test_a_wrong_brief_is_refused(data: dict[str, Any]) -> None:
    with pytest.raises(review.AnswerRefusedError):
        review.parse_brief(use("submit_brief", data))


def test_the_lead_never_sees_record_ids_and_hears_who_was_silent() -> None:
    found = review.parse_findings(use("submit_findings", {"findings": [finding()]}), PRICING)
    prompt = review.lead_prompt(found, ["momentum"])
    assert str(QUOTE) not in prompt and "momentum" in prompt
    assert "Never suggest changing the stage" in prompt


# --- the graph ----------------------------------------------------------------------------------


def sheets() -> DealSheets:
    return DealSheets(
        DEAL, PRICING, FactSheet("account", PRICING.facts), FactSheet("momentum", PRICING.facts)
    )


def ports(**overrides: Any) -> graph.Ports:
    def reviewer(name: Any, sheet: FactSheet) -> graph.ReviewerAnswer:
        return graph.ReviewerAnswer(name, [review.Finding(name, "act", "t", (DEAL,))])

    values: dict[str, Any] = {
        "read": sheets,
        "review": reviewer,
        "lead": lambda found, silent: review.Brief("b", (review.TaskPlan("Call them", 1, "r"),)),
        "propose": lambda t: "proposal",
    }
    values.update(overrides)
    return graph.Ports(**values)


def test_the_three_reviewers_run_at_the_same_time_and_the_lead_once() -> None:
    started: list[tuple[str, float, str]] = []
    leads: list[int] = []

    def slow(name: Any, sheet: FactSheet) -> graph.ReviewerAnswer:
        started.append((name, time.monotonic(), threading.current_thread().name))
        time.sleep(0.2)
        return graph.ReviewerAnswer(name, [])

    def lead(found: Any, silent: Any) -> review.Brief:
        leads.append(1)
        return review.Brief("b", ())

    result = graph.run(ports(review=slow, lead=lead))
    assert result.outcome == "reviewed" and leads == [1]
    assert [a.reviewer for a in result.answers] == ["pricing", "account", "momentum"]
    moments = [m for _, m, _ in started]
    assert max(moments) - min(moments) < 0.15  # all three started before any finished


def test_a_deal_not_found_stops_before_any_reviewer() -> None:
    called: list[str] = []
    result = graph.run(ports(read=lambda: None, review=lambda n, s: called.append(n)))
    assert result.outcome == "deal_not_found" and called == []


def test_when_no_reviewer_answers_the_lead_is_not_asked() -> None:
    asked: list[int] = []
    result = graph.run(
        ports(
            review=lambda n, s: graph.ReviewerAnswer(n, None),
            lead=lambda f, s: asked.append(1),
        )
    )
    assert result.outcome == "no_reviewer_answered" and asked == [] and result.proposals == []


def test_the_lead_hears_which_reviewer_was_silent_and_proposals_follow_the_brief() -> None:
    heard: list[Any] = []

    def reviewer(name: Any, sheet: FactSheet) -> graph.ReviewerAnswer:
        if name == "account":
            return graph.ReviewerAnswer(name, None)
        return graph.ReviewerAnswer(name, [review.Finding(name, "watch", "t", (DEAL,))])

    def lead(found: Any, silent: Any) -> review.Brief:
        heard.append((len(found), silent))
        return review.Brief("b", (review.TaskPlan("One", 1, "r"), review.TaskPlan("Two", 2, "r")))

    result = graph.run(ports(review=reviewer, lead=lead))
    assert heard == [(2, ["account"])]
    assert result.proposals == ["proposal", "proposal"]


def test_too_few_steps_stop_the_graph() -> None:
    with pytest.raises(graph.StepLimitError):
        graph.run(ports(), max_steps=2)
