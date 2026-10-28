"""The verification artifact (ADR 0018, step VA1) as pure data: the plan, the comparison and the
stored shape. Reading the record and running the action are tested against the database in
tests/db/test_artifacts.py."""

import uuid

import pytest

from app.modules.approvals.artifact import (
    STORED_VERSION,
    Change,
    build_artifact,
    mismatches,
    outcome_json,
)
from app.modules.approvals.catalogue import KINDS
from app.modules.approvals.sentinel import Finding, Verdict

PERSON = str(uuid.uuid4())
OTHER = str(uuid.uuid4())


def verdict(*findings: Finding) -> Verdict:
    return Verdict(list(findings), ["words", "pattern", "state", "tenant", "record_text"])


# --- the plan ----------------------------------------------------------------------------------


def test_a_change_is_stored_as_plain_json() -> None:
    change = Change("status", "new", "contacted")
    assert change.to_json() == {"field": "status", "before": "new", "after": "contacted"}


def test_a_change_can_hold_a_small_structure_for_a_new_record() -> None:
    task = {"subject": "Call", "due_in_days": 2, "assignee_id": PERSON}
    assert Change("task", None, task).to_json()["after"] == task


def test_the_artifact_keeps_what_the_sentinel_stored_and_adds_plan_and_basis() -> None:
    warning = Finding("lead_owned_by_other", "warn", "Someone else owns this lead.")
    artifact = build_artifact(
        verdict(warning),
        [Change("owner_id", PERSON, OTHER)],
        {"record_version": 3, "status": "new", "owner_id": PERSON},
    )
    assert artifact["version"] == STORED_VERSION == 2
    assert artifact["checked"] == ["words", "pattern", "state", "tenant", "record_text"]
    assert artifact["warnings"] == [{"code": "lead_owned_by_other", "message": warning.message}]
    assert artifact["spec"] == {
        "changes": [{"field": "owner_id", "before": PERSON, "after": OTHER}],
        "basis": {"record_version": 3, "status": "new", "owner_id": PERSON},
    }
    assert "outcome" not in artifact  # written only when the proposal has been decided


def test_a_proposal_for_a_record_without_state_has_an_empty_basis() -> None:
    artifact = build_artifact(verdict(), [Change("task", None, {"subject": "Call"})], {})
    assert artifact["spec"]["basis"] == {}


# --- comparing the plan with what was seen -----------------------------------------------------


def test_the_same_values_match() -> None:
    plan = [Change("status", "new", "contacted"), Change("owner_id", PERSON, OTHER)]
    seen = [Change("status", "new", "contacted"), Change("owner_id", PERSON, OTHER)]
    assert mismatches(plan, seen) == []


def test_only_the_after_value_is_compared() -> None:
    """What was seen afterwards has no 'before' worth comparing: the record has moved on."""
    assert (
        mismatches([Change("status", "new", "contacted")], [Change("status", None, "contacted")])
        == []
    )


def test_a_different_value_is_named() -> None:
    plan = [Change("status", "new", "contacted"), Change("owner_id", PERSON, OTHER)]
    seen = [Change("status", "new", "new"), Change("owner_id", PERSON, OTHER)]
    assert mismatches(plan, seen) == ["status"]


def test_a_field_that_was_not_seen_is_a_mismatch() -> None:
    assert mismatches([Change("status", "new", "contacted")], []) == ["status"]


def test_an_extra_field_that_changed_unannounced_is_a_mismatch() -> None:
    plan = [Change("status", "new", "contacted")]
    seen = [Change("status", "new", "contacted"), Change("owner_id", PERSON, OTHER)]
    assert mismatches(plan, seen) == ["owner_id"]


def test_structures_are_compared_as_a_whole() -> None:
    plan = [Change("task", None, {"subject": "Call", "due_in_days": 2, "assignee_id": PERSON})]
    same = [Change("task", None, {"assignee_id": PERSON, "due_in_days": 2, "subject": "Call"})]
    different = [Change("task", None, {"subject": "Call", "due_in_days": 3, "assignee_id": PERSON})]
    assert mismatches(plan, same) == []
    assert mismatches(plan, different) == ["task"]


def test_ids_compare_as_text_whatever_their_type() -> None:
    plan = [Change("owner_id", None, uuid.UUID(OTHER))]
    seen = [Change("owner_id", None, OTHER)]
    assert mismatches(plan, seen) == []


# --- the outcome -------------------------------------------------------------------------------


def test_an_outcome_that_matched() -> None:
    plan = [Change("status", "new", "contacted")]
    out = outcome_json(uuid.UUID(PERSON), plan, [Change("status", "new", "contacted")])
    assert out == {
        "ran": True,
        "ran_as": PERSON,
        "seen": [{"field": "status", "after": "contacted"}],
        "matches_spec": True,
        "differs": [],
    }


def test_an_outcome_that_differed_names_the_fields() -> None:
    out = outcome_json(
        uuid.UUID(PERSON),
        [Change("status", "new", "contacted")],
        [Change("status", "new", "qualified")],
    )
    assert out["matches_spec"] is False and out["differs"] == ["status"]


def test_an_outcome_without_a_plan_says_unknown() -> None:
    """A proposal made before artifacts existed: what was seen is kept, nothing is judged."""
    out = outcome_json(uuid.UUID(PERSON), None, [Change("status", "new", "contacted")])
    assert out["matches_spec"] is None and out["differs"] == [] and out["ran"] is True


def test_an_outcome_for_an_action_that_did_not_run() -> None:
    out = outcome_json(uuid.UUID(PERSON), [Change("status", "new", "contacted")], None)
    assert out == {"ran": False, "ran_as": PERSON, "seen": [], "matches_spec": None, "differs": []}


def test_the_outcome_holds_ids_and_codes_not_names() -> None:
    out = outcome_json(
        uuid.UUID(PERSON), [Change("owner_id", PERSON, OTHER)], [Change("owner_id", None, OTHER)]
    )
    text = str(out)
    assert PERSON in text and OTHER in text and "Avery" not in text


# --- the catalogue -----------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(KINDS))
def test_every_action_kind_can_describe_its_plan_and_what_it_did(name: str) -> None:
    """A new kind of action must say what it will change and how to see that afterwards."""
    kind = KINDS[name]
    assert callable(kind.spec) and callable(kind.observe)


def test_every_kind_runs_to_a_result_that_can_carry_a_created_record() -> None:
    from app.modules.approvals.catalogue import Ran

    assert Ran("done").created_id is None
    created = uuid.uuid4()
    assert Ran("done", created).created_id == created
