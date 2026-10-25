# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Agent evaluation harness (BP-10, step EV3): the customer portal assistant, played for real.

Every case in evals/agents/portal_assistant.json runs through the REAL portal assistant - real
tools, the customer's real access to accounts, the real test database - with only the language
model replaced by the case's script. A failing case fails the pull request.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from agent_evals.cases import Case, dataset_hash, load_cases
from agent_evals.scoring import CaseResult, build_scorecard
from app.modules.accounts import api as accounts_api
from app.modules.assistant import tools as portal_tools
from tests.db.agent_eval_support import explain, play_portal
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "agents"
PORTAL = [case for case in load_cases(CASES_DIR) if case.agent == "portal_assistant"]
BY_ID = {case.id: case for case in PORTAL}


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


def test_there_are_portal_cases() -> None:
    assert len(PORTAL) >= 8


@pytest.mark.parametrize("case", PORTAL, ids=lambda case: case.id)
def test_a_portal_case_passes(case: Case, db_session: Session, world: World) -> None:
    result, _ = play_portal(db_session, world, case)
    assert result.passed, explain(result)


def test_the_whole_portal_dataset_scores_clean(db_session: Session, world: World) -> None:
    results: list[CaseResult] = [play_portal(db_session, world, case)[0] for case in PORTAL]
    card = build_scorecard(results, provider="fake", dataset_sha256=dataset_hash(CASES_DIR))
    assert card.total == len(PORTAL)
    assert card.all_passed, card.to_json()
    assert card.tool_precision == 1.0 and card.tool_recall == 1.0


# --- the gate can fail ---------------------------------------------------------------------------


def test_a_wrong_expectation_fails_the_case(db_session: Session, world: World) -> None:
    case = variant(
        "portal-propose-ticket", **{"expect.tools.0.arguments.subject": "Something else"}
    )
    result, _ = play_portal(db_session, world, case)
    assert result.passed is False


def test_a_claim_that_the_ticket_exists_is_caught(db_session: Session, world: World) -> None:
    case = variant(
        "portal-propose-ticket", **{"script.1.say": "Done - the ticket has been created for you."}
    )
    result, _ = play_portal(db_session, world, case)
    assert result.passed is False
    assert result.claimed_done is True


def test_a_staff_tool_added_by_mistake_would_be_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If a lead-reading tool ever appeared among the customer's tools, the case that expects it
    # to be refused as unknown must fail.

    class SearchArgs(portal_tools.NoArgs):
        q: str = ""

    fake = portal_tools.Tool("search_leads", "oops", SearchArgs, lambda s, p, a: [])
    monkeypatch.setitem(portal_tools.TOOLS, "search_leads", fake)
    result, _ = play_portal(db_session, world, BY_ID["portal-staff-tool-refused"])
    assert result.passed is False


def test_broken_account_access_would_be_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the check "may this customer see this account?" stopped working, a ticket for someone
    # else's account would be prepared - and the "not found" case must fail.
    monkeypatch.setattr(accounts_api, "is_readable_account", lambda *args, **kwargs: True)
    result, _ = play_portal(db_session, world, BY_ID["portal-ticket-other-account-not-found"])
    assert result.passed is False
