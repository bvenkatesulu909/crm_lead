"""Projects and units through the real API and PostgreSQL (ADR 0040, RP1). Rolled back each test.

tenant ALPHA: admin, manager, agent1, agent2, support, customer1, customer2
tenant BETA:  admin, customer
"""

# ruff: noqa: F811 - the fixtures are imported and used by name

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.audit import AuditLog
from app.core.auth.rbac import Role
from app.core.db import bind_tenant
from app.core.errors import ForbiddenError
from app.modules.units import api as units_api
from app.modules.units import service
from app.modules.units.schemas import ProjectCreate
from tests.db.test_invoices_api import (  # noqa: F401 - fixtures used by name
    api,
    auth,
    ok,
    principal_for,
    world,
)

PROJECTS = "/api/v1/projects"
UNITS = "/api/v1/units"
ADMIN = "alpha.admin"


def make_project(api, auth, who=ADMIN, name="Green Valley", **over: Any) -> dict[str, Any]:
    body = {"name": name, **over}
    return ok(api.post(PROJECTS, json=body, headers=auth(who)), 201)


def make_unit(api, auth, project_id, who=ADMIN, code="A-101", **over: Any) -> dict[str, Any]:
    body = {
        "project_id": project_id,
        "unit_code": code,
        "unit_type": "apartment",
        "price": "4500000.50",
        **over,
    }
    return ok(api.post(UNITS, json=body, headers=auth(who)), 201)


# --- who may -----------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["alpha.admin", "alpha.manager"])
def test_managers_and_administrators_maintain_projects_and_units(api, auth, world, who) -> None:
    project = make_project(api, auth, who, name=f"P of {who}")
    unit = make_unit(api, auth, project["id"], who)
    assert unit["status"] == "available" and unit["currency"] == "INR"
    assert ok(api.get(f"{UNITS}/{unit['id']}", headers=auth(who)))["unit_code"] == "A-101"


def test_a_sales_agent_reads_but_cannot_change(api, auth, world) -> None:
    project = make_project(api, auth)
    unit = make_unit(api, auth, project["id"])
    agent = auth("alpha.agent1")
    assert ok(api.get(PROJECTS, headers=agent))["total"] == 1
    assert ok(api.get(UNITS, headers=agent))["total"] == 1
    assert ok(api.get(f"{UNITS}/{unit['id']}", headers=agent))["id"] == unit["id"]
    assert api.post(PROJECTS, json={"name": "X"}, headers=agent).status_code == 403
    body = {"project_id": project["id"], "unit_code": "B", "unit_type": "plot", "price": "1"}
    assert api.post(UNITS, json=body, headers=agent).status_code == 403
    patch = api.patch(
        f"{UNITS}/{unit['id']}", json={"version": 1, "status": "blocked"}, headers=agent
    )
    assert patch.status_code == 403
    patch = api.patch(
        f"{PROJECTS}/{project['id']}", json={"version": 1, "name": "Z"}, headers=agent
    )
    assert patch.status_code == 403


@pytest.mark.parametrize("who", ["alpha.support", "alpha.customer1", "beta.customer"])
def test_support_and_customers_have_no_access(api, auth, world, who) -> None:
    project = make_project(api, auth)
    unit = make_unit(api, auth, project["id"])
    headers = auth(who)
    assert api.get(PROJECTS, headers=headers).status_code == 403
    assert api.get(UNITS, headers=headers).status_code == 403
    assert api.get(f"{UNITS}/{unit['id']}", headers=headers).status_code == 403
    assert api.post(PROJECTS, json={"name": "X"}, headers=headers).status_code == 403


def test_every_endpoint_needs_a_sign_in(api, auth, world) -> None:
    for path in (PROJECTS, UNITS):
        assert api.get(path).status_code == 401
        assert api.post(path, json={}).status_code == 401


# --- projects ----------------------------------------------------------------------------


def test_a_project_name_is_unique_ignoring_capitals(api, auth, world) -> None:
    make_project(api, auth, name="Green Valley")
    again = api.post(PROJECTS, json={"name": "green valley"}, headers=auth(ADMIN))
    assert again.status_code == 409 and again.json()["code"] == "already_exists"


def test_two_organisations_may_use_the_same_project_name(api, auth, world) -> None:
    make_project(api, auth, name="Green Valley")
    assert make_project(api, auth, "beta.admin", name="Green Valley")["version"] == 1


def test_a_project_change_needs_the_version_that_was_read(api, auth, world) -> None:
    project = make_project(api, auth)
    done = ok(
        api.patch(
            f"{PROJECTS}/{project['id']}",
            json={"version": 1, "location": "Vijayawada"},
            headers=auth(ADMIN),
        )
    )
    assert done["version"] == 2 and done["location"] == "Vijayawada"
    stale = api.patch(
        f"{PROJECTS}/{project['id']}", json={"version": 1, "name": "Later"}, headers=auth(ADMIN)
    )
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"


