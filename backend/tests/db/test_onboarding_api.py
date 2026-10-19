"""User administration and onboarding (ADR 0004) through the real API and PostgreSQL.

Keycloak's admin API is replaced by an in-memory fake that records every call, so these tests
check exactly what the CRM asks Keycloak to do. A separate test file talks to the real Keycloak.

tenant ALPHA: admin, manager, agent1 (owns A1), agent2 (owns A2), support, customer1 -> A1
tenant BETA:  admin, customer -> B1
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.auth.identity_admin import (
    IdentityAdminUnavailableError,
    IdentityConflictError,
    NewIdentity,
)
from app.core.auth.principal import Principal
from app.core.auth.rbac import Role, permissions_for
from app.core.config import Settings
from app.main import create_app
from app.modules.accounts.models import Account
from app.modules.identity import onboarding
from app.modules.identity.models import PortalAccessGrant, Tenant, User
from app.modules.identity.onboarding import LastAdminError
from tests.auth_helpers import TEST_ISSUER, TokenFactory, bearer
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for

PEOPLE = {
    "alpha.admin": ("alpha", "tenant_admin"),
    "alpha.manager": ("alpha", "sales_manager"),
    "alpha.agent1": ("alpha", "sales_agent"),
    "alpha.agent2": ("alpha", "sales_agent"),
    "alpha.support": ("alpha", "support_agent"),
    "alpha.customer1": ("alpha", "customer"),
    "beta.admin": ("beta", "tenant_admin"),
    "beta.customer": ("beta", "customer"),
}
Headers = Callable[[str], dict[str, str]]


class FakeIdentityAdmin:
    """Records what the CRM asks Keycloak to do; can be told to fail."""

    def __init__(self) -> None:
        self.users: dict[str, NewIdentity] = {}
        self.roles: dict[str, frozenset[str]] = {}
        self.enabled: dict[str, bool] = {}
        self.emails: list[str] = []
        self.deleted: list[str] = []
        self.fail_email = False
        self.taken: set[str] = set()

    def create_user(self, identity: NewIdentity) -> str:
        if identity.email in self.taken:
            raise IdentityConflictError("This e-mail address can't be used.")
        subject = str(uuid.uuid4())
        self.users[subject] = identity
        return subject

    def delete_user(self, subject: str) -> None:
        self.deleted.append(subject)
        self.users.pop(subject, None)

    def set_roles(self, subject: str, roles: frozenset[str]) -> None:
        assert "super_admin" not in roles
        self.roles[subject] = roles

    def set_enabled(self, subject: str, enabled: bool) -> None:
        self.enabled[subject] = enabled

    def send_setup_email(self, subject: str) -> None:
        if self.fail_email:
            raise IdentityAdminUnavailableError("The invitation e-mail could not be sent.")
        self.emails.append(subject)


class World:
    users: dict[str, User]
    accounts: dict[str, uuid.UUID]
    tenants: dict[str, Tenant]


@pytest.fixture
def world(db_session: Session) -> World:
    w = World()
    w.tenants = {}
    for slug in ("alpha", "beta"):
        tenant = Tenant(slug=f"{slug}-onboarding", name=f"{slug.title()} Onboarding Test")
        db_session.add(tenant)
        db_session.flush()
        db_session.refresh(tenant)
        w.tenants[slug] = tenant
    w.users = {}
    for name, (slug, role) in PEOPLE.items():
        user = User(
            tenant_id=w.tenants[slug].id,
            idp_issuer=TEST_ISSUER,
            idp_subject=f"sub-{name}",
            email=f"{name}@example.test",
            display_name=name,
            user_type="customer" if role == "customer" else "staff",
            roles=[role],
        )
        db_session.add(user)
        w.users[name] = user
    db_session.flush()
    w.accounts = {}
    for key, slug, owner in [
        ("A1", "alpha", "alpha.agent1"),
        ("A2", "alpha", "alpha.agent2"),
        ("B1", "beta", "beta.admin"),
    ]:
        account = Account(
            tenant_id=w.tenants[slug].id, name=f"Onboarding {key}", owner_id=w.users[owner].id
        )
        db_session.add(account)
        db_session.flush()
        w.accounts[key] = account.id
    for customer, key in [("alpha.customer1", "A1"), ("beta.customer", "B1")]:
        u = w.users[customer]
        db_session.add(
            PortalAccessGrant(tenant_id=u.tenant_id, user_id=u.id, account_id=w.accounts[key])
        )
    db_session.flush()
    return w


@pytest.fixture
def kc() -> FakeIdentityAdmin:
    return FakeIdentityAdmin()


@pytest.fixture
def api(
    db_connection: Connection, token_factory: TokenFactory, kc: FakeIdentityAdmin
) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
    )
    app = create_app(settings, token_verifier=token_factory.verifier(), identity_admin=kc)
    app.state.session_factory = session_factory_for(db_connection)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth(token_factory: TokenFactory, world: World) -> Headers:
    return lambda name: bearer(token_factory.mint(f"sub-{name}", [PEOPLE[name][1]]))


@pytest.fixture
def stranger(token_factory: TokenFactory) -> Callable[..., dict[str, str]]:
    """Someone who signed up in Keycloak but has no CRM user."""

    def make(subject: str = "sub-stranger", verified: bool = True, roles: tuple[str, ...] = ()):
        return bearer(
            token_factory.mint(
                subject,
                list(roles),
                email=f"{subject}@example.test",
                email_verified=verified,
                name="Sam Stranger",
            )
        )

    return make


NEW_STAFF = {
    "email": "New.Person@Example.test",
    "first_name": "New",
    "last_name": "Person",
    "role": "sales_agent",
}


def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json()


# --- Staff users ---------------------------------------------------------------------------


def test_admin_adds_staff_member_who_gets_an_invitation(api, auth, world, kc, db_session) -> None:
    created = ok(api.post("/api/v1/tenant/users", json=NEW_STAFF, headers=auth("alpha.admin")), 201)

    assert (created["email"], created["roles"], created["user_type"]) == (
        "new.person@example.test",
        ["sales_agent"],
        "staff",
    )
    [subject] = kc.users
    assert kc.roles[subject] == {"sales_agent"}
    assert kc.emails == [subject]
    row = db_session.get(User, uuid.UUID(created["id"]))
    assert row.tenant_id == world.tenants["alpha"].id and row.idp_subject == subject
    actions = db_session.scalars(select(AuditLog.action).where(AuditLog.entity_id == row.id)).all()
    assert actions == ["user.invited"]


@pytest.mark.parametrize(
    "change",
    [
        {"role": "super_admin"},
        {"role": "customer"},
        {"email": "not-an-email"},
        {"tenant_id": str(uuid.uuid4())},
        {"first_name": ""},
    ],
)
def test_staff_member_input_is_validated(api, auth, world, kc, change) -> None:
    response = api.post(
        "/api/v1/tenant/users", json={**NEW_STAFF, **change}, headers=auth("alpha.admin")
    )

    assert response.status_code == 422
    assert kc.users == {}


@pytest.mark.parametrize(
    "user", ["alpha.manager", "alpha.agent1", "alpha.support", "alpha.customer1"]
)
def test_only_tenant_admins_manage_users(api, auth, world, kc, user) -> None:
    assert api.get("/api/v1/tenant/users", headers=auth(user)).status_code == 403
    assert api.post("/api/v1/tenant/users", json=NEW_STAFF, headers=auth(user)).status_code == 403
    assert kc.users == {}


def test_admin_sees_only_own_organisation(api, auth, world) -> None:
    emails = {u["email"] for u in ok(api.get("/api/v1/tenant/users", headers=auth("alpha.admin")))}

    assert "alpha.customer1@example.test" in emails
    assert not any(e.startswith("beta.") for e in emails)


def test_duplicate_email_in_organisation_is_refused_before_keycloak(api, auth, world, kc) -> None:
    body = {**NEW_STAFF, "email": "alpha.manager@example.test"}

    response = api.post("/api/v1/tenant/users", json=body, headers=auth("alpha.admin"))

    assert (response.status_code, response.json()["code"]) == (409, "email_in_use")
    assert kc.users == {}


def test_email_taken_in_keycloak_is_a_conflict(api, auth, world, kc) -> None:
    kc.taken.add("new.person@example.test")

    response = api.post("/api/v1/tenant/users", json=NEW_STAFF, headers=auth("alpha.admin"))

    assert (response.status_code, response.json()["code"]) == (409, "email_in_use")


def test_failed_invitation_leaves_no_login_and_no_user(api, auth, world, kc) -> None:
    kc.fail_email = True

    response = api.post("/api/v1/tenant/users", json=NEW_STAFF, headers=auth("alpha.admin"))

    assert response.status_code == 503
    assert kc.users == {} and len(kc.deleted) == 1  # the Keycloak login was removed again
    emails = {u["email"] for u in ok(api.get("/api/v1/tenant/users", headers=auth("alpha.admin")))}
    assert "new.person@example.test" not in emails


def test_role_change(api, auth, world, kc, db_session) -> None:
    agent = world.users["alpha.agent1"]
    url = f"/api/v1/tenant/users/{agent.id}/role"

    changed = ok(api.put(url, json={"role": "sales_manager"}, headers=auth("alpha.admin")))

    assert changed["roles"] == ["sales_manager"]
    assert kc.roles[agent.idp_subject] == {"sales_manager"}
    assert (
        api.put(url, json={"role": "super_admin"}, headers=auth("alpha.admin")).status_code == 422
    )


def test_admin_cannot_change_themselves(api, auth, world) -> None:
    me = world.users["alpha.admin"].id
    for response in (
        api.put(
            f"/api/v1/tenant/users/{me}/role",
            json={"role": "sales_agent"},
            headers=auth("alpha.admin"),
        ),
        api.post(f"/api/v1/tenant/users/{me}/deactivate", headers=auth("alpha.admin")),
    ):
        assert (response.status_code, response.json()["code"]) == (409, "cannot_change_yourself")


def test_last_active_tenant_admin_is_protected(world, db_session, kc) -> None:
    """Defence in depth: through the API the acting admin always counts as an admin, so this
    is checked on the service with someone holding admin rights whose stored role is not
    tenant_admin (e.g. a just-changed role), removing the only real admin."""
    acting = world.users["alpha.manager"]
    principal = Principal(
        subject=acting.idp_subject,
        issuer=TEST_ISSUER,
        user_type="staff",
        roles=frozenset({Role.TENANT_ADMIN}),
        permissions=permissions_for(frozenset({Role.TENANT_ADMIN})),
        user_id=acting.id,
        tenant_id=acting.tenant_id,
    )
    only_admin = world.users["alpha.admin"].id

    with pytest.raises(LastAdminError):
        onboarding.set_active(db_session, principal, kc, only_admin, False)
    with pytest.raises(LastAdminError):
        onboarding.change_role(db_session, principal, kc, only_admin, "sales_agent")
    assert kc.enabled == {} and kc.roles == {}


def test_customers_cannot_get_a_staff_role(api, auth, world) -> None:
    customer = world.users["alpha.customer1"].id

    response = api.put(
        f"/api/v1/tenant/users/{customer}/role",
        json={"role": "tenant_admin"},
        headers=auth("alpha.admin"),
    )  # noqa: E501

    assert response.status_code == 409


def test_deactivated_user_is_locked_out_and_can_return(api, auth, world, kc) -> None:
    agent = world.users["alpha.agent1"]

    ok(api.post(f"/api/v1/tenant/users/{agent.id}/deactivate", headers=auth("alpha.admin")))
    assert kc.enabled[agent.idp_subject] is False
    assert api.get("/api/v1/me", headers=auth("alpha.agent1")).status_code == 403

    ok(api.post(f"/api/v1/tenant/users/{agent.id}/reactivate", headers=auth("alpha.admin")))
    assert kc.enabled[agent.idp_subject] is True
    assert api.get("/api/v1/me", headers=auth("alpha.agent1")).status_code == 200


def test_users_of_another_organisation_are_not_found(api, auth, world, kc) -> None:
    beta = world.users["beta.admin"].id
    for response in (
        api.put(
            f"/api/v1/tenant/users/{beta}/role",
            json={"role": "sales_agent"},
            headers=auth("alpha.admin"),
        ),  # noqa: E501
        api.post(f"/api/v1/tenant/users/{beta}/deactivate", headers=auth("alpha.admin")),
        api.post(f"/api/v1/tenant/users/{beta}/resend-invite", headers=auth("alpha.admin")),
    ):
        assert response.status_code == 404
    assert kc.roles == {} and kc.enabled == {} and kc.emails == []


def test_resend_invite(api, auth, world, kc) -> None:
    agent = world.users["alpha.agent1"]

    response = api.post(
        f"/api/v1/tenant/users/{agent.id}/resend-invite", headers=auth("alpha.admin")
    )

    assert response.status_code == 204
    assert kc.emails == [agent.idp_subject]


# --- Sign-up code --------------------------------------------------------------------------


def test_signup_code_is_visible_to_admins_and_can_be_replaced(api, auth, world) -> None:
    first = ok(api.get("/api/v1/tenant/signup-code", headers=auth("alpha.admin")))["signup_code"]
    new = ok(api.post("/api/v1/tenant/signup-code/regenerate", headers=auth("alpha.admin")))[
        "signup_code"
    ]

    assert first == world.tenants["alpha"].signup_code
    assert new != first
    assert len(new) == 14 and new.count("-") == 2
    assert api.get("/api/v1/tenant/signup-code", headers=auth("alpha.manager")).status_code == 403


# --- Portal invitations --------------------------------------------------------------------


def invite(
    api: TestClient, auth: Headers, user: str, account: uuid.UUID, email: str = "Dana@Client.test"
) -> Any:  # noqa: E501
    body = {"email": email, "first_name": "Dana", "last_name": "Client"}
    return api.post(f"/api/v1/accounts/{account}/portal-users", json=body, headers=auth(user))


@pytest.mark.parametrize("inviter", ["alpha.admin", "alpha.agent1"])
def test_customer_contact_is_invited_for_one_account(api, auth, world, kc, inviter) -> None:
    invited = ok(invite(api, auth, inviter, world.accounts["A1"]), 201)

    [subject] = kc.users
    assert kc.roles[subject] == {"customer"} and kc.emails == [subject]
    portal = ok(
        api.get(
            f"/api/v1/accounts/{world.accounts['A1']}/portal-users", headers=auth("alpha.admin")
        )
    )  # noqa: E501
    assert invited["id"] in {u["id"] for u in portal}
    users = ok(api.get("/api/v1/tenant/users", headers=auth("alpha.admin")))
    row = next(u for u in users if u["id"] == invited["id"])
    assert (row["user_type"], row["portal_account_ids"]) == (
        "customer",
        [str(world.accounts["A1"])],
    )


@pytest.mark.parametrize(
    ("user", "account", "status"),
    [
        ("alpha.agent1", "A2", 404),  # not their account
        ("alpha.admin", "B1", 404),  # another organisation
        ("beta.admin", "A1", 404),
        ("alpha.support", "A1", 403),  # no invite permission
        ("alpha.manager", "A1", 403),
        ("alpha.customer1", "A1", 403),
    ],
)
def test_portal_invitation_denied(api, auth, world, kc, user, account, status) -> None:
    assert invite(api, auth, user, world.accounts[account]).status_code == status
    assert kc.users == {}


def test_existing_portal_user_just_gets_another_account(api, auth, world, kc) -> None:
    response = invite(
        api, auth, "alpha.admin", world.accounts["A2"], "alpha.customer1@example.test"
    )

    assert ok(response, 201)["id"] == str(world.users["alpha.customer1"].id)
    assert kc.users == {}  # no second login
    accounts = ok(api.get("/api/v1/portal/accounts", headers=auth("alpha.customer1")))
    assert {a["id"] for a in accounts} == {str(world.accounts["A1"]), str(world.accounts["A2"])}


def test_staff_email_cannot_become_a_portal_user(api, auth, world) -> None:
    response = invite(api, auth, "alpha.admin", world.accounts["A1"], "alpha.agent1@example.test")

    assert (response.status_code, response.json()["code"]) == (409, "email_in_use")


def test_revoking_portal_access(api, auth, world) -> None:
    customer = world.users["alpha.customer1"].id
    url = f"/api/v1/accounts/{world.accounts['A1']}/portal-users/{customer}"

    assert api.delete(url, headers=auth("alpha.agent2")).status_code == 404  # not their account
    assert api.delete(url, headers=auth("alpha.agent1")).status_code == 204
    assert ok(api.get("/api/v1/portal/accounts", headers=auth("alpha.customer1"))) == []
    assert api.delete(url, headers=auth("alpha.agent1")).status_code == 404  # already gone


# --- Self sign-up with approval ------------------------------------------------------------


def test_signed_up_person_has_no_access_until_approved(api, stranger, world) -> None:
    me = api.get("/api/v1/me", headers=stranger())
    assert (me.status_code, me.json()["code"]) == (403, "access_pending")
    assert api.get("/api/v1/accounts", headers=stranger()).status_code == 403
    assert ok(api.get("/api/v1/onboarding/status", headers=stranger()))["state"] == "none"


def test_request_with_the_right_code_waits_for_that_organisation(
    api, auth, stranger, world
) -> None:
    code = world.tenants["alpha"].signup_code

    status = ok(
        api.post(
            "/api/v1/onboarding/requests", json={"signup_code": code.lower()}, headers=stranger()
        ),
        201,
    )  # noqa: E501

    assert (status["state"], status["organisation_name"]) == ("pending", "Alpha Onboarding Test")
    again = api.post("/api/v1/onboarding/requests", json={"signup_code": code}, headers=stranger())
    assert again.status_code == 409
    alpha = ok(api.get("/api/v1/tenant/access-requests", headers=auth("alpha.admin")))
    assert [(r["email"], r["display_name"]) for r in alpha] == [
        ("sub-stranger@example.test", "Sam Stranger")
    ]  # noqa: E501
    assert ok(api.get("/api/v1/tenant/access-requests", headers=auth("beta.admin"))) == []


def test_wrong_codes_are_limited(api, stranger, world) -> None:
    for _ in range(5):
        wrong = api.post(
            "/api/v1/onboarding/requests",
            json={"signup_code": "AAAA-BBBB-CCCC"},
            headers=stranger(),
        )  # noqa: E501
        assert (wrong.status_code, wrong.json()["code"]) == (422, "invalid_signup_code")

    right = world.tenants["alpha"].signup_code
    blocked = api.post(
        "/api/v1/onboarding/requests", json={"signup_code": right}, headers=stranger()
    )

    assert (blocked.status_code, blocked.json()["code"]) == (429, "too_many_attempts")


def test_unverified_email_cannot_request_access(api, stranger, world) -> None:
    response = api.post(
        "/api/v1/onboarding/requests",
        json={"signup_code": world.tenants["alpha"].signup_code},
        headers=stranger(verified=False),
    )

    assert (response.status_code, response.json()["code"]) == (403, "email_not_verified")


def test_request_cannot_choose_its_own_organisation_or_role(api, stranger, world) -> None:
    for extra in ({"tenant_id": str(world.tenants["beta"].id)}, {"role": "tenant_admin"}):
        body = {"signup_code": world.tenants["alpha"].signup_code, **extra}
        assert (
            api.post("/api/v1/onboarding/requests", json=body, headers=stranger()).status_code
            == 422
        )


def pending_request(
    api: TestClient, auth: Headers, stranger: Any, world: World, subject: str = "sub-stranger"
) -> str:
    """Submits a request with Alpha's code; returns its ID as Alpha's admin sees it."""
    body = {"signup_code": world.tenants["alpha"].signup_code}
    ok(api.post("/api/v1/onboarding/requests", json=body, headers=stranger(subject)), 201)
    requests = ok(api.get("/api/v1/tenant/access-requests", headers=auth("alpha.admin")))
    return str(next(r["id"] for r in requests if r["email"] == f"{subject}@example.test"))


def test_approval_as_staff_gives_access_in_that_organisation(
    api, auth, stranger, world, kc, token_factory
) -> None:  # noqa: E501
    request_id = pending_request(api, auth, stranger, world)

    user = ok(
        api.post(
            f"/api/v1/tenant/access-requests/{request_id}/approve",
            json={"role": "support_agent"},
            headers=auth("alpha.admin"),
        )
    )  # noqa: E501

    assert (user["email"], user["roles"]) == ("sub-stranger@example.test", ["support_agent"])
    assert kc.roles["sub-stranger"] == {"support_agent"}
    # With the role in the next token, the person is a member of Alpha - and only Alpha.
    token = bearer(token_factory.mint("sub-stranger", ["support_agent"]))
    me = ok(api.get("/api/v1/me", headers=token))
    assert (me["tenant_id"], me["user_type"]) == (str(world.tenants["alpha"].id), "staff")
    assert ok(api.get("/api/v1/onboarding/status", headers=token))["state"] == "member"


def test_approval_as_customer_with_accounts(api, auth, stranger, world, token_factory) -> None:
    request_id = pending_request(api, auth, stranger, world)
    url = f"/api/v1/tenant/access-requests/{request_id}/approve"

    assert api.post(url, json={"role": "customer"}, headers=auth("alpha.admin")).status_code == 422
    assert (
        api.post(
            url,
            json={"role": "sales_agent", "account_ids": [str(world.accounts["A1"])]},
            headers=auth("alpha.admin"),
        ).status_code
        == 422
    )  # noqa: E501
    assert (
        api.post(
            url,
            json={"role": "customer", "account_ids": [str(world.accounts["B1"])]},
            headers=auth("alpha.admin"),
        ).status_code
        == 404
    )  # noqa: E501
    ok(
        api.post(
            url,
            json={"role": "customer", "account_ids": [str(world.accounts["A2"])]},
            headers=auth("alpha.admin"),
        )
    )  # noqa: E501

    token = bearer(token_factory.mint("sub-stranger", ["customer"]))
    accounts = ok(api.get("/api/v1/portal/accounts", headers=token))
    assert [a["id"] for a in accounts] == [str(world.accounts["A2"])]


def test_other_organisation_cannot_decide_the_request(api, auth, stranger, world, kc) -> None:
    request_id = pending_request(api, auth, stranger, world)

    approve = api.post(
        f"/api/v1/tenant/access-requests/{request_id}/approve",
        json={"role": "tenant_admin"},
        headers=auth("beta.admin"),
    )  # noqa: E501
    reject = api.post(
        f"/api/v1/tenant/access-requests/{request_id}/reject", headers=auth("beta.admin")
    )

    assert (approve.status_code, reject.status_code) == (404, 404)
    assert kc.roles == {}


def test_rejected_person_stays_locked_out(api, auth, stranger, world) -> None:
    request_id = pending_request(api, auth, stranger, world)

    assert (
        api.post(
            f"/api/v1/tenant/access-requests/{request_id}/reject", headers=auth("alpha.admin")
        ).status_code
        == 204
    )  # noqa: E501

    assert ok(api.get("/api/v1/onboarding/status", headers=stranger()))["state"] == "rejected"
    assert api.get("/api/v1/me", headers=stranger()).status_code == 403
    again = api.post(
        f"/api/v1/tenant/access-requests/{request_id}/approve",
        json={"role": "sales_agent"},
        headers=auth("alpha.admin"),
    )  # noqa: E501
    assert again.status_code == 404  # decided requests can't be approved later


def test_a_role_in_the_token_alone_grants_nothing(api, stranger, world) -> None:
    # Someone with a forged/leftover realm role but no CRM user still gets no data.
    token = stranger("sub-intruder", roles=("tenant_admin",))
    response = api.get("/api/v1/tenant/users", headers=token)
    assert (response.status_code, response.json()["code"]) == (403, "access_pending")


# --- Platform ------------------------------------------------------------------------------


def test_super_admin_creates_an_organisation_with_its_first_admin(
    api, auth, world, kc, token_factory
) -> None:  # noqa: E501
    platform = bearer(token_factory.mint("sub-platform", ["super_admin"]))
    body = {
        "slug": "gamma-co",
        "name": "Gamma Co",
        "admin_email": "boss@gamma.test",
        "admin_first_name": "Gia",
        "admin_last_name": "Boss",
    }

    created = ok(api.post("/api/v1/platform/tenants", json=body, headers=platform), 201)

    [subject] = kc.users
    assert kc.roles[subject] == {"tenant_admin"} and kc.emails == [subject]
    assert len(created["signup_code"]) == 14
    assert api.post("/api/v1/platform/tenants", json=body, headers=platform).status_code == 409
    assert (
        api.post(
            "/api/v1/platform/tenants", json={**body, "slug": "x"}, headers=auth("alpha.admin")
        ).status_code
        == 403
    )  # noqa: E501
    # The new admin works inside Gamma; the super admin still sees no business data.
    gamma = ok(api.get("/api/v1/me", headers=bearer(token_factory.mint(subject, ["tenant_admin"]))))
    assert gamma["tenant_name"] == "Gamma Co"
    assert api.get("/api/v1/accounts", headers=platform).status_code == 403


def test_sign_in_is_recorded_at_most_every_15_minutes(api, auth, world, db_session) -> None:
    agent = world.users["alpha.agent1"]
    assert agent.last_login_at is None

    ok(api.get("/api/v1/me", headers=auth("alpha.agent1")))
    db_session.refresh(agent)
    first = agent.last_login_at
    ok(api.get("/api/v1/me", headers=auth("alpha.agent1")))
    db_session.refresh(agent)

    assert first is not None
    assert agent.last_login_at == first  # not rewritten on every request
