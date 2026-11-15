# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Agent evaluation harness (ADR 0032 Amendment A, BP-10): the deck writer, played for real.

Every case in evals/agents/deck_writer.json runs through the REAL ``writer.draft_summary`` -
permission to change the quote, the quote's own read rules, the limits, the agent registry, the
cleaned facts, the strict answer check, the approval queue and its Sentinel, the audit - with only
the language model replaced by the case's script. Each case also gets checks it cannot skip
(agent_evals/writer.py): nothing changed directly, proposals stored and pending with exactly one
``text`` field that fits the slide and holds no link, every finished run audited once.
"""

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_evals import writer as eval_writer
from agent_evals.cases import Case, dataset_hash, load_cases
from agent_evals.scoring import CaseResult, build_scorecard
from app.modules.agents import api as agents_api
from app.modules.proposal_decks import writer
from app.modules.proposal_decks.models import DeckSummary
from app.modules.quotes.models import Quote
from tests.db.agent_eval_support import explain, play_deck_writer
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "agents"
WRITER = [case for case in load_cases(CASES_DIR) if case.agent == "deck_writer"]
BY_ID = {case.id: case for case in WRITER}
HAPPY = "deck-writer-drafts-a-slide"
SWITCHED_OFF = "deck-writer-switched-off-stops-before-the-model"


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


def test_the_dataset_covers_every_way_a_draft_can_end() -> None:
    assert len(WRITER) >= 16
    outcomes = {case.expect.outcome for case in WRITER}
    assert {"proposal_pending", "refused", "not_found", "agent_off", "over_budget"} <= outcomes
    # Two cases may also be played by a real model; the forced bad answers are scripted only.
    assert {case.id for case in WRITER if case.live} == {
        HAPPY,
        "deck-writer-quote-note-tries-to-steer-the-model",
    }


@pytest.mark.parametrize("case", WRITER, ids=lambda case: case.id)
def test_a_deck_writer_case_passes(case: Case, db_session: Session, world: World) -> None:
    result, _ = play_deck_writer(db_session, world, case)
    assert result.passed, explain(result)


def test_the_whole_dataset_scores_clean_in_one_transaction(
    db_session: Session, world: World
) -> None:
    # A case must leave nothing behind for the next.
    results: list[CaseResult] = [play_deck_writer(db_session, world, c)[0] for c in WRITER]
    card = build_scorecard(results, provider="fake", dataset_sha256=dataset_hash(CASES_DIR))
    assert card.total == len(WRITER)
    assert card.all_passed, card.to_json()
    assert card.tool_precision == 1.0 and card.tool_recall == 1.0


# --- the gate can fail ---------------------------------------------------------------------------


def test_a_wrong_expected_text_fails_the_case(db_session: Session, world: World) -> None:
    case = variant(HAPPY, **{"expect.proposals.0.payload.text": {"contains": "no such words"}})
    assert play_deck_writer(db_session, world, case)[0].passed is False


def test_a_missing_proposal_is_caught(db_session: Session, world: World) -> None:
    assert (
        play_deck_writer(db_session, world, variant(HAPPY, **{"expect.proposals": []}))[0].passed
        is False
    )


def test_a_writer_that_changes_the_quote_itself_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = writer.draft_summary

    def and_edits_the_quote(session: Session, principal: Any, model: Any, quote: Any, **kw: Any):  # noqa: ANN202
        result = real(session, principal, model, quote, **kw)
        found = session.scalar(select(Quote).where(Quote.id == quote))
        assert found is not None
        found.title = "Changed by the writer"
        found.status = "draft"
        session.flush()
        return result

    monkeypatch.setattr(writer, "draft_summary", and_edits_the_quote)
    result, _ = play_deck_writer(db_session, world, BY_ID[HAPPY])
    assert result.passed is False
    assert any(c.name == "no_direct_change" and not c.passed for c in result.checks)


def test_a_writer_that_stores_the_summary_without_approval_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = writer.draft_summary

    def and_approves_it(session: Session, principal: Any, model: Any, quote: Any, **kw: Any):  # noqa: ANN202
        result = real(session, principal, model, quote, **kw)
        session.add(
            DeckSummary(
                tenant_id=principal.tenant_id,
                quote_id=quote,
                approved_by_user_id=principal.user_id,
                body="Approved by the writer itself.",
            )
        )
        session.flush()
        return result

    monkeypatch.setattr(writer, "draft_summary", and_approves_it)
    result, _ = play_deck_writer(db_session, world, BY_ID[HAPPY])
    assert result.passed is False
    assert any(c.name == "no_direct_change" and not c.passed for c in result.checks)


def test_a_writer_that_forgets_the_audit_entry_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(writer, "record_audit", lambda *a, **k: None)
    result, _ = play_deck_writer(db_session, world, BY_ID[HAPPY])
    assert result.passed is False
    assert any(c.name == "runs_audited" and not c.passed for c in result.checks)


def test_a_writer_that_ignores_the_registry_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without the registry gate a switched-off writer still calls the model.
    monkeypatch.setattr(agents_api, "governed", lambda model, *a, **k: model)
    result, _ = play_deck_writer(db_session, world, BY_ID[SWITCHED_OFF])
    assert result.passed is False


def test_a_proposal_with_more_than_the_text_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The shape check looks at what was stored: a payload with a second field fails it.
    real = eval_writer._proposal_shape

    def two_fields(session: Session, ids: list[uuid.UUID]) -> Any:
        from app.modules.approvals.models import AgentAction

        for action in session.scalars(select(AgentAction).where(AgentAction.id.in_(ids))):
            action.payload = {**(action.payload or {}), "price": "1"}
        session.flush()
        return real(session, ids)

    monkeypatch.setattr(eval_writer, "_proposal_shape", two_fields)
    result, _ = play_deck_writer(db_session, world, BY_ID[HAPPY])
    assert result.passed is False
    assert any(c.name == "proposal_shape" and not c.passed for c in result.checks)
