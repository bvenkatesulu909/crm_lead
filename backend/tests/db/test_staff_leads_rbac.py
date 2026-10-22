# ruff: noqa: F811
"""DB cross-tenant test for staff search_leads."""

import uuid

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.leads import api as leads_api
from app.modules.leads.models import Lead
from tests.db.test_quotes_api import world  # noqa: F401


def _staff(world, user: str) -> Principal:
    return Principal(
        subject="sub-" + user,
        issuer="test",
        user_type="staff",
        roles=frozenset(),
        permissions=frozenset({Permission.LEAD_READ_ALL}),
        user_id=world.users[user].id,
        tenant_id=world.users[user].tenant_id,
    )


def test_search_leads_never_crosses_tenants(world, db_session):
    alpha = world.users["alpha.admin"].tenant_id
    beta = world.users["beta.admin"].tenant_id
    alpha_lead = Lead(id=uuid.uuid4(), tenant_id=alpha, last_name="AlphaOnlyLead", status="new")
    beta_lead = Lead(id=uuid.uuid4(), tenant_id=beta, last_name="BetaOnlyLead", status="new")
    db_session.add_all([alpha_lead, beta_lead])
    db_session.flush()

    alpha_rows = leads_api.search_leads(db_session, _staff(world, "alpha.admin"), q="OnlyLead")
    beta_rows = leads_api.search_leads(db_session, _staff(world, "beta.admin"), q="OnlyLead")
    assert {row["id"] for row in alpha_rows} == {str(alpha_lead.id)}
    assert {row["id"] for row in beta_rows} == {str(beta_lead.id)}
