"""Tenant-level, role-level and record-level authorization, tested through the real API.

World used by every test (all invented data; committed through the owner role and truncated
after each test, so the restricted app role running the API can see it):

    tenant ALPHA                                 tenant BETA
      admin    (tenant_admin)                      admin    (tenant_admin)
      manager  (sales_manager)                     customer (customer) -> account B1
      agent1   (sales_agent)  owns account A1      account B1
      agent2   (sales_agent)  owns account A2
      support  (support_agent)
      customer1 (customer) -> granted A1
      customer2 (customer) -> granted A2
    super admin: valid token, no CRM user row, no tenant
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.modules.accounts.models import Account
from app.modules.identity.models import PortalAccessGrant, Tenant, User
from tests.auth_helpers import TEST_ISSUER, TokenFactory, bearer
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import session_factory_for


@dataclass
class World:
    tenants: dict[str, uuid.UUID] = field(default_factory=dict)
    users: dict[str, User] = field(default_factory=dict)
    accounts: dict[str, uuid.UUID] = field(default_factory=dict)


ROLES = {
    "alpha.admin": "tenant_admin",
    "alpha.manager": "sales_manager",
    "alpha.agent1": "sales_agent",
    "alpha.agent2": "sales_agent",
    "alpha.support": "support_agent",
    "alpha.customer1": "customer",
    "alpha.customer2": "customer",
    "beta.admin": "tenant_admin",
    "beta.customer": "customer",
}


@pytest.fixture
def world(committed_world: Session) -> World:
    w = World()
    for slug in ("alpha", "beta"):
        tenant = Tenant(slug=f"{slug}-test", name=f"{slug.title()} Test Tenant")
        committed_world.add(tenant)
        committed_world.flush()
        w.tenants[slug] = tenant.id

    for name, role in ROLES.items():
        tenant_slug, local = name.split(".")
        user = User(
            tenant_id=w.tenants[tenant_slug],
            idp_issuer=TEST_ISSUER,
            idp_subject=f"subject-{name}",
            email=f"{local}@{tenant_slug}.example.test",
            display_name=name,
            user_type="customer" if role == "customer" else "staff",
        )
        committed_world.add(user)
        committed_world.flush()
        w.users[name] = user

    for key, tenant_slug, owner in [
        ("A1", "alpha", "alpha.agent1"),
        ("A2", "alpha", "alpha.agent2"),
        ("B1", "beta", "beta.admin"),
    ]:
        account = Account(
            tenant_id=w.tenants[tenant_slug],
            name=f"Test Account {key}",
            account_number=f"INT-{key}",
            owner_id=w.users[owner].id,
        )
        committed_world.add(account)
        committed_world.flush()
        w.accounts[key] = account.id

    for customer, account_key in [
        ("alpha.customer1", "A1"),
        ("alpha.customer2", "A2"),
        ("beta.customer", "B1"),
    ]:
        user = w.users[customer]
        committed_world.add(
            PortalAccessGrant(
                tenant_id=user.tenant_id, user_id=user.id, account_id=w.accounts[account_key]
            )
        )
    committed_world.commit()
    return w


@pytest.fixture
def api(db_connection: Connection, token_factory: TokenFactory) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,  # replaced below by the test connection
        oidc_issuer=TEST_ISSUER,
    )
    app = create_app(settings, token_verifier=token_factory.verifier())
    app.state.session_factory = session_factory_for(db_connection)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def as_user(token_factory: TokenFactory, world: World):
    """as_user("alpha.agent1") -> Authorization header for that user's normal token."""

    def headers(name: str, roles: list[str] | None = None) -> dict[str, str]:
        if name == "superadmin":
            return bearer(token_factory.mint("subject-superadmin", roles or ["super_admin"]))
        return bearer(token_factory.mint(f"subject-{name}", roles or [ROLES[name]]))

    return headers


def ids(response_json: list[dict[str, str]] | dict[str, list[dict[str, str]]]) -> set[str]:
    items = response_json["items"] if isinstance(response_json, dict) else response_json
    return {item["id"] for item in items}


# --- Who am I: identity comes only from the verified token + database ------------------


def test_me_returns_identity_resolved_from_token_and_database(api, as_user, world) -> None:
    response = api.get("/api/v1/me", headers=as_user("alpha.agent1"))

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(world.users["alpha.agent1"].id)
    assert body["tenant_id"] == str(world.tenants["alpha"])
    assert body["roles"] == ["sales_agent"]
    assert body["display_name"] == "alpha.agent1"
    assert body["email"] == "agent1@alpha.example.test"
    assert "account:read:own" in body["permissions"]
    assert "account:read:all" not in body["permissions"]


def test_client_supplied_tenant_and_user_ids_are_ignored(api, as_user, world) -> None:
    beta = str(world.tenants["beta"])
    other_user = str(world.users["beta.admin"].id)
    response = api.get(
        f"/api/v1/me?tenant_id={beta}&user_id={other_user}",
        headers={**as_user("alpha.agent1"), "X-Tenant-ID": beta, "X-User-ID": other_user},
    )

    assert response.json()["tenant_id"] == str(world.tenants["alpha"])
    assert response.json()["user_id"] == str(world.users["alpha.agent1"].id)


