# ruff: noqa: F811
"""Leads RLS: agent owns, manager all, missing settings fail closed."""

import uuid

from sqlalchemy import select, text

from app.core.db import bind_tenant, bind_user, clear_tenant
from app.modules.leads.models import Lead
from tests.db.test_quotes_api import world  # noqa: F401


def _lead(tenant: uuid.UUID, owner: uuid.UUID, name: str) -> Lead:
    return Lead(id=uuid.uuid4(), tenant_id=tenant, last_name=name, status="new", owner_id=owner)


def test_agent_sees_only_own_leads_and_manager_sees_all(world, db_session):
    tenant = world.users["alpha.admin"].tenant_id
    agent1 = world.users["alpha.agent1"].id
    agent2 = world.users["alpha.agent2"].id
    manager = world.users["alpha.manager"].id

    bind_tenant(db_session, tenant)
    bind_user(db_session, agent1, "own")
    own = _lead(tenant, agent1, "OwnLead")
    db_session.add(own)
    db_session.flush()

    bind_user(db_session, agent2, "own")
    other = _lead(tenant, agent2, "OtherLead")
    db_session.add(other)
    db_session.flush()

    assert db_session.scalars(select(Lead.id)).all() == [other.id]

    bind_user(db_session, manager, "all")
    assert set(db_session.scalars(select(Lead.id)).all()) == {own.id, other.id}

    bind_user(db_session, agent1, "own")
    assert db_session.scalars(select(Lead.id)).all() == [own.id]


def test_no_settings_returns_zero_rows(world, db_session):
    tenant = world.users["alpha.admin"].tenant_id
    owner = world.users["alpha.agent1"].id
    bind_tenant(db_session, tenant)
    bind_user(db_session, owner, "own")
    db_session.add(_lead(tenant, owner, "HiddenLead"))
    db_session.flush()

    clear_tenant(db_session)
    db_session.info.pop("user_id", None)
    db_session.info.pop("lead_scope", None)
    db_session.execute(text("select set_config('app.user_id', '', true)"))
    db_session.execute(text("select set_config('app.lead_scope', '', true)"))

    assert db_session.scalars(select(Lead.id)).all() == []
