# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Agent evaluation harness (ADR 0035, CN6; BP-10): call notes, played for real.

Every case in evals/agents/call_notes.json runs through the REAL ``call_notes.service.run_notes``
(and ``proposals.propose`` when the case asks for suggestions) - permission, the transcript only of
a lead the person may read, size and rate limits, the agent registry, the cleaned transcript, the
strict answer check, the quote verification, the stored draft, the approval queue and its
Sentinel, the audit - with only the language model replaced by the case's script. Each case also
gets checks it cannot skip (agent_evals/notes.py): nothing changed directly, one draft per finished
run, every stored line honest when checked again from the transcript, nothing private shown to the
model, every proposal a buyer-memory ASSUMPTION or the one follow-up task.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from agent_evals import notes as eval_notes
from agent_evals.cases import Case, dataset_hash, load_cases
from agent_evals.scoring import CaseResult, build_scorecard
from app.modules.agents import api as agents_api
from app.modules.buyer_memory.models import BuyerMemoryItem
from app.modules.call_notes import answer as notes_answer
from app.modules.call_notes import proposals, rules, service
from tests.db.agent_eval_support import explain, play_call_notes
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "agents"
NOTES = [case for case in load_cases(CASES_DIR) if case.agent == "call_notes"]
BY_ID = {case.id: case for case in NOTES}
HAPPY = "notes-drafts-the-checklist-from-the-transcript"
INVENTED = "notes-an-invented-quote-becomes-unknown"
SWITCHED_OFF = "notes-switched-off-stops-before-the-model"
SUGGESTS = "notes-a-suggestion-is-an-assumption-never-a-fact"
POISONED = "notes-a-poisoned-transcript-is-reported-and-changes-nothing"


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
    assert len(NOTES) >= 25
    outcomes = {case.expect.outcome for case in NOTES}
    assert {
        "nothing_changed",
        "proposal_pending",
        "refused",
        "not_found",
        "agent_off",
        "over_budget",
    } <= outcomes
    # The cases a real model may also play: honest calls, the poisoned transcript. Forced bad
    # answers are scripted only.
    live = {case.id for case in NOTES if case.live}
    assert live == {
        HAPPY,
        "notes-meddic-uses-its-own-fields",
        "notes-hindi-quote-stays-in-hindi",
        "notes-telugu-quote-stays-in-telugu",
        POISONED,
    }
    languages = {m for case in NOTES for m in case.messages}
    assert {"{{call.hindi}}", "{{call.telugu}}", "{{call.poisoned}}"} <= languages


@pytest.mark.parametrize("case", NOTES, ids=lambda case: case.id)
def test_a_call_notes_case_passes(case: Case, db_session: Session, world: World) -> None:
    result, _ = play_call_notes(db_session, world, case)
    assert result.passed, explain(result)


def test_the_whole_dataset_scores_clean_in_one_transaction(
    db_session: Session, world: World
) -> None:
    # A case must leave nothing behind for the next.
    results: list[CaseResult] = [play_call_notes(db_session, world, c)[0] for c in NOTES]
    card = build_scorecard(results, provider="fake", dataset_sha256=dataset_hash(CASES_DIR))
    assert card.total == len(NOTES)
    assert card.all_passed, card.to_json()
    assert card.tool_precision == 1.0 and card.tool_recall == 1.0


def test_the_tool_in_the_cases_is_the_real_tool() -> None:
    assert notes_answer.TOOL_NAME == "submit_notes"
    assert {c.name for case in NOTES for c in case.script[0].calls} <= {
        "submit_notes",
        "approve_everything",
    }


# --- the gate can fail ---------------------------------------------------------------------------


def test_a_wrong_expected_state_fails_the_case(db_session: Session, world: World) -> None:
    case = variant(HAPPY, **{"expect.notes.states": {"budget": "unknown"}})
    assert play_call_notes(db_session, world, case)[0].passed is False


def test_a_changed_number_in_the_expected_value_fails_the_case(
    db_session: Session, world: World
) -> None:
    # The checklist must hold the buyer's words, not a number made from them.
    case = variant(HAPPY, **{"expect.notes.values": {"budget": "1.5 crore"}})
    assert play_call_notes(db_session, world, case)[0].passed is False


def test_a_missing_proposal_is_caught(db_session: Session, world: World) -> None:
    case = variant(SUGGESTS, **{"expect.proposals": []})
    assert play_call_notes(db_session, world, case)[0].passed is False


