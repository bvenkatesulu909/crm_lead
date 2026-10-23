# ruff: noqa: F811
"""CRM-101: support agent sees/manages all tickets in its tenant, never another tenant's."""

from app.modules.identity.models import User
from tests.auth_helpers import TEST_ISSUER
from tests.db.test_tickets_api import (  # noqa: F401
    api,
    auth,
    portal_ticket,
    world,
)


def test_support_can_read_and_manage_another_support_agents_ticket(
    api, auth, world, committed_world
):
    support2 = User(
        tenant_id=world.users["alpha.support"].tenant_id,
        idp_issuer=TEST_ISSUER,
        idp_subject="sub-alpha.support2",
        email="support2@example.test",
        display_name="Second Support",
        user_type="staff",
        roles=["support_agent"],
    )
    committed_world.add(support2)
    committed_world.commit()

    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    assigned = api.post(
        f"/api/v1/tickets/{ticket['id']}/assign",
        json={"assignee_id": str(support2.id)},
        headers=auth("alpha.admin"),
    )
    assert assigned.status_code == 200, assigned.text

    response = api.get(f"/api/v1/tickets/{ticket['id']}", headers=auth("alpha.support"))
    assert response.status_code == 200, response.text

    write = api.post(
        f"/api/v1/tickets/{ticket['id']}/assign",
        json={"assignee_id": str(world.users["alpha.support"].id)},
        headers=auth("alpha.support"),
    )
    assert write.status_code == 200, write.text
    assert write.json()["assignee_user_id"] == str(world.users["alpha.support"].id)


def test_support_sees_unassigned_queue(api, auth, world):
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    response = api.get(f"/api/v1/tickets/{ticket['id']}", headers=auth("alpha.support"))
    assert response.status_code == 200


def test_support_sees_ticket_assigned_to_themselves(api, auth, world):
    ticket = portal_ticket(api, auth, "alpha.customer1", world.accounts["A1"])
    assigned = api.post(
        f"/api/v1/tickets/{ticket['id']}/assign",
        json={"assignee_id": str(world.users["alpha.support"].id)},
        headers=auth("alpha.admin"),
    )
    assert assigned.status_code == 200, assigned.text
    response = api.get(f"/api/v1/tickets/{ticket['id']}", headers=auth("alpha.support"))
    assert response.status_code == 200


def test_support_cannot_read_another_tenants_ticket(api, auth, world):
    beta = portal_ticket(api, auth, "beta.customer", world.accounts["B1"])
    response = api.get(f"/api/v1/tickets/{beta['id']}", headers=auth("alpha.support"))
    assert response.status_code == 404
