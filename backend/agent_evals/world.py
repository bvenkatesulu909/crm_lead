"""The fictional world a case plays in (BP-10, step EV5).

One implementation for the CI tests (the test world) and the command-line tool (the demo data of
the development database). People are found BY ROLE inside an organisation, and the records a case
refers to (``{{lead.own}}``, ``{{contact.other}}`` ...) are created inside the current
transaction - the caller rolls it back, so nothing is kept.

Needed in the organisation: two sales agents, a sales manager, a support agent, a tenant admin, a
customer with access to at least one account. The "other" organisation (cited-answer isolation
cases) needs one staff member.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Role, permissions_for
from app.core.config import Settings
from app.core.db import bind_tenant, bind_user
from app.modules.accounts.models import Account
from app.modules.activities.models import Activity
from app.modules.approvals.models import AgentAction
from app.modules.assistant import guardrails
from app.modules.contacts.models import Contact
from app.modules.identity import api as identity_api
from app.modules.identity.models import PortalAccessGrant, Tenant, User
from app.modules.leads.models import Lead


class WorldError(RuntimeError):
    """The organisation doesn't have the people or records the cases need."""


def clean_id() -> uuid.UUID:
    """A new id the assistant's own input guardrail lets through.

    About 1 random id in 600 contains a digit run the card-number rule takes for a card, which
    would make a case fail now and then for no reason (a finding in docs/agent-evals.md). The
    cases are about the assistant's behaviour, so the records they talk about get a clean id."""
    while True:
        candidate = uuid.uuid4()
        if guardrails.inspect_input(str(candidate)).allowed:
            return candidate


@dataclass(frozen=True)
class Snapshot:
    leads: dict[uuid.UUID, tuple[str, uuid.UUID | None, int]]
    activities: int
    actions: dict[uuid.UUID, str]


# Persona -> (which organisation, how to find the person)
_STAFF_ROLE = {
    "sales_agent": Role.SALES_AGENT,
    "sales_manager": Role.SALES_MANAGER,
    "support_agent": Role.SUPPORT_AGENT,
    "tenant_admin": Role.TENANT_ADMIN,
}


