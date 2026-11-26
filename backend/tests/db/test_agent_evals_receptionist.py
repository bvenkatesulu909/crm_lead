# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Agent evaluation harness (ADR 0038, BP-10): the voice receptionist, played for real.

Every case in evals/agents/receptionist.json runs through the REAL voice pipeline of the website
chat - the registry gate and the consent before any audio is recognised, the spoken-number check,
the model with its three tools, the knowledge search over the real brochures (customer scope), the
callback proposal in the approval queue, the number check of the spoken answer - with only the
language model replaced by the case's script and the embedder by the harness's hashing stand-in.
Each case also gets checks it cannot skip (agent_evals/receptionist.py): nothing changed directly
and only callbacks proposed, every callback a waiting proposal of fixed words in the visitor's
language, every lead new / unassigned / web / in that language, the consent stored with every
conversation, and no unbacked price or RERA number in a spoken answer without a successful search.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from agent_evals import receptionist as eval_receptionist
from agent_evals.cases import Case, dataset_hash, load_cases
from agent_evals.scoring import CaseResult, build_scorecard
from app.modules.agents import api as agents_api
from app.modules.approvals import api as approvals_api
from app.modules.public_chat import rules, service
from tests.db.agent_eval_support import eval_world, explain, play_receptionist
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "agents"
RECEPTIONIST = [case for case in load_cases(CASES_DIR) if case.agent == "receptionist"]
BY_ID = {case.id: case for case in RECEPTIONIST}
SAVE = "rec-save-lead-english"
CALLBACK = "rec-callback-proposal"
INVENTED = "rec-invented-price-replaced"
CARD = "rec-card-said-in-words"
OFF = "rec-off"
REMOVED = "rec-tool-removed"


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


def test_the_dataset_covers_every_way_a_call_can_end() -> None:
    assert len(RECEPTIONIST) >= 30
    outcomes = {case.expect.outcome for case in RECEPTIONIST}
    assert {"answered", "lead_saved", "proposal_pending", "refused", "agent_off"} <= outcomes
    assert "nothing_changed" in outcomes
    assert {case.language for case in RECEPTIONIST} == {"en", "hi", "te"}
    # A real model is only asked the plain ones; forced bad calls and the search are scripted.
    assert {case.id for case in RECEPTIONIST if case.live} == {
        "rec-greeting-no-tools",
        SAVE,
        "rec-save-lead-telugu",
        CALLBACK,
        "rec-callback-before-lead",
    }


@pytest.mark.parametrize("case", RECEPTIONIST, ids=lambda case: case.id)
def test_a_receptionist_case_passes(case: Case, db_session: Session, world: World) -> None:
    result, _ = play_receptionist(db_session, world, case)
    assert result.passed, explain(result)


def test_the_whole_dataset_scores_clean_in_one_transaction(
    db_session: Session, world: World
) -> None:
    # A case must leave nothing behind for the next.
    results: list[CaseResult] = [play_receptionist(db_session, world, c)[0] for c in RECEPTIONIST]
    card = build_scorecard(results, provider="fake", dataset_sha256=dataset_hash(CASES_DIR))
    assert card.total == len(RECEPTIONIST)
    assert card.all_passed, card.to_json()
    assert card.tool_precision == 1.0 and card.tool_recall == 1.0


# --- the gate can fail ---------------------------------------------------------------------------


def test_a_wrong_expected_outcome_fails_the_case(db_session: Session, world: World) -> None:
    case = variant(SAVE, **{"expect.outcome": "answered"})
    assert play_receptionist(db_session, world, case)[0].passed is False


def test_a_wrong_expected_callback_count_fails_the_case(db_session: Session, world: World) -> None:
    case = variant(CALLBACK, **{"expect.callbacks": 0})
    assert play_receptionist(db_session, world, case)[0].passed is False


def test_a_spoken_number_check_that_lets_a_card_through_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rules, "spoken_number_refusal", lambda text: False)
    assert play_receptionist(db_session, world, BY_ID[CARD])[0].passed is False


def test_an_answer_gate_that_lets_an_invented_price_through_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "_unbacked_numbers", lambda *a, **k: False)
    assert play_receptionist(db_session, world, BY_ID[INVENTED])[0].passed is False


def test_a_receptionist_that_ignores_the_registry_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without the gate a switched-off receptionist still answers.
    monkeypatch.setattr(agents_api, "check_can_call", lambda *a, **k: None)
    monkeypatch.setattr(agents_api, "governed", lambda model, *a, **k: model)
    assert play_receptionist(db_session, world, BY_ID[OFF])[0].passed is False


def test_a_tool_filter_that_does_nothing_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agents_api, "governed", lambda model, *a, **k: model)
    assert play_receptionist(db_session, world, BY_ID[REMOVED])[0].passed is False


def test_a_callback_that_claims_success_without_a_proposal_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service, "_request_callback", lambda *a, **k: ('{"requested": true}', False)
    )
    assert play_receptionist(db_session, world, BY_ID[CALLBACK])[0].passed is False


def test_a_callback_with_more_than_fixed_words_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = approvals_api.propose

    def with_a_note(*args: Any, **kwargs: Any) -> Any:
        action = real(*args, **kwargs)
        action.payload = {**(action.payload or {}), "note": "visitor said: call me at 3"}
        db_session.flush()
        return action

    monkeypatch.setattr(approvals_api, "propose", with_a_note)
    result, _ = play_receptionist(db_session, world, BY_ID[CALLBACK])
    assert result.passed is False
    assert any(c.name == "callbacks_shape" and not c.passed for c in result.checks)


def test_a_callback_with_the_wrong_language_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = approvals_api.propose

    def english_always(*args: Any, **kwargs: Any) -> Any:
        kwargs["payload"] = {**kwargs["payload"], "language": "en"}
        return real(*args, **kwargs)

    monkeypatch.setattr(approvals_api, "propose", english_always)
    result, _ = play_receptionist(db_session, world, BY_ID["rec-callback-telugu"])
    assert result.passed is False
    assert any(c.name == "callbacks_shape" and not c.passed for c in result.checks)


def test_a_conversation_without_the_consent_record_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The database refuses a voice conversation without its consent, so the stored version is
    falsified after the call: the check must notice a version that is not the current notice."""
    real = eval_receptionist.run_receptionist_case

    def forget_the_version(*args: Any, **kwargs: Any) -> Any:
        run = real(*args, **kwargs)
        found = eval_receptionist._conversations(  # noqa: SLF001
            db_session, eval_world(db_session, world)
        )
        for conversation in found.values():
            conversation.voice_consent_version = 99
        db_session.flush()
        return run

    monkeypatch.setattr(eval_receptionist, "run_receptionist_case", forget_the_version)
    result, _ = play_receptionist(db_session, world, BY_ID[SAVE])
    assert result.passed is False
    assert any(c.name == "consent_stored" and not c.passed for c in result.checks)
