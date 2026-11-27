# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Agent evaluation harness (ADR 0041, BP-10): the video drafter, played for real.

Every case in evals/agents/video_brief.json runs through the REAL ``draft.draft_script`` (facts read
as the asker, limits, agent registry, cleaned facts, strict answer check, the code-side checks) or
``draft.propose_script`` (every check again, the approval queue and its Sentinel), with only the
language model replaced by the case's script - a propose case calls no model. Each case also gets
checks it cannot skip (agent_evals/video.py): nothing changed directly, proposals stored and pending
with exactly the five payload fields, every draft audited once, and the model never shown the lead's
last name, e-mail address, phone number or company.
"""

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_evals import video as eval_video
from agent_evals.cases import Case, dataset_hash, load_cases
from agent_evals.scoring import CaseResult, build_scorecard
from agent_evals.world import VIDEO_SECRETS
from app.modules.agents import api as agents_api
from app.modules.buyer_memory.models import BuyerMemoryItem
from app.modules.video_brief import draft
from app.modules.video_brief.models import VideoScript
from tests.db.agent_eval_support import explain, play_video_brief
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "agents"
VIDEO = [case for case in load_cases(CASES_DIR) if case.agent == "video_brief"]
BY_ID = {case.id: case for case in VIDEO}
HAPPY = "video-draft-uses-the-confirmed-facts"
SWITCHED_OFF = "video-draft-switched-off-stops-before-the-model"
PROPOSE = "video-propose-waits-for-a-colleagues-approval"


def variant(case_id: str, **changes: Any) -> Case:
    """A changed copy of a real case, to see the gate notice the change."""
    raw = BY_ID[case_id].model_dump(by_alias=True)
    for path, value in changes.items():
        target: Any = raw
        *parents, last = path.split(".")
        for part in parents:
            target = target[int(part)] if part.isdigit() else target[part]
        target[int(last) if last.isdigit() else last] = value
    return Case.model_validate(raw)


def test_the_dataset_covers_every_way_a_script_can_end() -> None:
    assert len(VIDEO) >= 20
    outcomes = {case.expect.outcome for case in VIDEO}
    assert {
        "nothing_changed",
        "proposal_pending",
        "refused",
        "not_found",
        "agent_off",
        "over_budget",
    } <= outcomes
    modes = {case.video.mode if case.video else "draft" for case in VIDEO}
    assert modes == {"draft", "propose"}
    codes = {case.expect.code for case in VIDEO if case.expect.code}
    assert {
        "video_draft_unsupported_number",
        "video_draft_assumption_stated",
        "video_draft_script_banned_phrase",
        "video_draft_script_contact_detail",
        "video_draft_script_unsafe_text",
        "video_draft_script_too_long",
        "video_draft_invalid_answer",
        "video_draft_rate_limited",
    } <= codes
    # Only the open-ended drafts may be played by a real model; forced bad answers are scripted.
    assert {case.id for case in VIDEO if case.live} == {
        HAPPY,
        "video-draft-asks-about-an-assumption-as-question",
    }


@pytest.mark.parametrize("case", VIDEO, ids=lambda case: case.id)
def test_a_video_drafter_case_passes(case: Case, db_session: Session, world: World) -> None:
    result, _ = play_video_brief(db_session, world, case)
    assert result.passed, explain(result)


def test_the_whole_dataset_scores_clean_in_one_transaction(
    db_session: Session, world: World
) -> None:
    # A case must leave nothing behind for the next.
    results: list[CaseResult] = [play_video_brief(db_session, world, c)[0] for c in VIDEO]
    card = build_scorecard(results, provider="fake", dataset_sha256=dataset_hash(CASES_DIR))
    assert card.total == len(VIDEO)
    assert card.all_passed, card.to_json()
    assert card.tool_precision == 1.0 and card.tool_recall == 1.0


# --- the gate can fail ---------------------------------------------------------------------------


def test_a_wrong_expected_word_fails_the_case(db_session: Session, world: World) -> None:
    case = variant(HAPPY, **{"expect.draft.contains": ["no such words"]})
    assert play_video_brief(db_session, world, case)[0].passed is False


def test_a_wrong_expected_code_fails_the_case(db_session: Session, world: World) -> None:
    case = variant(
        "video-draft-made-up-number-is-refused", **{"expect.code": "video_draft_script_too_long"}
    )
    result, _ = play_video_brief(db_session, world, case)
    assert result.passed is False
    assert any(c.name == "refusal_code" and not c.passed for c in result.checks)


def test_a_missing_proposal_is_caught(db_session: Session, world: World) -> None:
    case = variant(PROPOSE, **{"expect.proposals": []})
    assert play_video_brief(db_session, world, case)[0].passed is False


def test_a_drafter_that_saves_the_script_itself_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = draft.draft_script

    def and_saves_it(session: Session, principal: Any, model: Any, lead: Any, **kw: Any):  # noqa: ANN202
        result = real(session, principal, model, lead, **kw)
        session.add(
            VideoScript(
                tenant_id=principal.tenant_id,
                lead_id=lead,
                created_by_user_id=principal.user_id,
                version=1,
                language="en",
                tone="warm",
                goal="follow_up",
                length_seconds=60,
                lines=["Saved by the drafter itself."],
                words=5,
                source="hand_written",
            )
        )
        session.flush()
        return result

    monkeypatch.setattr(draft, "draft_script", and_saves_it)
    result, _ = play_video_brief(db_session, world, BY_ID[HAPPY])
    assert result.passed is False
    assert any(c.name == "no_direct_change" and not c.passed for c in result.checks)


def test_a_drafter_that_writes_buyer_memory_itself_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = draft.draft_script

    def and_remembers(session: Session, principal: Any, model: Any, lead: Any, **kw: Any):  # noqa: ANN202
        result = real(session, principal, model, lead, **kw)
        session.add(
            BuyerMemoryItem(
                tenant_id=principal.tenant_id,
                lead_id=lead,
                key="budget",
                value="Made up",
                status="assumption",
                reason="The drafter wrote it",
                recorded_by_user_id=principal.user_id,
            )
        )
        session.flush()
        return result

    monkeypatch.setattr(draft, "draft_script", and_remembers)
    result, _ = play_video_brief(db_session, world, BY_ID[HAPPY])
    assert result.passed is False
    assert any(c.name == "no_direct_change" and not c.passed for c in result.checks)


def test_a_drafter_that_forgets_the_audit_entry_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(draft, "record_audit", lambda *a, **k: None)
    result, _ = play_video_brief(db_session, world, BY_ID[HAPPY])
    assert result.passed is False
    assert any(c.name == "runs_audited" and not c.passed for c in result.checks)


def test_a_drafter_that_ignores_the_registry_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without the registry gate a switched-off drafter still calls the model.
    monkeypatch.setattr(agents_api, "governed", lambda model, *a, **k: model)
    result, _ = play_video_brief(db_session, world, BY_ID[SWITCHED_OFF])
    assert result.passed is False


def test_a_drafter_that_shows_the_model_the_contact_details_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = draft.system_prompt

    def with_the_phone(shown: dict[str, Any], suspicious: bool) -> str:
        return real(shown, suspicious) + f"\nPhone: {VIDEO_SECRETS[2]}"

    monkeypatch.setattr(draft, "system_prompt", with_the_phone)
    result, _ = play_video_brief(db_session, world, BY_ID[HAPPY])
    assert result.passed is False
    assert any(c.name == "model_privacy" and not c.passed for c in result.checks)


def test_a_drafter_that_lets_a_made_up_number_through_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(draft, "numbers_in", lambda text: set())
    result, _ = play_video_brief(db_session, world, BY_ID["video-draft-made-up-number-is-refused"])
    assert result.passed is False


def test_a_proposal_with_more_than_the_script_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The shape check looks at what was stored: a payload with a sixth field fails it.
    real = eval_video._proposal_shape

    def six_fields(session: Session, ids: list[uuid.UUID]) -> Any:
        from app.modules.approvals.models import AgentAction

        for action in session.scalars(select(AgentAction).where(AgentAction.id.in_(ids))):
            action.payload = {**(action.payload or {}), "price": "1"}
        session.flush()
        return real(session, ids)

    monkeypatch.setattr(eval_video, "_proposal_shape", six_fields)
    result, _ = play_video_brief(db_session, world, BY_ID[PROPOSE])
    assert result.passed is False
    assert any(c.name == "proposal_shape" and not c.passed for c in result.checks)