def test_an_empty_change_or_a_removed_name_is_refused(api, auth, world) -> None:
    project = make_project(api, auth)
    url = f"{PROJECTS}/{project['id']}"
    assert api.patch(url, json={"version": 1}, headers=auth(ADMIN)).status_code == 422
    assert api.patch(url, json={"version": 1, "name": None}, headers=auth(ADMIN)).status_code == 422


def test_an_inactive_project_takes_no_new_units(api, auth, world) -> None:
    project = make_project(api, auth)
    ok(
        api.patch(
            f"{PROJECTS}/{project['id']}",
            json={"version": 1, "is_active": False},
            headers=auth(ADMIN),
        )
    )
    body = {"project_id": project["id"], "unit_code": "A", "unit_type": "plot", "price": "1"}
    response = api.post(UNITS, json=body, headers=auth(ADMIN))
    assert response.status_code == 409 and response.json()["code"] == "project_inactive"


def test_projects_can_be_searched(api, auth, world) -> None:
    make_project(api, auth, name="Green Valley", location="Vijayawada")
    make_project(api, auth, name="Blue Hills", location="Guntur")
    by_name = ok(api.get(PROJECTS, params={"q": "green"}, headers=auth(ADMIN)))
    by_place = ok(api.get(PROJECTS, params={"q": "gunt"}, headers=auth(ADMIN)))
    assert [p["name"] for p in by_name["items"]] == ["Green Valley"]
    assert [p["name"] for p in by_place["items"]] == ["Blue Hills"]


def test_a_search_with_wildcards_matches_only_the_literal_text(api, auth, world) -> None:
    make_project(api, auth, name="Green Valley")
    assert ok(api.get(PROJECTS, params={"q": "%"}, headers=auth(ADMIN)))["total"] == 0


# --- units -------------------------------------------------------------------------------


def test_the_price_keeps_its_paise_exactly(api, auth, world) -> None:
    project = make_project(api, auth)
    unit = make_unit(api, auth, project["id"], price="12345678.07", area_sqft="1250.50")
    got = ok(api.get(f"{UNITS}/{unit['id']}", headers=auth(ADMIN)))
    assert Decimal(got["price"]) == Decimal("12345678.07")
    assert Decimal(got["area_sqft"]) == Decimal("1250.50")


@pytest.mark.parametrize(
    "bad",
    [
        {"price": "-1"},
        {"price": "10000000001"},
        {"price": "1.234"},
        {"area_sqft": "0"},
        {"unit_type": "castle"},
        {"unit_code": ""},
        {"unit_code": "A 1"},
        {"unit_code": "<b>"},
    ],
)
def test_impossible_units_are_refused(api, auth, world, bad) -> None:
    project = make_project(api, auth)
    body = {
        "project_id": project["id"],
        "unit_code": "A-1",
        "unit_type": "apartment",
        "price": "100",
        **bad,
    }
    assert api.post(UNITS, json=body, headers=auth(ADMIN)).status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"tenant_id": "00000000-0000-0000-0000-000000000000"},
        {"status": "reserved"},
        {"status": "sold"},
        {"version": 7},
        {"currency": "USD"},
    ],
)
def test_the_client_cannot_send_server_controlled_fields(api, auth, world, extra) -> None:
    project = make_project(api, auth)
    body = {
        "project_id": project["id"],
        "unit_code": "A-1",
        "unit_type": "apartment",
        "price": "100",
        **extra,
    }
    assert api.post(UNITS, json=body, headers=auth(ADMIN)).status_code == 422


def test_a_unit_code_is_unique_inside_its_project_only(api, auth, world) -> None:
    one = make_project(api, auth, name="One")
    two = make_project(api, auth, name="Two")
    make_unit(api, auth, one["id"], code="A-101")
    clash = api.post(
        UNITS,
        json={"project_id": one["id"], "unit_code": "a-101", "unit_type": "plot", "price": "1"},
        headers=auth(ADMIN),
    )
    assert clash.status_code == 409 and clash.json()["code"] == "already_exists"
    assert make_unit(api, auth, two["id"], code="A-101")["unit_code"] == "A-101"


def test_a_staff_member_may_block_and_release_a_unit(api, auth, world) -> None:
    unit = make_unit(api, auth, make_project(api, auth)["id"])
    url = f"{UNITS}/{unit['id']}"
    blocked = ok(api.patch(url, json={"version": 1, "status": "blocked"}, headers=auth(ADMIN)))
    assert blocked["status"] == "blocked" and blocked["version"] == 2
    released = ok(api.patch(url, json={"version": 2, "status": "available"}, headers=auth(ADMIN)))
    assert released["status"] == "available"


