# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The verification artifact in propose() and approve() (ADR 0018, step VA1), against the real
database: the plan stored with a proposal, and the outcome written when it is approved."""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import null, select, update

from app.core.audit import AuditLog
from app.modules.approvals import artifact, service
from app.modules.approvals.service import ProposalBlockedError
from app.modules.leads import api as leads_api
from app.modules.leads.models import Lead
from tests.db.conftest import setup_lead_context
from tests.db.test_approvals import (
    acting,  # noqa: F401 - fixture used by name
    add_lead,
    alpha,
    audits,
    reload_lead,
    status_proposal,
)
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name


def assign(lead: Lead, owner_id: uuid.UUID) -> dict[str, Any]:
    return {"kind": "lead.assign", "target_id": lead.id, "payload": {"owner_id": str(owner_id)}}


def task(target_id: uuid.UUID, target_type: str = "lead", **extra: Any) -> dict[str, Any]:
    payload = {"subject": "Call the buyer", "due_in_days": 2, **extra}
    return {
        "kind": "activity.create_task",
        "target_id": target_id,
        "target_type": target_type,
        "payload": payload,
    }


def changes_of(action: Any) -> list[dict[str, Any]]:
    return list(action.verification["spec"]["changes"])


# --- the plan is stored with the proposal ------------------------------------------------------


def test_a_status_proposal_stores_what_will_change(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    assert action.verification["version"] == 2
    assert changes_of(action) == [{"field": "status", "before": "new", "after": "contacted"}]


def test_the_basis_is_the_record_as_it_was_when_the_proposal_was_made(
    acting, db_session, world
) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    assert action.verification["spec"]["basis"] == {
        "record_version": lead.version,
        "status": "new",
        "owner_id": str(world.users["alpha.agent1"].id),
    }


def test_an_assignment_stores_the_old_and_the_new_owner(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    colleague = world.users["alpha.agent2"].id
    action = acting.propose("alpha.manager", **assign(lead, colleague))
    assert changes_of(action) == [
        {
            "field": "owner_id",
            "before": str(world.users["alpha.agent1"].id),
            "after": str(colleague),
        }
    ]


def test_an_unassigned_lead_has_no_old_owner(acting, db_session, world) -> None:
    lead = add_lead(db_session, world, owner=None)
    action = acting.propose("alpha.manager", **assign(lead, world.users["alpha.agent2"].id))
    assert changes_of(action)[0]["before"] is None


def test_a_task_proposal_stores_the_new_task_and_who_it_is_for(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **task(lead.id))
    [change] = changes_of(action)
    assert change["field"] == "task" and change["before"] is None
    assert change["after"] == {
        "subject": "Call the buyer",
        "due_in_days": 2,
        "assignee_id": str(world.users["alpha.agent1"].id),  # nobody named: the asker
    }


def test_a_task_for_a_colleague_names_the_colleague(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    support = world.users["alpha.support"].id
    action = acting.propose("alpha.agent1", **task(lead.id, assignee_id=str(support)))
    assert changes_of(action)[0]["after"]["assignee_id"] == str(support)


def test_a_task_for_an_account_has_no_record_state_in_its_basis(acting, db_session, world) -> None:
    action = acting.propose("alpha.agent1", **task(world.ids["A1"], "account"))
    assert action.verification["spec"]["basis"] == {}
    assert changes_of(action)[0]["field"] == "task"


def test_the_artifact_keeps_the_sentinels_findings(acting, db_session, world) -> None:
    lead = add_lead(db_session, world, "alpha.agent2")
    action = acting.propose("alpha.manager", **assign(lead, world.users["alpha.agent1"].id))
    assert [w["code"] for w in action.verification["warnings"]] == ["lead_owned_by_other"]
    assert {"words", "pattern", "state", "tenant"} <= set(action.verification["checked"])


def test_the_artifact_holds_no_names(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.manager", **assign(lead, world.users["alpha.agent2"].id))
    text = json.dumps(action.verification)
    for user in world.users.values():
        assert user.display_name not in text
    assert "Asha" not in text and "Rao" not in text  # the lead's own name is not stored either


def test_a_plan_that_cannot_be_prepared_refuses_the_proposal(
    acting, db_session, world, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.approvals import catalogue

    lead = add_lead(db_session, world)

    def broken(*args: Any, **kwargs: Any) -> list[Any]:
        raise RuntimeError("boom with a secret text")

    kind = catalogue.KINDS["lead.set_status"]
    monkeypatch.setitem(catalogue.KINDS, "lead.set_status", _with_spec(kind, broken))
    with pytest.raises(ProposalBlockedError) as caught:
        acting.propose("alpha.agent1", **status_proposal(lead))
    assert caught.value.codes == ["artifact_error"] and "secret" not in caught.value.detail


def _with_spec(kind: Any, spec: Any) -> Any:
    from dataclasses import replace

    return replace(kind, spec=spec)


# --- the outcome is written when the proposal is approved --------------------------------------


def test_an_approved_status_change_matches_its_plan(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    done = acting.approve("alpha.manager", action)
    outcome = done.verification["outcome"]
    assert outcome["ran"] is True and outcome["matches_spec"] is True and outcome["differs"] == []
    assert outcome["ran_as"] == str(world.users["alpha.manager"].id)
    assert outcome["seen"] == [{"field": "status", "after": "contacted"}]
    assert done.verification["spec"] == action.verification["spec"]  # the plan is kept as it was
    assert reload_lead(db_session, world, lead).status == "contacted"


def test_an_approved_assignment_matches_its_plan(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    colleague = world.users["alpha.agent2"].id
    done = acting.approve("alpha.admin", acting.propose("alpha.manager", **assign(lead, colleague)))
    assert done.verification["outcome"]["matches_spec"] is True
    assert done.verification["outcome"]["seen"] == [{"field": "owner_id", "after": str(colleague)}]


def test_an_approved_task_matches_its_plan(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **task(lead.id))
    done = acting.approve("alpha.manager", action)
    outcome = done.verification["outcome"]
    assert outcome["matches_spec"] is True and outcome["differs"] == []
    [seen] = outcome["seen"]
    assert seen["field"] == "task" and seen["after"] == changes_of(action)[0]["after"]


def test_an_action_that_ran_differently_is_recorded_as_a_mismatch(
    acting, db_session, world, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owning module says "done" but the record did not change as announced."""
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    monkeypatch.setattr(leads_api, "set_lead_status", lambda *args, **kwargs: None)
    done = acting.approve("alpha.manager", action)
    assert done.status == "approved"  # it ran; what is recorded is that it differed
    outcome = done.verification["outcome"]
    assert outcome["matches_spec"] is False and outcome["differs"] == ["status"]
    assert outcome["seen"] == [{"field": "status", "after": "new"}]
    [row] = audits(db_session, world, "agent_action.mismatch")
    assert row.entity_id == action.id and row.changes["differs"] == ["status"]
    assert "Asha" not in str(row.changes)


