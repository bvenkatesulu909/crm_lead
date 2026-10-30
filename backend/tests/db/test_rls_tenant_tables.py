"""Row-level security on every tenant table (ADR 0009, step 5) - the guard for future migrations.

Setup data is committed through crm_owner (committed_world); every assertion runs as the
restricted crm_app role, so the policies are really exercised.
"""

# ruff: noqa: F811 - the imported world fixture is used as a test parameter

import uuid

import pytest
from sqlalchemy import column, func, select, table, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.db import bind_tenant, bind_user, clear_tenant
from app.modules.accounts.models import Account
from app.modules.contacts.models import Contact
from app.modules.leads.models import Lead, LeadActivity, LeadAssignment
from tests.db.test_quotes_api import world  # noqa: F401

# Tables without a tenant_id column, each a documented exception in ADR 0009.
NOT_TENANT_TABLES = {"alembic_version", "tenants", "signup_code_attempts", "service_heartbeats"}


def _tenant_tables(session: Session) -> list[str]:
    return list(
        session.scalars(
            text(
                "select c.table_name from information_schema.columns c "
                "join information_schema.tables t "
                "  on t.table_schema = c.table_schema and t.table_name = c.table_name "
                "where c.table_schema = current_schema() and c.column_name = 'tenant_id' "
                "  and t.table_type = 'BASE TABLE' "
                "order by c.table_name"
            )
        )
    )


def _rows_by_tenant(session: Session, name: str) -> dict[uuid.UUID, int]:
    tenant_table = table(name, column("tenant_id"))
    rows = session.execute(
        select(tenant_table.c.tenant_id, func.count()).group_by(tenant_table.c.tenant_id)
    ).all()
    return {tenant_id: count for tenant_id, count in rows}


def test_every_tenant_table_has_forced_rls_and_a_tenant_policy(db_session: Session) -> None:
    names = _tenant_tables(db_session)
    assert len(names) >= 47  # grows with new modules; never shrinks silently
    flags = {
        name: (enabled, forced)
        for name, enabled, forced in db_session.execute(
            text(
                "select c.relname, c.relrowsecurity, c.relforcerowsecurity from pg_class c "
                "join pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname = current_schema() and c.relkind = 'r'"
            )
        )
    }
    policies: dict[str, list[tuple[str, str]]] = {}
    for name, using, check in db_session.execute(
        text(
            "select tablename, qual, with_check from pg_policies "
            "where schemaname = current_schema()"
        )
    ):
        policies.setdefault(name, []).append((using or "", check or ""))

    missing = [name for name in names if flags.get(name) != (True, True)]
    assert missing == [], f"tenant tables without ENABLE + FORCE RLS: {missing}"
    for name in names:
        assert policies.get(name), f"{name} has no policy"
        for using, check in policies[name]:
            assert "crm_current_tenant()" in using, f"{name}: USING does not check the tenant"
            assert "crm_current_tenant()" in check, f"{name}: WITH CHECK does not check the tenant"

    others = set(flags) - set(names)
    assert others <= NOT_TENANT_TABLES, f"new table without tenant_id: {others - NOT_TENANT_TABLES}"


def test_app_role_has_no_bypass(db_session: Session) -> None:
    assert db_session.scalar(text("select current_user")) == "crm_app"
    bypass = db_session.scalar(text("select rolbypassrls from pg_roles where rolname = 'crm_app'"))
    assert bypass is False


def test_no_context_sees_nothing_and_a_tenant_sees_only_itself(world, db_session) -> None:
    alpha = world.users["alpha.admin"].tenant_id
    beta = world.users["beta.admin"].tenant_id
    names = _tenant_tables(db_session)
    seen_rows = 0

    clear_tenant(db_session)
    for name in names:
        assert _rows_by_tenant(db_session, name) == {}, f"{name} leaks rows without a tenant"

    for tenant in (alpha, beta):
        bind_tenant(db_session, tenant)
        for name in names:
            visible = _rows_by_tenant(db_session, name)
            assert set(visible) <= {tenant}, f"{name} shows another tenant's rows"
            seen_rows += sum(visible.values())
    assert seen_rows > 0  # the probe looked at real rows, not only empty tables


def test_rows_cannot_be_written_into_another_tenant(world, db_session) -> None:
    alpha = world.users["alpha.admin"].tenant_id
    beta = world.users["beta.admin"].tenant_id
    bind_tenant(db_session, alpha)

    with pytest.raises(ProgrammingError, match="row-level security"), db_session.begin_nested():
        db_session.add(Account(tenant_id=beta, name="Planted in beta"))
        db_session.flush()

    own = db_session.scalars(select(Account).where(Account.tenant_id == alpha)).first()
    assert own is not None
    with pytest.raises(ProgrammingError, match="row-level security"), db_session.begin_nested():
        db_session.execute(
            text("update accounts set tenant_id = :beta where id = :id"),
            {"beta": beta, "id": own.id},
        )


def test_other_tenants_rows_cannot_be_changed_or_deleted(world, db_session) -> None:
    alpha = world.users["alpha.admin"].tenant_id
    beta = world.users["beta.admin"].tenant_id
    bind_tenant(db_session, alpha)

    changed = db_session.execute(
        text("update accounts set name = 'hijacked' where tenant_id = :beta"), {"beta": beta}
    )
    deleted = db_session.execute(
        text("delete from portal_access_grants where tenant_id = :beta"), {"beta": beta}
    )
    assert (changed.rowcount, deleted.rowcount) == (0, 0)


def test_app_role_cannot_switch_rls_off(db_session: Session) -> None:
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(text("alter table accounts disable row level security"))
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(text("set local row_security = off"))
        db_session.execute(text("select count(*) from accounts")).scalar()


CORE_TABLES = ("accounts", "contacts", "lead_activities", "lead_assignments")


def _seed_core_rows(session: Session, tenant: uuid.UUID, user_id: uuid.UUID) -> None:
    """One lead with its timeline entry and assignment, and one contact on an account."""
    bind_tenant(session, tenant)
    bind_user(session, user_id, "all")
    lead = Lead(
        id=uuid.uuid4(), tenant_id=tenant, last_name="Probe", status="new", owner_id=user_id
    )
    account = Account(id=uuid.uuid4(), tenant_id=tenant, name="Probe account")
    session.add_all([lead, account])
    session.flush()
    session.add_all(
        [
            LeadActivity(tenant_id=tenant, lead_id=lead.id, kind="note", subject="probe"),
            LeadAssignment(tenant_id=tenant, lead_id=lead.id, to_user_id=user_id),
            Contact(tenant_id=tenant, last_name="Probe", account_id=account.id),
        ]
    )
    session.flush()


def test_core_tables_hide_the_other_tenants_real_rows(world, db_session) -> None:
    """CRM-107: accounts, contacts, lead_activities and lead_assignments are probed on rows that
    exist in both tenants (the general probe passes even when these tables are empty)."""
    alpha = world.users["alpha.admin"]
    beta = world.users["beta.admin"]
    _seed_core_rows(db_session, alpha.tenant_id, alpha.id)
    _seed_core_rows(db_session, beta.tenant_id, beta.id)
    for tenant in (alpha.tenant_id, beta.tenant_id):
        bind_tenant(db_session, tenant)
        for name in CORE_TABLES:
            visible = _rows_by_tenant(db_session, name)
            assert visible, f"{name}: no rows to probe for this tenant"
            assert set(visible) == {tenant}, f"{name} shows another tenant's rows"
    clear_tenant(db_session)
    for name in CORE_TABLES:
        assert _rows_by_tenant(db_session, name) == {}, f"{name} leaks rows without a tenant"
