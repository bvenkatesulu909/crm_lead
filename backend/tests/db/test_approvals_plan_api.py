# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The plan and the outcome of a proposal in the normal read (ADR 0018, step VA3).

The same record-level rules as for the rest of the proposal: whoever may read it sees what it
will change and what happened, nobody else."""

from sqlalchemy import update

from tests.db.test_approvals_api import (  # noqa: F401 - fixtures used by name
    ACTIONS,
    add_lead,
    alpha,
    propose,
)
from tests.db.test_quotes_api import api, auth, ok, world  # noqa: F401


def test_a_pending_proposal_shows_what_it_would_change(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    action = propose(db_session, world, "alpha.agent1", lead)
    body = ok(api.get(f"{ACTIONS}/{action.id}", headers=auth("alpha.manager")))
    assert body["changes"] == [{"field": "status", "before": "new", "after": "contacted"}]
    assert body["outcome"] is None


def test_the_list_carries_the_plan_too(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    propose(db_session, world, "alpha.agent1", lead)
    items = ok(api.get(ACTIONS, headers=auth("alpha.manager")))["items"]
    assert items[0]["changes"][0]["field"] == "status"


def test_an_approved_proposal_shows_what_happened(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    action = propose(db_session, world, "alpha.agent1", lead)
    url = f"{ACTIONS}/{action.id}/approve"
    body = ok(api.post(url, json={"version": 1}, headers=auth("alpha.manager")))
    assert body["outcome"] == {
        "ran": True,
        "matches_plan": True,
        "differs": [],
        "seen": [{"field": "status", "after": "contacted"}],
    }
    assert body["changes"][0]["after"] == "contacted"  # the plan is kept as it was


def test_a_rejected_proposal_has_a_plan_and_no_outcome(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    action = propose(db_session, world, "alpha.agent1", lead)
    url = f"{ACTIONS}/{action.id}/reject"
    body = ok(api.post(url, json={"version": 1, "note": "No"}, headers=auth("alpha.manager")))
    assert body["changes"] and body["outcome"] is None


def test_an_old_proposal_without_a_plan_reads_as_empty(api, auth, world, db_session) -> None:
    from app.modules.approvals.models import AgentAction

    lead = add_lead(db_session, world)
    action = propose(db_session, world, "alpha.agent1", lead)
    db_session.execute(
        update(AgentAction)
        .where(AgentAction.id == action.id)
        .values(verification={"version": 1, "checked": [], "warnings": []})
    )
    db_session.flush()
    body = ok(api.get(f"{ACTIONS}/{action.id}", headers=auth("alpha.manager")))
    assert body["changes"] == [] and body["outcome"] is None


def test_someone_who_may_not_read_the_proposal_gets_no_plan(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    action = propose(db_session, world, "alpha.agent1", lead)
    for other in ("alpha.agent2", "beta.admin"):
        assert api.get(f"{ACTIONS}/{action.id}", headers=auth(other)).status_code == 404
    assert alpha(world)
