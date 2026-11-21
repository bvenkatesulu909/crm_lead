"""What a call-notes draft may turn into proposals (ADR 0035, CN4): pure rules, no database."""

import pytest

from app.modules.call_notes import proposal_rules as pr
from app.modules.call_notes import rules
from app.modules.call_notes.proposal_rules import PlanRefused, StoredLine


def line(position: int, field: str, state: str = "stated", **changes: object) -> StoredLine:
    base: dict[str, object] = {
        "value": "around one and a half crore",
        "quote": "My budget is around one and a half crore",
        "start_ms": 6000,
        "reason": None,
    }
    if state == "unknown":
        base = {"value": None, "quote": None, "start_ms": None, "reason": None}
    if state == "assumed":
        base["reason"] = "They hinted at it."
    return StoredLine(position, field, state, **{**base, **changes})  # type: ignore[arg-type]


BANT = [
    line(1, "budget"),
    line(2, "authority", "assumed", value="wife decides too", start_ms=14_000),
    line(3, "need", "unknown"),
    line(4, "timeline", "unknown"),
    StoredLine(5, "note", "stated", "A note", "some words said", 30_000, None),
]


def test_a_stamp_is_minutes_and_seconds() -> None:
    assert pr.stamp(6000) == "0:06"
    assert pr.stamp(3_725_000) == "62:05"
    assert pr.stamp(-5) == "0:00"


def test_stated_and_assumed_lines_with_a_buyer_memory_key_are_eligible() -> None:
    items = pr.eligible("bant", BANT, 1)
    assert [(i.position, i.key) for i in items] == [(1, "budget"), (2, "decision_makers")]


def test_a_stated_line_is_still_only_an_assumption_with_its_quote_and_time() -> None:
    [first, second] = pr.eligible("bant", BANT, 3)
    assert first.note == 'Said on the call at 0:06: "My budget is around one and a half crore"'
    assert first.reason.startswith("Call notes v3, Budget at 0:06:")
    assert first.at_ms == 6000 and first.value == "around one and a half crore"
    assert second.note == "They hinted at it. (call, 0:14)"


def test_unknown_lines_and_notes_and_unmapped_fields_are_never_eligible() -> None:
    meddic = [
        line(1, "metrics"),
        line(2, "champion"),
        line(3, "decision_process"),
        line(4, "economic_buyer"),
        line(5, "identify_pain", "unknown"),
    ]
    assert [i.field for i in pr.eligible("meddic", meddic, 1)] == ["economic_buyer"]


def test_texts_are_capped() -> None:
    long = line(1, "budget", quote="word " * 200, value="a value")
    [item] = pr.eligible("bant", [long], 1)
    assert len(item.note) <= pr.NOTE_MAX and item.note.endswith("…")
    assert len(item.reason) <= pr.REASON_MAX


def test_by_default_every_eligible_line_and_one_task_for_the_unknowns() -> None:
    plan = pr.plan("bant", BANT, version_no=2, positions=None, follow_up_task=True)
    assert [i.position for i in plan.memory] == [1, 2]
    assert plan.task is not None
    assert plan.task.subject == "Ask the buyer about need and timeline"
    assert plan.task.labels == ["Need", "Timeline"] and plan.task.due_in_days == 2
    assert "call notes v2" in plan.task.reason


def test_the_task_is_one_and_only_when_something_is_unknown_and_asked_for() -> None:
    assert pr.plan("bant", BANT, version_no=1, positions=None, follow_up_task=False).task is None
    known = [line(1, "budget"), line(2, "timeline")]
    assert pr.plan("bant", known, version_no=1, positions=None, follow_up_task=True).task is None
    only = [line(1, "need", "unknown")]
    task = pr.plan("bant", only, version_no=1, positions=None, follow_up_task=True).task
    assert task is not None and task.subject == "Ask the buyer about need"


def test_a_note_line_never_counts_as_unknown() -> None:
    plan = pr.plan("bant", [BANT[4]], version_no=1, positions=None, follow_up_task=True)
    assert plan.task is None and plan.memory == []


def test_chosen_positions_pick_lines_in_the_order_given() -> None:
    plan = pr.plan("bant", BANT, version_no=1, positions=[2, 1], follow_up_task=False)
    assert [i.position for i in plan.memory] == [2, 1]
    assert pr.plan("bant", BANT, version_no=1, positions=[], follow_up_task=True).memory == []


@pytest.mark.parametrize("positions", [[3], [4], [5], [99], [1, 3]])
def test_a_line_that_cannot_be_proposed_is_refused_not_skipped(positions: list[int]) -> None:
    with pytest.raises(PlanRefused) as caught:
        pr.plan("bant", BANT, version_no=1, positions=positions, follow_up_task=False)
    assert caught.value.code == "not_proposable"


def test_a_line_chosen_twice_is_refused() -> None:
    with pytest.raises(PlanRefused) as caught:
        pr.plan("bant", BANT, version_no=1, positions=[1, 1], follow_up_task=False)
    assert caught.value.code == "duplicate_position"


def test_more_than_five_buyer_memory_suggestions_are_refused(monkeypatch) -> None:
    monkeypatch.setattr(rules, "MAX_PROPOSALS", 1)
    with pytest.raises(PlanRefused) as caught:
        pr.plan("bant", BANT, version_no=1, positions=None, follow_up_task=False)
    assert caught.value.code == "too_many"


def test_an_unknown_frame_is_refused() -> None:
    with pytest.raises(PlanRefused):
        pr.plan("spin", BANT, version_no=1, positions=None, follow_up_task=False)
