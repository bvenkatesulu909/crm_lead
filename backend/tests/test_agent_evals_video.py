"""The case format of the video drafter (ADR 0041, BP-10): pure, no database."""

from typing import Any

import pytest
from pydantic import ValidationError

from agent_evals.cases import Case, known_tools


def make(**changes: Any) -> Case:
    raw: dict[str, Any] = {
        "id": "video-format-test",
        "description": "A format test.",
        "agent": "video_brief",
        "as": "sales_agent",
        "messages": ["{{lead.facts}}"],
        "expect": {"outcome": "nothing_changed"},
    }
    raw.update(changes)
    return Case.model_validate(raw)


def test_the_drafter_has_exactly_one_tool() -> None:
    assert known_tools("video_brief") == {"submit_script"}


def test_a_draft_case_needs_no_extra_setup() -> None:
    case = make()
    assert case.video is None and case.expect.code is None and case.expect.draft is None


def test_a_propose_case_needs_lines_and_a_draft_case_has_none() -> None:
    with pytest.raises(ValidationError, match="propose case needs lines"):
        make(video={"mode": "propose"})
    with pytest.raises(ValidationError, match="only for a propose case"):
        make(video={"mode": "draft", "lines": ["Hello"]})
    assert make(video={"mode": "propose", "lines": ["Hello"]}).video is not None


def test_a_propose_case_calls_no_model_so_it_has_no_script_or_tools() -> None:
    video = {"mode": "propose", "lines": ["Hello"]}
    step = {"calls": [{"name": "submit_script", "arguments": {}}]}
    with pytest.raises(ValidationError, match="calls no model"):
        make(video=video, script=[step])
    with pytest.raises(ValidationError, match="calls no model"):
        make(
            video=video, expect={"outcome": "nothing_changed", "tools": [{"name": "submit_script"}]}
        )


def test_the_new_fields_belong_to_the_video_drafter_only() -> None:
    other = {"agent": "staff_assistant", "messages": ["Hello"]}
    with pytest.raises(ValidationError, match="only for the video drafter"):
        make(video={"mode": "draft"}, **other)
    with pytest.raises(ValidationError, match="only for the video drafter"):
        make(expect={"outcome": "answered", "code": "video_draft_invalid_answer"}, **other)
    with pytest.raises(ValidationError, match="only for the video drafter"):
        make(expect={"outcome": "answered", "draft": {"contains": ["x"]}}, **other)


def test_a_support_agent_cannot_use_the_drafter() -> None:
    with pytest.raises(ValidationError, match="can't use the video_brief"):
        make(**{"as": "support_agent"})


def test_a_made_up_tool_must_be_listed_as_refused() -> None:
    step = {"calls": [{"name": "send_script_to_buyer", "arguments": {}}]}
    with pytest.raises(ValidationError, match="not a tool of video_brief"):
        make(script=[step])
    case = make(
        script=[step],
        expect={
            "outcome": "refused",
            "tools": [{"name": "send_script_to_buyer", "outcome": "refused"}],
        },
    )
    assert case.expect.tools[0].outcome == "refused"


def test_the_limits_stay_inside_the_platforms_range() -> None:
    for bad in (0, 1_001):
        with pytest.raises(ValidationError):
            make(video={"mode": "draft", "per_lead_hour": bad})
    for choice in ({"length_seconds": 45}, {"language": "fr"}, {"tone": "angry"}, {"goal": "spam"}):
        with pytest.raises(ValidationError):
            make(video={"mode": "draft", **choice})
