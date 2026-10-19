"""The database itself enforces the identity and customer-access rules, even if code is wrong."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.accounts.models import Account
from app.modules.identity.models import PortalAccessGrant, Tenant, User
from tests.db.test_schema_constraints import make_account, make_tenant, violated_constraint

ISSUER = "http://localhost:8080/realms/crm"


def make_person(session: Session, tenant: Tenant, subject: str, user_type: str) -> User:
    user = User(
        tenant_id=tenant.id,
        idp_issuer=ISSUER,
        idp_subject=subject,
        email=f"{subject}@example.test",
        display_name=subject,
        user_type=user_type,
    )
    session.add(user)
    session.flush()
    return user


def grant(session: Session, user: User, account: Account, **extra: str) -> None:
    session.add(
        PortalAccessGrant(tenant_id=user.tenant_id, user_id=user.id, account_id=account.id, **extra)
    )
    session.flush()


def test_keycloak_identity_can_belong_to_only_one_tenant(db_session: Session) -> None:
    alpha, beta = make_tenant(db_session, "alpha"), make_tenant(db_session, "beta")
    make_person(db_session, alpha, "same-subject", "staff")

    with pytest.raises(IntegrityError) as error:
        make_person(db_session, beta, "same-subject", "staff")
    assert violated_constraint(error) == "uq_users_idp_issuer_idp_subject"


def test_customer_can_be_granted_an_account_of_own_tenant(db_session: Session) -> None:
    tenant = make_tenant(db_session, "alpha")
    customer = make_person(db_session, tenant, "customer-1", "customer")
    grant(db_session, customer, make_account(db_session, tenant))  # accepted


def test_staff_user_cannot_receive_a_portal_grant(db_session: Session) -> None:
    tenant = make_tenant(db_session, "alpha")
    staff = make_person(db_session, tenant, "staff-1", "staff")

    with pytest.raises(IntegrityError) as error:
        grant(db_session, staff, make_account(db_session, tenant))
    assert violated_constraint(error) == "fk_portal_access_grants_tenant_id_user_id_user_type_users"


def test_grant_row_cannot_claim_a_non_customer_type(db_session: Session) -> None:
    tenant = make_tenant(db_session, "alpha")
    customer = make_person(db_session, tenant, "customer-1", "customer")

    with pytest.raises(IntegrityError) as error:
        grant(db_session, customer, make_account(db_session, tenant), user_type="staff")
    assert violated_constraint(error) == "ck_portal_access_grants_customer_only"


def test_customer_cannot_be_granted_another_tenants_account(db_session: Session) -> None:
    alpha, beta = make_tenant(db_session, "alpha"), make_tenant(db_session, "beta")
    customer = make_person(db_session, alpha, "customer-1", "customer")
    beta_account = make_account(db_session, beta)

    with pytest.raises(IntegrityError) as error:
        grant(db_session, customer, beta_account)
    assert violated_constraint(error) == "fk_portal_access_grants_tenant_id_account_id_accounts"


def test_customer_with_grants_cannot_silently_become_staff(db_session: Session) -> None:
    tenant = make_tenant(db_session, "alpha")
    customer = make_person(db_session, tenant, "customer-1", "customer")
    grant(db_session, customer, make_account(db_session, tenant))

    customer.user_type = "staff"
    with pytest.raises(IntegrityError) as error:
        db_session.flush()
    assert violated_constraint(error) == "fk_portal_access_grants_tenant_id_user_id_user_type_users"


def test_duplicate_grant_is_rejected(db_session: Session) -> None:
    tenant = make_tenant(db_session, "alpha")
    customer = make_person(db_session, tenant, "customer-1", "customer")
    account = make_account(db_session, tenant)
    grant(db_session, customer, account)

    with pytest.raises(IntegrityError) as error:
        grant(db_session, customer, account)
    assert violated_constraint(error) == "uq_portal_access_grants_tenant_id_user_id_account_id"