class World:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        tenant_slug: str,
        other_tenant_slug: str | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.tenant_slug = tenant_slug
        self.tenant_id = self._tenant(tenant_slug)
        self.other_tenant_id = self._tenant(other_tenant_slug) if other_tenant_slug else None

    # --- organisations and people ----------------------------------------------------------

    def _tenant(self, slug: str) -> uuid.UUID:
        found = self.session.scalar(select(Tenant.id).where(Tenant.slug == slug))
        if found is None:
            raise WorldError(f"there is no organisation with the slug '{slug}'")
        return found

    def _people(self, tenant_id: uuid.UUID, user_type: str, role: str) -> list[User]:
        bind_tenant(self.session, tenant_id)
        rows = self.session.scalars(
            select(User)
            .where(
                User.tenant_id == tenant_id, User.user_type == user_type, User.is_active.is_(True)
            )
            .order_by(User.email)
        )
        return [u for u in rows if role in (u.roles or [])]

    def _person(self, tenant_id: uuid.UUID, user_type: str, role: str, index: int = 0) -> User:
        people = self._people(tenant_id, user_type, role)
        if len(people) <= index:
            raise WorldError(
                f"the organisation needs {index + 1} active {role} user(s) of type {user_type}; "
                f"it has {len(people)}"
            )
        return people[index]

    def user_for(self, persona: str) -> User:
        if persona in _STAFF_ROLE:
            return self._person(self.tenant_id, "staff", _STAFF_ROLE[persona].value)
        if persona == "customer":
            return self._person(self.tenant_id, "customer", Role.CUSTOMER.value)
        if persona == "beta_agent":
            if self.other_tenant_id is None:
                raise WorldError("the persona beta_agent needs a second organisation")
            for role in (Role.SALES_AGENT, Role.TENANT_ADMIN):
                people = self._people(self.other_tenant_id, "staff", role.value)
                if people:
                    return people[0]
            raise WorldError("the second organisation has no sales agent or admin")
        raise WorldError(f"unknown persona '{persona}'")

    def other_agent(self) -> User:
        """The second sales agent: whose records the first agent must not see."""
        return self._person(self.tenant_id, "staff", Role.SALES_AGENT.value, 1)

    def bind(self, principal: Principal) -> None:
        """The database context a request of this person would have (tenant, user, lead scope)."""
        if principal.tenant_id is None or principal.user_id is None:
            raise WorldError("a principal without an organisation or user can't be bound")
        bind_tenant(self.session, principal.tenant_id)
        managers = {Role.SALES_MANAGER, Role.TENANT_ADMIN}
        bind_user(self.session, principal.user_id, "all" if managers & principal.roles else "own")

    def principal(self, persona: str) -> Principal:
        user = self.user_for(persona)
        if persona == "customer":
            tenant = self.session.get(Tenant, user.tenant_id)
            principal = Principal(
                subject=user.idp_subject,
                issuer=user.idp_issuer,
                user_type="customer",
                roles=frozenset({Role.CUSTOMER}),
                permissions=permissions_for(frozenset({Role.CUSTOMER})),
                user_id=user.id,
                tenant_id=user.tenant_id,
                display_name=user.display_name,
                email=user.email,
                tenant_name=tenant.name if tenant else None,
            )
        else:
            found = identity_api.staff_principal(self.session, user.tenant_id, user.id)
            if found is None:
                raise WorldError(f"'{user.email}' is not an active staff member")
            principal = found
        self.bind(principal)
        return principal

    # --- records ---------------------------------------------------------------------------

    def granted_accounts(self, persona: str) -> list[uuid.UUID]:
        """The accounts a customer persona may see (the portal grants)."""
        user = self.user_for(persona)
        bind_tenant(self.session, user.tenant_id)
        return list(
            self.session.scalars(
                select(PortalAccessGrant.account_id)
                .where(
                    PortalAccessGrant.tenant_id == user.tenant_id,
                    PortalAccessGrant.user_id == user.id,
                )
                .order_by(PortalAccessGrant.account_id)
            )
        )

    def _lead(self, owner: User, last_name: str) -> uuid.UUID:
        bind_tenant(self.session, self.tenant_id)
        bind_user(self.session, owner.id, "own")  # the leads rule: a new lead is the owner's
        lead = Lead(
            id=clean_id(),
            tenant_id=self.tenant_id,
            first_name="Eval",
            last_name=last_name,
            owner_id=owner.id,
        )
        self.session.add(lead)
        self.session.flush()
        return lead.id

    def _contact(self, owner: User, last_name: str) -> uuid.UUID:
        bind_tenant(self.session, self.tenant_id)
        contact = Contact(
            id=clean_id(), tenant_id=self.tenant_id, last_name=last_name, owner_id=owner.id
        )
        self.session.add(contact)
        self.session.flush()
        return contact.id

    def _other_account(self, granted: list[uuid.UUID]) -> uuid.UUID:
        bind_tenant(self.session, self.tenant_id)
        others = self.session.scalars(
            select(Account.id)
            .where(
                Account.tenant_id == self.tenant_id, Account.id.not_in(granted or [uuid.uuid4()])
            )
            .order_by(Account.name)
        ).first()
        if others is not None:
            return others
        account = Account(tenant_id=self.tenant_id, name="Eval Other Account")
        self.session.add(account)
        self.session.flush()
        return account.id

    def _mentionable(self, user: User, role: Role) -> uuid.UUID:
        """The id to write into a question about this colleague.

        Seeded demo users have ids such as a1000000-0000-4000-8000-000000000004, which the card
        number rule refuses (a finding in docs/agent-evals.md). Then a stand-in colleague with the
        same role and a clean id is created - inside the transaction the caller rolls back."""
        if guardrails.inspect_input(str(user.id)).allowed:
            return user.id
        bind_tenant(self.session, self.tenant_id)
        stand_in = User(
            id=clean_id(),
            tenant_id=self.tenant_id,
            idp_issuer="eval-stand-in",
            idp_subject=f"eval-{uuid.uuid4()}",
            email=f"zz-eval-{uuid.uuid4().hex[:10]}@example.test",
            display_name=f"Eval {role.value}",
            user_type="staff",
            roles=[role.value],
        )
        self.session.add(stand_in)
        self.session.flush()
        return stand_in.id

    def placeholders(self, persona: str) -> dict[str, str]:
        """What ``{{...}}`` stands for when this persona plays."""
        if persona in ("visitor", "beta_agent"):
            return {}
        if persona == "customer":
            granted = self.granted_accounts(persona)
            if not granted:
                raise WorldError("the customer has no account access (portal grant)")
            return {
                "account.own": str(granted[0]),
                "account.other": str(self._other_account(granted)),
            }
        acting, other = self.user_for(persona), self.other_agent()
        support = self._person(self.tenant_id, "staff", Role.SUPPORT_AGENT.value)
        values = {
            "lead.own": str(self._lead(acting, "Own")),
            "lead.other": str(self._lead(other, "Other")),
            "user.agent2": str(self._mentionable(other, Role.SALES_AGENT)),
            "user.support": str(self._mentionable(support, Role.SUPPORT_AGENT)),
        }
        if persona == "sales_agent":
            values["contact.own"] = str(self._contact(acting, "Own"))
            values["contact.other"] = str(self._contact(other, "Other"))
        return values

    def snapshot(self) -> Snapshot:
        """Leads (as a manager sees them: all), activities and proposals of the organisation."""
        bind_tenant(self.session, self.tenant_id)
        bind_user(self.session, uuid.uuid4(), "all")
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