@pytest.mark.parametrize("status", ["reserved", "sold", "nonsense"])
def test_a_person_cannot_set_reserved_or_sold(api, auth, world, status) -> None:
    unit = make_unit(api, auth, make_project(api, auth)["id"])
    response = api.patch(
        f"{UNITS}/{unit['id']}", json={"version": 1, "status": status}, headers=auth(ADMIN)
    )
    assert response.status_code == 422


def test_a_reserved_unit_cannot_be_edited_or_released_by_hand(api, auth, world, db_session) -> None:
    unit = make_unit(api, auth, make_project(api, auth)["id"])
    bind_tenant(db_session, world.users[ADMIN].tenant_id)
    db_session.execute(
        text("update property_units set status = 'reserved' where id = :i"), {"i": unit["id"]}
    )
    url = f"{UNITS}/{unit['id']}"
    for body in ({"status": "available"}, {"price": "1"}, {"unit_code": "Z"}):
        response = api.patch(url, json={"version": 1, **body}, headers=auth(ADMIN))
        assert response.status_code == 409, body
        assert response.json()["code"] == "unit_status_locked"
    # the row is exactly as the reservation left it
    got = ok(api.get(url, headers=auth(ADMIN)))
    assert got["status"] == "reserved" and Decimal(got["price"]) == Decimal("4500000.50")


def test_a_unit_change_needs_the_version_that_was_read(api, auth, world) -> None:
    unit = make_unit(api, auth, make_project(api, auth)["id"])
    url = f"{UNITS}/{unit['id']}"
    ok(api.patch(url, json={"version": 1, "price": "5000000"}, headers=auth(ADMIN)))
    stale = api.patch(url, json={"version": 1, "price": "6000000"}, headers=auth(ADMIN))
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"


def test_units_can_be_filtered(api, auth, world) -> None:
    one = make_project(api, auth, name="One")
    two = make_project(api, auth, name="Two")
    make_unit(api, auth, one["id"], code="A-1", unit_type="apartment")
    plot = make_unit(api, auth, one["id"], code="P-1", unit_type="plot")
    make_unit(api, auth, two["id"], code="A-1", unit_type="apartment")
    ok(
        api.patch(
            f"{UNITS}/{plot['id']}", json={"version": 1, "status": "blocked"}, headers=auth(ADMIN)
        )
    )
    admin = auth(ADMIN)
    assert ok(api.get(UNITS, headers=admin))["total"] == 3
    assert ok(api.get(UNITS, params={"project_id": one["id"]}, headers=admin))["total"] == 2
    assert ok(api.get(UNITS, params={"status": "blocked"}, headers=admin))["total"] == 1
    assert ok(api.get(UNITS, params={"unit_type": "apartment"}, headers=admin))["total"] == 2
    assert ok(api.get(UNITS, params={"q": "p-"}, headers=admin))["total"] == 1
    assert api.get(UNITS, params={"status": "weird"}, headers=admin).status_code == 422


# --- tenant isolation and ID tampering -------------------------------------------------


def test_another_organisation_cannot_see_or_change_these(api, auth, world) -> None:
    project = make_project(api, auth)
    unit = make_unit(api, auth, project["id"])
    beta = auth("beta.admin")
    assert ok(api.get(PROJECTS, headers=beta))["total"] == 0
    assert ok(api.get(UNITS, headers=beta))["total"] == 0
    assert api.get(f"{PROJECTS}/{project['id']}", headers=beta).status_code == 404
    assert api.get(f"{UNITS}/{unit['id']}", headers=beta).status_code == 404
    patch = api.patch(
        f"{UNITS}/{unit['id']}", json={"version": 1, "status": "blocked"}, headers=beta
    )
    assert patch.status_code == 404
    patch = api.patch(f"{PROJECTS}/{project['id']}", json={"version": 1, "name": "X"}, headers=beta)
    assert patch.status_code == 404


def test_a_unit_cannot_be_put_in_another_organisations_project(api, auth, world) -> None:
    project = make_project(api, auth)
    body = {
        "project_id": project["id"],
        "unit_code": "A-1",
        "unit_type": "plot",
        "price": "1",
    }
    response = api.post(UNITS, json=body, headers=auth("beta.admin"))
    assert response.status_code == 404 and response.json()["code"] == "project_not_found"