def test_valid_token_for_unregistered_identity_is_forbidden(api, token_factory, world) -> None:
    response = api.get(
        "/api/v1/me", headers=bearer(token_factory.mint("stranger", ["sales_agent"]))
    )

    assert response.status_code == 403


def test_disabled_user_is_forbidden(api, as_user, world, committed_world) -> None:
    world.users["alpha.agent1"].is_active = False
    committed_world.commit()

    assert api.get("/api/v1/me", headers=as_user("alpha.agent1")).status_code == 403


def test_users_of_suspended_tenant_are_forbidden(api, as_user, world, committed_world) -> None:
    committed_world.get(Tenant, world.tenants["alpha"]).status = "suspended"
    committed_world.commit()

    assert api.get("/api/v1/accounts", headers=as_user("alpha.admin")).status_code == 403


# --- Tenant isolation -------------------------------------------------------------------


def test_tenant_admin_lists_only_own_tenant_accounts(api, as_user, world) -> None:
    response = api.get("/api/v1/accounts", headers=as_user("alpha.admin"))

    assert response.status_code == 200
    assert ids(response.json()) == {str(world.accounts["A1"]), str(world.accounts["A2"])}


def test_other_tenants_account_is_404_not_403(api, as_user, world) -> None:
    response = api.get(f"/api/v1/accounts/{world.accounts['B1']}", headers=as_user("alpha.admin"))

    # 404, exactly like a non-existent ID: the caller cannot even learn that B1 exists.
    assert response.status_code == 404
    unknown = api.get(f"/api/v1/accounts/{uuid.uuid4()}", headers=as_user("alpha.admin"))
    assert unknown.status_code == 404
    assert response.json()["detail"] == unknown.json()["detail"]


def test_beta_admin_cannot_read_alpha_accounts_by_id(api, as_user, world) -> None:
    for key in ("A1", "A2"):
        response = api.get(f"/api/v1/accounts/{world.accounts[key]}", headers=as_user("beta.admin"))
        assert response.status_code == 404


def test_query_parameter_cannot_switch_tenant(api, as_user, world) -> None:
    response = api.get(
        f"/api/v1/accounts?tenant_id={world.tenants['beta']}", headers=as_user("alpha.admin")
    )

    assert str(world.accounts["B1"]) not in ids(response.json())


def test_same_subject_from_another_issuer_is_rejected(api, token_factory, world) -> None:
    token = token_factory.sign(
        token_factory.claims(
            "subject-alpha.admin", ["tenant_admin"], iss="http://other.test/realms/crm"
        )
    )

    assert api.get("/api/v1/accounts", headers=bearer(token)).status_code == 401


# --- Role-level (RBAC) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ("alpha.admin", {"A1", "A2"}),
        ("alpha.manager", {"A1", "A2"}),
        ("alpha.support", {"A1", "A2"}),
        ("alpha.agent1", {"A1"}),
        ("alpha.agent2", {"A2"}),
        ("beta.admin", {"B1"}),
    ],
)
def test_staff_see_exactly_the_accounts_their_role_allows(
    api, as_user, world, user, expected
) -> None:
    response = api.get("/api/v1/accounts", headers=as_user(user))

    assert response.status_code == 200
    assert ids(response.json()) == {str(world.accounts[key]) for key in expected}


def test_super_admin_can_list_tenants_but_sees_no_tenant_data(api, as_user, world) -> None:
    tenants = api.get("/api/v1/platform/tenants", headers=as_user("superadmin"))
    assert tenants.status_code == 200
    assert {t["slug"] for t in tenants.json()} >= {"alpha-test", "beta-test"}

    assert api.get("/api/v1/accounts", headers=as_user("superadmin")).status_code == 403
    assert api.get("/api/v1/portal/accounts", headers=as_user("superadmin")).status_code == 403
    single = api.get(f"/api/v1/accounts/{world.accounts['A1']}", headers=as_user("superadmin"))
    assert single.status_code == 403


@pytest.mark.parametrize("user", ["alpha.admin", "alpha.agent1", "alpha.customer1"])
def test_non_super_admins_cannot_list_tenants(api, as_user, user) -> None:
    assert api.get("/api/v1/platform/tenants", headers=as_user(user)).status_code == 403


def test_customer_cannot_use_staff_endpoints(api, as_user, world) -> None:
    headers = as_user("alpha.customer1")

    assert api.get("/api/v1/accounts", headers=headers).status_code == 403
    assert api.get(f"/api/v1/accounts/{world.accounts['A1']}", headers=headers).status_code == 403


@pytest.mark.parametrize("user", ["alpha.admin", "alpha.manager", "alpha.agent1", "alpha.support"])
def test_staff_cannot_use_portal_endpoints(api, as_user, user) -> None:
    assert api.get("/api/v1/portal/accounts", headers=as_user(user)).status_code == 403


