# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Approval queue for AI-proposed actions (ADR 0014, step AP1), through the service layer.

The AI may only PROPOSE; a sales manager or tenant admin approves; the change then runs through
the owning module's api.py as the approver, in one locked transaction, with audit. Nobody
approves their own proposal. People come from test_quotes_api.py: tenant alpha has admin,
manager, manager2, agent1 (owns A1, C1), agent2 (owns A2, C2), support, customers; tenant beta
has admin and agent.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission, Role, permissions_for
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.modules.activities.models import Activity
from app.modules.approvals import service
from app.modules.approvals.models import AgentAction
from app.modules.identity.models import User
from app.modules.leads.models import Lead
from tests.auth_helpers import TEST_ISSUER
from tests.db.conftest import bind_principal, setup_lead_context
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

ROLES = {
    "alpha.admin": Role.TENANT_ADMIN,
    "alpha.manager": Role.SALES_MANAGER,
    "alpha.manager2": Role.SALES_MANAGER,
    "alpha.agent1": Role.SALES_AGENT,
    "alpha.agent2": Role.SALES_AGENT,
    "alpha.support": Role.SUPPORT_AGENT,
    "alpha.customer": Role.CUSTOMER,
    "beta.admin": Role.TENANT_ADMIN,
    "beta.agent": Role.SALES_AGENT,
}


def principal_for(
    user: User, role: Role, permissions: frozenset[Permission] | None = None
) -> Principal:
    return Principal(
        subject=user.idp_subject,
        issuer=TEST_ISSUER,
        user_type="customer" if role == Role.CUSTOMER else "staff",
        roles=frozenset({role}),
        permissions=permissions if permissions is not None else permissions_for(frozenset({role})),
        user_id=user.id,
        tenant_id=user.tenant_id,
        display_name=user.display_name,
    )


class Acting:
    """Calls the service as one person, with the RLS context a request would have."""

    def __init__(self, session: Session, world: World) -> None:
        self.session, self.world = session, world

    def who(self, name: str) -> Principal:
        principal = principal_for(self.world.users[name], ROLES[name])
        bind_principal(self.session, principal)
        return principal

    def propose(self, name: str, **values: Any) -> AgentAction:
        values.setdefault("agent", "staff_assistant")
        values.setdefault("reason", "The buyer answered the call and wants a site visit.")
        return service.propose(self.session, self.who(name), **values)

    def approve(self, name: str, action: AgentAction, **values: Any) -> AgentAction:
        values.setdefault("version", action.version)
        return service.approve(self.session, self.who(name), action.id, **values)

    def reject(self, name: str, action: AgentAction, note: str = "Not yet.") -> AgentAction:
        return service.reject(
            self.session, self.who(name), action.id, version=action.version, note=note
        )


@pytest.fixture
def acting(db_session: Session, world: World) -> Acting:
    return Acting(db_session, world)


def alpha(world: World) -> uuid.UUID:
    return world.users["alpha.admin"].tenant_id


def add_lead(db_session: Session, world: World, owner: str | None = "alpha.agent1") -> Lead:
    owner_id = world.users[owner].id if owner else None
    setup_lead_context(db_session, alpha(world), owner_id)
    lead = Lead(tenant_id=alpha(world), first_name="Asha", last_name="Rao", owner_id=owner_id)
    db_session.add(lead)
    db_session.flush()
    return lead


def status_proposal(lead: Lead, status: str = "contacted") -> dict[str, Any]:
    return {"kind": "lead.set_status", "target_id": lead.id, "payload": {"status": status}}


def reload_lead(db_session: Session, world: World, lead: Lead) -> Lead:
    setup_lead_context(db_session, alpha(world), scope="all")
    db_session.refresh(lead)
    return lead


def audits(db_session: Session, world: World, action: str) -> list[AuditLog]:
    setup_lead_context(db_session, alpha(world), scope="all")
    return list(db_session.scalars(select(AuditLog).where(AuditLog.action == action)))