def test_made_up_ids_are_not_found(api, auth, world) -> None:
    missing = "00000000-0000-4000-8000-000000000001"
    assert api.get(f"{UNITS}/{missing}", headers=auth(ADMIN)).status_code == 404
    assert api.get(f"{PROJECTS}/{missing}", headers=auth(ADMIN)).status_code == 404
    body = {"project_id": missing, "unit_code": "A", "unit_type": "plot", "price": "1"}
    assert api.post(UNITS, json=body, headers=auth(ADMIN)).status_code == 404
    assert api.get(f"{UNITS}/not-an-id", headers=auth(ADMIN)).status_code == 422


def test_the_public_interface_hides_other_organisations(api, auth, world, db_session) -> None:
    unit = make_unit(api, auth, make_project(api, auth)["id"])
    alpha, beta = world.users[ADMIN].tenant_id, world.users["beta.admin"].tenant_id
    bind_tenant(db_session, alpha)
    info = units_api.unit_info(db_session, alpha, unit["id"])
    assert info is not None and info.project_name == "Green Valley" and info.status == "available"
    assert info.price == Decimal("4500000.50")
    bind_tenant(db_session, beta)
    assert units_api.unit_info(db_session, beta, unit["id"]) is None


# --- audit and the database's own locks ----------------------------------------------------


def test_changes_are_audited_with_the_old_and_new_price(api, auth, world, db_session) -> None:
    unit = make_unit(api, auth, make_project(api, auth)["id"])
    ok(
        api.patch(
            f"{UNITS}/{unit['id']}",
            json={"version": 1, "price": "5000000.25"},
            headers=auth(ADMIN),
        )
    )
    bind_tenant(db_session, world.users[ADMIN].tenant_id)
    actions = {a.action for a in db_session.scalars(select(AuditLog)).all()}
    assert {"project.created", "unit.created", "unit.updated"} <= actions
    updated = db_session.scalars(select(AuditLog).where(AuditLog.action == "unit.updated")).one()
    assert updated.changes["price"] == {"old": "4500000.50", "new": "5000000.25"}


def _insert_unit(db_session, world, **over: Any) -> None:
    tenant = world.users[ADMIN].tenant_id
    bind_tenant(db_session, tenant)
    project = db_session.execute(
        text("insert into property_projects (tenant_id, name) values (:t, 'DB') returning id"),
        {"t": tenant},
    ).scalar_one()
    row = {
        "t": tenant,
        "p": project,
        "c": "A",
        "ty": "plot",
        "pr": 1,
        "st": "available",
        **over,
    }
    db_session.execute(
        text(
            "insert into property_units "
            "(tenant_id, project_id, unit_code, unit_type, price, status)"
            " values (:t, :p, :c, :ty, :pr, :st)"
        ),
        row,
    )


@pytest.mark.parametrize(
    "bad",
    [{"ty": "castle"}, {"st": "gone"}, {"pr": -1}, {"c": ""}],
)
def test_the_database_refuses_impossible_units(db_session, world, bad) -> None:
    with pytest.raises((IntegrityError, DBAPIError)):
        with db_session.begin_nested():
            _insert_unit(db_session, world, **bad)


def test_the_database_refuses_a_unit_in_another_tenants_project(db_session, world) -> None:
    alpha, beta = world.users[ADMIN].tenant_id, world.users["beta.admin"].tenant_id
    bind_tenant(db_session, alpha)
    project = db_session.execute(
        text("insert into property_projects (tenant_id, name) values (:t, 'Mine') returning id"),
        {"t": alpha},
    ).scalar_one()
    bind_tenant(db_session, beta)
    with pytest.raises((IntegrityError, DBAPIError)):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "insert into property_units "
                    "(tenant_id, project_id, unit_code, unit_type, price)"
                    " values (:t, :p, 'A', 'plot', 1)"
                ),
                {"t": beta, "p": project},
            )


def test_without_an_organisation_no_row_can_be_read(api, auth, world, db_session) -> None:
    make_unit(api, auth, make_project(api, auth)["id"])
    db_session.info.pop("tenant_id", None)
    db_session.execute(text("select set_config('app.tenant_id', '', true)"))
    assert db_session.scalar(text("select count(*) from property_units")) == 0
    assert db_session.scalar(text("select count(*) from property_projects")) == 0


def test_the_service_itself_refuses_a_reader_who_tries_to_change(world, db_session) -> None:
    """The router also checks; this proves the service does not rely on it."""
    agent = principal_for(world.users["alpha.agent1"], Role.SALES_AGENT)
    bind_tenant(db_session, world.users["alpha.agent1"].tenant_id)
    with pytest.raises(ForbiddenError):
        service.create_project(db_session, agent, ProjectCreate(name="Sneaky"))
    support = principal_for(world.users["alpha.support"], Role.SUPPORT_AGENT)
    with pytest.raises(ForbiddenError):
        service.list_projects(db_session, support, q=None, active=None, limit=10, offset=0)