def test_extra_roles_in_token_do_not_escalate_a_customer(api, as_user, world) -> None:
    # Even if Keycloak were misconfigured to give a customer staff/admin roles, the CRM user
    # is a customer, so only the customer role counts.
    headers = as_user("alpha.customer1", roles=["customer", "tenant_admin", "super_admin"])

    me = api.get("/api/v1/me", headers=headers).json()
    assert me["roles"] == ["customer"]
    assert api.get("/api/v1/accounts", headers=headers).status_code == 403
    assert api.get("/api/v1/platform/tenants", headers=headers).status_code == 403


def test_tenant_member_cannot_become_super_admin_via_token_role(api, as_user) -> None:
    headers = as_user("alpha.agent1", roles=["sales_agent", "super_admin"])

    assert api.get("/api/v1/platform/tenants", headers=headers).status_code == 403


def test_unknown_role_names_grant_nothing(api, as_user) -> None:
    headers = as_user("alpha.agent1", roles=["admin", "root", "offline_access"])

    assert api.get("/api/v1/me", headers=headers).json()["permissions"] == []
    assert api.get("/api/v1/accounts", headers=headers).status_code == 403


# --- Record-level -----------------------------------------------------------------------


def test_sales_agent_cannot_read_colleagues_account_by_id(api, as_user, world) -> None:
    own = api.get(f"/api/v1/accounts/{world.accounts['A1']}", headers=as_user("alpha.agent1"))
    other = api.get(f"/api/v1/accounts/{world.accounts['A2']}", headers=as_user("alpha.agent1"))

    assert own.status_code == 200
    assert other.status_code == 404


def test_customer_sees_only_granted_account(api, as_user, world) -> None:
    response = api.get("/api/v1/portal/accounts", headers=as_user("alpha.customer1"))

    assert response.status_code == 200
    assert ids(response.json()) == {str(world.accounts["A1"])}


@pytest.mark.parametrize("target", ["A2", "B1"])
def test_customer_cannot_open_another_customers_account(api, as_user, world, target) -> None:
    # A2: same tenant, other customer. B1: other tenant. Both must look non-existent.
    response = api.get(
        f"/api/v1/portal/accounts/{world.accounts[target]}", headers=as_user("alpha.customer1")
    )

    assert response.status_code == 404


def test_portal_response_hides_internal_fields(api, as_user, world) -> None:
    response = api.get(
        f"/api/v1/portal/accounts/{world.accounts['A1']}", headers=as_user("alpha.customer1")
    )

    assert response.status_code == 200
    assert set(response.json()) == {"id", "name", "website", "status"}
    assert "INT-A1" not in response.text  # internal account number
    assert str(world.users["alpha.agent1"].id) not in response.text  # owner


def test_removing_a_grant_removes_access_immediately(api, as_user, world, committed_world) -> None:
    grant = (
        committed_world.query(PortalAccessGrant).filter_by(account_id=world.accounts["A1"]).one()
    )
    committed_world.delete(grant)
    committed_world.commit()

    response = api.get("/api/v1/portal/accounts", headers=as_user("alpha.customer1"))
    assert response.json() == []


def test_soft_deleted_account_is_invisible(api, as_user, world, committed_world) -> None:
    from datetime import UTC, datetime

    committed_world.get(Account, world.accounts["A1"]).deleted_at = datetime.now(UTC)
    committed_world.commit()

    response = api.get(f"/api/v1/accounts/{world.accounts['A1']}", headers=as_user("alpha.admin"))
    assert response.status_code == 404


def test_malformed_account_id_is_rejected_before_any_lookup(api, as_user) -> None:
    response = api.get("/api/v1/accounts/1%20OR%201=1", headers=as_user("alpha.admin"))

    assert response.status_code == 422


# --- Account list: search, filter, pagination (still limited to what you may see) -------


def test_account_search_and_paging_stay_within_scope(api, as_user, world) -> None:
    page = api.get("/api/v1/accounts?q=account%20a&limit=1", headers=as_user("alpha.admin")).json()
    assert (page["total"], len(page["items"]), page["limit"]) == (2, 1, 1)

    found = api.get("/api/v1/accounts?q=INT-B1", headers=as_user("alpha.admin")).json()
    assert found["total"] == 0  # account number of another tenant's account

    agent = api.get("/api/v1/accounts?q=account", headers=as_user("alpha.agent1")).json()
    assert ids(agent) == {str(world.accounts["A1"])}
    assert agent["total"] == 1


def test_account_status_filter_and_bad_parameters(api, as_user) -> None:
    active = api.get("/api/v1/accounts?status=active", headers=as_user("alpha.admin")).json()
    assert active["total"] == 2
    inactive = api.get("/api/v1/accounts?status=inactive", headers=as_user("alpha.admin")).json()
    assert inactive["total"] == 0
    for bad in ("status=deleted", "limit=0", "q="):
        assert api.get(f"/api/v1/accounts?{bad}", headers=as_user("alpha.admin")).status_code == 422


def test_me_includes_organisation_name(api, as_user) -> None:
    assert api.get("/api/v1/me", headers=as_user("alpha.agent1")).json()["tenant_name"] == (
        "Alpha Test Tenant"
    )
