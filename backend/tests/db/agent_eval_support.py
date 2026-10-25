"""Shared helpers for playing agent evaluation cases against the real test database (BP-10).

Builds the fictional world a case refers to (``{{lead.own}}`` ...) from the people and records of
``test_quotes_api.world``, plays a case through the real assistant as the right person, and adds
the checks only a database-level runner can make: nothing in the CRM changed directly, and what
the assistant proposed is really stored as pending proposals.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent_evals.cases import Case, substitute
from agent_evals.runner import StaffRun, run_staff_case
from agent_evals.scoring import CaseResult, Check, score_case, with_checks
from app.core.auth.principal import Principal
from app.modules.activities.models import Activity
from app.modules.approvals.models import AgentAction
from app.modules.leads.models import Lead
from tests.db.conftest import bind_principal, setup_lead_context
from tests.db.test_approvals import ROLES, principal_for
from tests.db.test_quotes_api import World

# Who plays each persona in the fictional test world (tenant "alpha").
PERSONA_USER = {
    "sales_agent": "alpha.agent1",
    "sales_manager": "alpha.manager",
    "support_agent": "alpha.support",
    "tenant_admin": "alpha.admin",
}
OTHER_AGENT = "alpha.agent2"


@dataclass(frozen=True)
class Snapshot:
    leads: dict[uuid.UUID, tuple[str, uuid.UUID | None, int]]
    activities: int
    actions: dict[uuid.UUID, str]


class EvalWorld:
    def __init__(self, session: Session, world: World) -> None:
        self.session = session
        self.world = world
        self.tenant_id = world.users["alpha.admin"].tenant_id

    def principal(self, persona: str) -> Principal:
        name = PERSONA_USER[persona]
        principal = principal_for(self.world.users[name], ROLES[name])
        bind_principal(self.session, principal)
        return principal

    def _lead(self, owner: str, last_name: str) -> uuid.UUID:
        owner_id = self.world.users[owner].id
        setup_lead_context(self.session, self.tenant_id, owner_id)
        lead = Lead(
            tenant_id=self.tenant_id, first_name="Eval", last_name=last_name, owner_id=owner_id
        )
        self.session.add(lead)
        self.session.flush()
        return lead.id

    def placeholders(self, persona: str) -> dict[str, str]:
        """What ``{{...}}`` stands for when this persona plays: records of the acting person,
        a record of someone else, and two colleagues."""
        acting = PERSONA_USER[persona]
        values = {
            "lead.own": str(self._lead(acting, "Own")),
            "lead.other": str(self._lead(OTHER_AGENT, "Other")),
            "user.agent2": str(self.world.users[OTHER_AGENT].id),
            "user.support": str(self.world.users["alpha.support"].id),
        }
        if acting == "alpha.agent1":  # the contacts of the test world belong to agent 1 and agent 2
            values["contact.own"] = str(self.world.ids["C1"])
            values["contact.other"] = str(self.world.ids["C2"])
        return values

    def snapshot(self) -> Snapshot:
        """Leads (as a manager sees them: all), activities and proposals of the tenant."""
        setup_lead_context(self.session, self.tenant_id, scope="all")
        leads = {
            row.id: (row.status, row.owner_id, row.version)
            for row in self.session.scalars(select(Lead).where(Lead.tenant_id == self.tenant_id))
        }
        activities = self.session.scalar(
            select(func.count()).select_from(Activity).where(Activity.tenant_id == self.tenant_id)
        )
        actions = {
            row.id: row.status
            for row in self.session.scalars(
                select(AgentAction).where(AgentAction.tenant_id == self.tenant_id)
            )
        }
        return Snapshot(leads, activities or 0, actions)


def invariants(
    before: Snapshot, after: Snapshot, run: StaffRun, principal: Principal
) -> list[Check]:
    """What must hold after ANY staff-assistant conversation, whatever the case says."""
    changed = [
        str(lead_id) for lead_id, state in before.leads.items() if after.leads.get(lead_id) != state
    ]
    direct = Check(
        "no_direct_change",
        not changed
        and after.activities == before.activities
        and len(after.leads) == len(before.leads),
        f"leads changed: {changed}; activities {before.activities} -> {after.activities}"
        if changed or after.activities != before.activities or len(after.leads) != len(before.leads)
        else "",
    )
    new = {i: s for i, s in after.actions.items() if i not in before.actions}
    stored = Check(
        "proposals_stored",
        set(new) == set(run.proposal_ids) and all(s == "pending" for s in new.values()),
        f"proposals reported {sorted(map(str, run.proposal_ids))}, stored {sorted(map(str, new))}"
        if set(new) != set(run.proposal_ids) or any(s != "pending" for s in new.values())
        else "",
    )
    return [direct, stored]


def play_staff(
    session: Session, world: World, case: Case, **limits: Any
) -> tuple[CaseResult, StaffRun]:
    """Play one staff-assistant case for real and score it, invariants included."""
    env = EvalWorld(session, world)
    principal = env.principal(case.persona)
    ready = substitute(case, env.placeholders(case.persona))
    bind_principal(session, principal)
    before = env.snapshot()
    bind_principal(session, principal)
    run = run_staff_case(session, principal, ready, **limits)
    session.flush()
    after = env.snapshot()
    bind_principal(session, principal)
    result = score_case(ready, run.trajectory)
    return with_checks(result, invariants(before, after, run, principal)), run


def explain(result: CaseResult) -> str:
    """A readable failure message for a failed case."""
    problems = [f"  {c.name}: {c.detail}" for c in result.checks if not c.passed]
    return f"case '{result.case_id}' failed:\n" + "\n".join(problems)