# --- proposing ------------------------------------------------------------------------------


def test_a_proposal_waits_and_changes_nothing(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    before = datetime.now(UTC)
    action = acting.propose("alpha.agent1", **status_proposal(lead))

    assert action.status == "pending"
    assert (action.kind, action.target_type, action.target_id) == (
        "lead.set_status",
        "lead",
        lead.id,
    )
    assert action.payload == {"status": "contacted"}
    assert action.requested_by_user_id == world.users["alpha.agent1"].id
    assert action.agent == "staff_assistant"
    assert action.decided_at is None and action.decided_by_user_id is None
    assert timedelta(days=6, hours=23) < action.expires_at - before <= timedelta(days=7, hours=1)
    assert reload_lead(db_session, world, lead).status == "new"  # nothing happened yet
    [audit] = audits(db_session, world, "agent_action.proposed")
    assert audit.entity_id == action.id


def test_the_expiry_can_be_shorter(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead), expires_in_days=1)
    assert action.expires_at - datetime.now(UTC) < timedelta(days=1, hours=1)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "lead.delete"},  # not in the catalogue
        {"kind": "sql"},
        {"payload": {"status": "converted"}},  # only through conversion, never by the AI
        {"payload": {"status": "won"}},
        {"payload": {"status": "contacted", "owner_id": str(uuid.uuid4())}},  # nothing extra
        {"payload": {}},
        {"reason": ""},
        {"reason": "x" * 501},
        {"agent": "somebody_else"},
    ],
)
def test_invalid_proposals_are_refused(acting, db_session, world, changes) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(DomainError) as refused:
        acting.propose("alpha.agent1", **{**status_proposal(lead), **changes})
    assert refused.value.status_code == 422