def test_a_matching_approval_writes_no_mismatch_audit(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    acting.approve("alpha.manager", acting.propose("alpha.agent1", **status_proposal(lead)))
    assert audits(db_session, world, "agent_action.mismatch") == []


def test_a_proposal_that_failed_says_it_did_not_run(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    setup_lead_context(db_session, alpha(world), scope="all")
    db_session.execute(update(Lead).where(Lead.id == lead.id).values(status="contacted"))
    db_session.flush()
    done = acting.approve("alpha.manager", action)  # the Sentinel's re-check refuses it
    assert done.status == "failed"
    assert done.verification["outcome"] == {
        "ran": False,
        "ran_as": str(world.users["alpha.manager"].id),
        "seen": [],
        "matches_spec": None,
        "differs": [],
    }


def test_a_rejected_proposal_has_no_outcome(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    rejected = acting.reject(
        "alpha.manager", acting.propose("alpha.agent1", **status_proposal(lead))
    )
    assert "outcome" not in rejected.verification


def test_a_proposal_made_before_artifacts_still_works(acting, db_session, world) -> None:
    """Old rows have no plan (version 1 or nothing): they are approved as before and say so."""
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    action.verification = {"version": 1, "checked": ["words"], "warnings": []}
    db_session.flush()
    done = acting.approve("alpha.manager", action)
    assert done.status == "approved"
    outcome = done.verification["outcome"]
    assert outcome["matches_spec"] is None and outcome["ran"] is True
    assert outcome["seen"] == [{"field": "status", "after": "contacted"}]
    assert "spec" not in done.verification


def test_a_proposal_without_any_verification_is_approved_too(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    action.verification = null()  # SQL NULL, as rows from before migration 0044 have
    db_session.flush()
    db_session.refresh(action)
    assert action.verification is None
    done = acting.approve("alpha.manager", action)
    assert done.status == "approved" and done.verification["outcome"]["matches_spec"] is None


def test_the_stored_artifact_is_valid_json_the_database_accepts(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    db_session.expire(action)
    assert isinstance(action.verification, dict) and action.verification["version"] == 2
    assert artifact.STORED_VERSION == 2
    rows = db_session.scalars(select(AuditLog).where(AuditLog.action == "agent_action.proposed"))
    assert "spec" not in str([r.changes for r in rows])  # the audit entry stays small
    assert service.ENTITY == "agent_action"
