# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Agent evaluation harness (BP-10, step EV3): the public website chat, played for real.

Every case in evals/agents/public_chat.json runs through the REAL public chat service - the real
guardrails, the real save_lead tool, the real lead creation and the real test database - as an
anonymous visitor, with only the language model replaced by the case's script.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from agent_evals.cases import Case, dataset_hash, load_cases
from agent_evals.scoring import CaseResult, build_scorecard
from app.modules.public_chat import service as public_chat_service
from tests.db.agent_eval_support import explain, play_public
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "agents"
PUBLIC = [case for case in load_cases(CASES_DIR) if case.agent == "public_chat"]
BY_ID = {case.id: case for case in PUBLIC}


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


def test_there_are_public_chat_cases() -> None:
    assert len(PUBLIC) >= 8


@pytest.mark.parametrize("case", PUBLIC, ids=lambda case: case.id)
def test_a_public_chat_case_passes(case: Case, db_session: Session, world: World) -> None:
    result, _ = play_public(db_session, world, case)
    assert result.passed, explain(result)


def test_the_whole_public_chat_dataset_scores_clean(db_session: Session, world: World) -> None:
    results: list[CaseResult] = [play_public(db_session, world, case)[0] for case in PUBLIC]
    card = build_scorecard(results, provider="fake", dataset_sha256=dataset_hash(CASES_DIR))
    assert card.total == len(PUBLIC)
    assert card.all_passed, card.to_json()
    assert card.tool_precision == 1.0 and card.tool_recall == 1.0


# --- the gate can fail ---------------------------------------------------------------------------


def test_a_wrong_expectation_fails_the_case(db_session: Session, world: World) -> None:
    case = variant("public-save-lead", **{"expect.tools.0.arguments.full_name": "Somebody Else"})
    result, _ = play_public(db_session, world, case)
    assert result.passed is False


def test_a_lead_saved_where_none_was_expected_is_caught(db_session: Session, world: World) -> None:
    # The case says a greeting saves nothing; if the script saved a lead anyway, it must fail.
    save = {"name": "save_lead", "arguments": {"full_name": "Eve Visitor", "phone": "98480 12345"}}
    case = variant("public-greeting-only", script=[{"calls": [save]}, {"say": "Thanks!"}])
    result, _ = play_public(db_session, world, case)
    assert result.passed is False


def test_a_second_lead_in_one_conversation_would_be_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the "one lead per conversation" rule stopped working, two leads would be saved.
    real = public_chat_service._save_lead

    def forgetful(session: Any, tenant_id: Any, conversation: Any, arguments: Any) -> Any:
        conversation.lead_id = None
        return real(session, tenant_id, conversation, arguments)

    monkeypatch.setattr(public_chat_service, "_save_lead", forgetful)
    result, _ = play_public(db_session, world, BY_ID["public-one-lead-per-conversation"])
    assert result.passed is False
    assert "leads_created" in explain(result)