def test_unknown_and_invalid_have_stable_codes(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(DomainError) as unknown:
        acting.propose("alpha.agent1", **{**status_proposal(lead), "kind": "lead.delete"})
    assert unknown.value.code == "unknown_agent_action"
    with pytest.raises(DomainError) as invalid:
        acting.propose("alpha.agent1", **status_proposal(lead, "won"))
    assert invalid.value.code == "invalid_agent_action"


def test_the_requester_must_see_the_record(acting, db_session, world) -> None:
    theirs = add_lead(db_session, world, owner="alpha.agent2")
    with pytest.raises(NotFoundError):  # another agent's lead: as if it didn't exist
        acting.propose("alpha.agent1", **status_proposal(theirs))
    with pytest.raises(NotFoundError):  # another organisation
        acting.propose("beta.admin", **status_proposal(theirs))
    with pytest.raises(NotFoundError):  # an invented id
        acting.propose(
            "alpha.manager",
            kind="lead.set_status",
            target_id=uuid.uuid4(),
            payload={"status": "contacted"},
        )
    with pytest.raises(NotFoundError):  # support staff don't see leads
        acting.propose("alpha.support", **status_proposal(theirs))


def test_customers_can_never_propose(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(ForbiddenError):
        acting.propose("alpha.customer", **status_proposal(lead))


# --- approving --------------------------------------------------------------------------------


def test_a_manager_approves_and_the_change_runs_through_the_leads_rules(
    acting, db_session, world
) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    done = acting.approve("alpha.manager", action, note="Agreed.")

    assert done.status == "approved"
    assert done.decided_by_user_id == world.users["alpha.manager"].id
    assert done.decided_at is not None and done.decision_note == "Agreed."
    assert done.result
    assert reload_lead(db_session, world, lead).status == "contacted"
    [approved] = audits(db_session, world, "agent_action.approved")
    assert approved.actor_subject == world.users["alpha.manager"].idp_subject
    assert approved.changes["kind"] == "lead.set_status"
    assert approved.changes["requested_by"] == str(world.users["alpha.agent1"].id)
    # ...and the leads module audited the change itself, as done by the approver.
    [changed] = audits(db_session, world, "lead.status_changed")
    assert changed.actor_subject == world.users["alpha.manager"].idp_subject


def test_nobody_approves_their_own_proposal(acting, db_session, world) -> None:
    lead = add_lead(db_session, world, owner="alpha.manager")
    action = acting.propose("alpha.manager", **status_proposal(lead))
    with pytest.raises(ForbiddenError) as own:
        acting.approve("alpha.manager", action)
    assert own.value.code == "self_approval_forbidden"
    with pytest.raises(ForbiddenError):
        acting.reject("alpha.manager", action)

    admins = acting.propose("alpha.admin", **status_proposal(lead, "qualified"))
    with pytest.raises(ForbiddenError):  # admins too
        acting.approve("alpha.admin", admins)

    assert acting.approve("alpha.manager2", action).status == "approved"


def test_the_database_also_refuses_self_approval(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(
            update(AgentAction)
            .where(AgentAction.id == action.id)
            .values(decided_by_user_id=action.requested_by_user_id)
        )


def test_proposals_are_history_and_cannot_be_deleted(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    with pytest.raises(DBAPIError, match="permission denied"), db_session.begin_nested():
        db_session.execute(text("DELETE FROM agent_actions WHERE id = :id"), {"id": action.id})


def test_only_approvers_may_decide(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    for name in ("alpha.agent2", "alpha.support"):
        with pytest.raises((ForbiddenError, NotFoundError)):
            acting.approve(name, action)
    with pytest.raises(NotFoundError):  # another organisation: as if it didn't exist
        acting.approve("beta.admin", action)
    assert reload_lead(db_session, world, lead).status == "new"


def test_who_may_read_a_proposal(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    session = acting.session
    assert service.get_action(session, acting.who("alpha.agent1"), action.id).id == action.id
    assert service.get_action(session, acting.who("alpha.manager"), action.id).id == action.id
    for name in ("alpha.agent2", "beta.admin", "alpha.customer"):
        with pytest.raises((NotFoundError, ForbiddenError)):
            service.get_action(session, acting.who(name), action.id)
    with pytest.raises(NotFoundError):
        service.get_action(session, acting.who("alpha.manager"), uuid.uuid4())


def test_a_decision_is_made_once(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    stale_version = action.version
    acting.approve("alpha.manager", action)
    with pytest.raises(ConflictError) as again:
        acting.approve("alpha.manager2", action, version=action.version)
    assert again.value.code == "agent_action_already_decided"
    with pytest.raises(ConflictError):
        acting.reject("alpha.manager2", action)

    other = acting.propose("alpha.agent1", **status_proposal(lead, "qualified"))
    with pytest.raises(ConflictError) as stale:
        acting.approve("alpha.manager", other, version=other.version + 1)
    assert stale.value.code == "agent_action_changed"
    assert stale_version == 1


def test_an_expired_proposal_cannot_be_approved(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    db_session.execute(
        update(AgentAction)
        .where(AgentAction.id == action.id)
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    db_session.refresh(action)
    with pytest.raises(ConflictError) as expired:
        acting.approve("alpha.manager", action)
    assert expired.value.code == "agent_action_expired"
    assert reload_lead(db_session, world, lead).status == "new"


def test_a_failing_action_changes_nothing_and_is_marked_failed(acting, db_session, world):
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead, "contacted"))
    # Meanwhile someone moves the lead on by hand: "contacted" -> "contacted" is not allowed.
    bind_principal(db_session, principal_for(world.users["alpha.manager"], Role.SALES_MANAGER))
    from app.modules.leads import api as leads_api

    leads_api.set_lead_status(
        db_session, acting.who("alpha.manager"), lead.id, "contacted", "Called"
    )
    done = acting.approve("alpha.manager2", action)
    assert done.status == "failed"
    assert "contacted" in (done.result or "")
    assert reload_lead(db_session, world, lead).status == "contacted"
    assert audits(db_session, world, "agent_action.failed")


def test_an_approver_who_cannot_see_the_record_changes_nothing(acting, db_session, world):
    lead = add_lead(db_session, world, owner="alpha.agent1")
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    # An approver whose own rights only cover their own leads (not a built-in role today).
    narrow = principal_for(
        world.users["alpha.manager"],
        Role.SALES_MANAGER,
        frozenset({Permission.AGENT_ACTION_APPROVE, Permission.LEAD_READ_OWN}),
    )
    from app.core.db import bind_user

    bind_principal(db_session, narrow)
    bind_user(db_session, world.users["alpha.manager"].id, "own")
    with pytest.raises(NotFoundError):
        service.approve(db_session, narrow, action.id, version=action.version)
    db_session.refresh(action)
    assert action.status == "pending"
    assert reload_lead(db_session, world, lead).status == "new"


# --- rejecting --------------------------------------------------------------------------------


def test_a_rejection_needs_a_note_and_changes_nothing(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    action = acting.propose("alpha.agent1", **status_proposal(lead))
    with pytest.raises(DomainError) as empty:
        acting.reject("alpha.manager", action, note="  ")
    assert empty.value.status_code == 422
    done = acting.reject("alpha.manager", action, note="Call them first.")
    assert (done.status, done.decision_note) == ("rejected", "Call them first.")
    assert reload_lead(db_session, world, lead).status == "new"
    assert audits(db_session, world, "agent_action.rejected")


# --- the other kinds --------------------------------------------------------------------------


def test_an_assignment_proposal(acting, db_session, world) -> None:
    lead = add_lead(db_session, world, owner=None)
    agent2 = world.users["alpha.agent2"].id
    for wrong in ("alpha.support", "beta.agent", "alpha.customer"):  # not assignable here
        with pytest.raises(DomainError) as refused:
            acting.propose(
                "alpha.manager",
                kind="lead.assign",
                target_id=lead.id,
                payload={"owner_id": str(world.users[wrong].id)},
            )
        assert refused.value.code == "invalid_agent_action"
    action = acting.propose(
        "alpha.manager", kind="lead.assign", target_id=lead.id, payload={"owner_id": str(agent2)}
    )
    acting.approve("alpha.admin", action)
    assert reload_lead(db_session, world, lead).owner_id == agent2


def test_a_follow_up_task_on_a_contact(acting, db_session, world) -> None:
    contact_id = world.ids["C1"]
    action = acting.propose(
        "alpha.agent1",
        kind="activity.create_task",
        target_type="contact",
        target_id=contact_id,
        payload={"subject": "Send the brochure", "due_in_days": 2},
    )
    assert action.target_type == "contact"
    acting.approve("alpha.manager", action)
    bind_principal(db_session, principal_for(world.users["alpha.manager"], Role.SALES_MANAGER))
    [task] = db_session.scalars(select(Activity).where(Activity.contact_id == contact_id)).all()
    assert task.kind == "task" and task.subject == "Send the brochure"
    assert task.assignee_id == world.users["alpha.agent1"].id  # defaults to the requester
    assert task.due_at is not None


@pytest.mark.parametrize(
    "target_type, key",
    [("contact", "C2"), ("account", "A2"), ("deal", "O1")],
)
def test_task_targets_must_be_visible_and_supported(
    acting, db_session, world, target_type, key
) -> None:
    with pytest.raises(DomainError) as refused:
        acting.propose(
            "alpha.agent1",
            kind="activity.create_task",
            target_type=target_type,
            target_id=world.ids[key],
            payload={"subject": "Call", "due_in_days": 1},
        )
    # Another agent's contact/account: 404; a deal isn't a supported target: 422.
    assert refused.value.status_code == (422 if target_type == "deal" else 404)