def test_a_service_that_writes_the_buyer_memory_itself_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = service.run_notes

    def and_writes_a_fact(
        session: Session, principal: Any, model: Any, lead: Any, call: Any, **kw: Any
    ):  # noqa: ANN202
        result = real(session, principal, model, lead, call, **kw)
        session.add(
            BuyerMemoryItem(
                tenant_id=principal.tenant_id,
                lead_id=lead,
                recorded_by_user_id=principal.user_id,
                key="budget",
                value="written by the service",
                status="assumption",
                reason="x",
            )
        )
        session.flush()
        return result

    monkeypatch.setattr(service, "run_notes", and_writes_a_fact)
    result, _ = play_call_notes(db_session, world, BY_ID[HAPPY])
    assert result.passed is False
    assert any(c.name == "no_direct_change" and not c.passed for c in result.checks)


def test_a_service_that_forgets_the_audit_entry_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "record_audit", lambda *a, **k: None)
    result, _ = play_call_notes(db_session, world, BY_ID[HAPPY])
    assert result.passed is False
    assert any(c.name == "runs_audited" and not c.passed for c in result.checks)


def test_a_service_that_ignores_the_registry_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without the registry gate a switched-off agent still calls the model.
    monkeypatch.setattr(agents_api, "governed", lambda model, *a, **k: model)
    result, _ = play_call_notes(db_session, world, BY_ID[SWITCHED_OFF])
    assert result.passed is False


def test_a_service_that_skips_the_quote_check_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without the check an invented quote is stored as if it were said.
    def keeps_everything(framework: str, claims: Any, notes: Any, segments: Any) -> Any:
        lines = [
            rules.Line(c.field, c.state, c.value, c.quote, c.start_ms, c.end_ms, c.reason, None)
            if c.state != "unknown"
            else rules.Line(c.field, "unknown", None, None, None, None, None, None)
            for c in claims
        ]
        return rules.Verified(lines, 0, 0, [])

    monkeypatch.setattr(rules, "verify", keeps_everything)
    result, _ = play_call_notes(db_session, world, BY_ID[INVENTED])
    assert result.passed is False
    assert any(c.name in ("lines_honest", "notes") and not c.passed for c in result.checks)


def test_a_service_that_shows_the_model_the_lead_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = notes_answer.transcript_message

    def with_the_name(segments: Any) -> str:
        return real(segments) + "\nThe buyer is Zxqplorn."

    monkeypatch.setattr(notes_answer, "transcript_message", with_the_name)
    result, _ = play_call_notes(db_session, world, BY_ID[HAPPY])
    assert result.passed is False
    assert any(c.name == "model_saw_nothing_private" and not c.passed for c in result.checks)


def test_a_service_that_stores_a_link_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_clean = rules.screen  # type: ignore[attr-defined]

    monkeypatch.setattr(
        rules,
        "screen",
        lambda text, **kw: real_clean(
            text, strip_links=False, **{k: v for k, v in kw.items() if k != "strip_links"}
        ),
    )
    result, _ = play_call_notes(db_session, world, BY_ID["notes-a-link-in-the-answer-is-cleaned"])
    assert result.passed is False


def test_a_proposal_for_a_fact_is_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A proposal that carries a status or a source is not an assumption any more.
    real = proposals.propose

    def with_a_status(
        session: Session, principal: Any, lead: Any, call: Any, version: Any, **kw: Any
    ):  # noqa: ANN202
        done = real(session, principal, lead, call, version, **kw)
        from app.modules.approvals.models import AgentAction

        for outcome in done.outcomes:
            if outcome.proposal_id is not None:
                action = session.get(AgentAction, outcome.proposal_id)
                if action is not None:
                    action.payload = {**(action.payload or {}), "status": "fact"}
        session.flush()
        return done

    monkeypatch.setattr(proposals, "propose", with_a_status)
    result, _ = play_call_notes(db_session, world, BY_ID[SUGGESTS])
    assert result.passed is False
    assert any(c.name in ("proposal_shape", "proposals") and not c.passed for c in result.checks)


def test_an_honest_case_reports_what_it_stored(db_session: Session, world: World) -> None:
    # (The case's savepoint is rolled back when it ends, so only what the run reported remains.)
    result, run = play_call_notes(db_session, world, BY_ID[HAPPY])
    assert result.passed, explain(result)
    assert run.runs == 1 and len(run.note_ids) == 1 and run.proposal_ids == []
    assert eval_notes.MEMORY_KIND == "buyer_memory.add_assumption"
