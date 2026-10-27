"""Evaluation cases about the Sentinel (ADR 0017, step SN4): the case format and the dataset.

``expect.safety_warnings`` lists the warning codes the stored proposals must carry. The cases
themselves are played against the database in tests/db/test_agent_evals_staff.py and friends."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agent_evals.cases import Case, load_cases
from app.modules.approvals import sentinel

CASES_DIR = Path(__file__).resolve().parents[1] / "evals" / "agents"
ALL = {case.id: case for case in load_cases(CASES_DIR)}
SENTINEL_CASES = [case for case in ALL.values() if "-sentinel-" in case.id]


def make(**expect: Any) -> Case:
    return Case.model_validate(
        {
            "id": "staff-sentinel-format",
            "description": "A format check.",
            "agent": "staff_assistant",
            "as": "sales_agent",
            "messages": ["Mark lead {{lead.own}} as contacted."],
            "expect": {"outcome": "proposal_pending", **expect},
        }
    )


def test_safety_warnings_are_optional_and_default_to_not_checked() -> None:
    assert make().expect.safety_warnings is None


def test_an_empty_list_means_the_proposals_must_carry_no_warning() -> None:
    assert make(safety_warnings=[]).expect.safety_warnings == []


def test_known_warning_codes_are_accepted() -> None:
    codes = ["lead_owned_by_other", "record_contains_instruction"]
    assert make(safety_warnings=codes).expect.safety_warnings == codes


@pytest.mark.parametrize("bad", ["not_a_rule", "link", "lead_converted"])
def test_a_code_that_is_not_a_warning_is_refused(bad: str) -> None:
    """A typo, or a code that blocks instead of warning, must not pass unnoticed."""
    with pytest.raises(ValidationError, match="warning"):
        make(safety_warnings=[bad])


def test_every_warning_the_sentinel_can_give_is_known_to_the_format() -> None:
    assert sentinel.WARNING_CODES >= {
        "phone_number",
        "busy_record",
        "downgrade_qualified",
        "lead_owned_by_other",
        "task_for_other",
        "record_contains_instruction",
        "record_contains_hidden_text",
        "record_contains_link",
    }


# --- the dataset -------------------------------------------------------------------------------


def test_there_are_sentinel_cases_for_every_entrance() -> None:
    by_agent = {case.agent for case in SENTINEL_CASES}
    assert by_agent == {"staff_assistant", "portal_assistant", "public_chat"}
    assert len([c for c in SENTINEL_CASES if c.agent == "staff_assistant"]) >= 7


def test_the_staff_cases_cover_blocked_warned_and_refused() -> None:
    staff = {c.id: c for c in SENTINEL_CASES if c.agent == "staff_assistant"}
    outcomes = {c.expect.outcome for c in staff.values()}
    assert {"proposal_pending", "nothing_changed", "refused"} <= outcomes
    assert any(c.expect.safety_warnings for c in staff.values())  # a warned proposal
    assert any(
        any(call.outcome == "refused" for call in c.expect.tools) for c in staff.values()
    )  # a proposal the Sentinel refused


def test_the_hidden_character_cases_use_real_hidden_characters() -> None:
    hidden = [c for c in SENTINEL_CASES if "hidden" in c.id]
    assert len(hidden) >= 3
    for case in hidden:
        assert any("​" in message for message in case.messages), case.id
        assert case.expect.outcome == "refused" and case.expect.model_called is False


def test_the_cases_that_force_a_blocked_proposal_are_not_played_by_a_real_model() -> None:
    """A real model decides its own reason; only the script can force a link into it."""
    assert all(case.live is False for case in SENTINEL_CASES)
