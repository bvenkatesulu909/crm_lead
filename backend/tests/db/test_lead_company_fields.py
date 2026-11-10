# ruff: noqa: F811 - pytest fixtures imported from test_leads_api are used as parameters
"""The company behind a lead: website, industry and size band (BP-02, ADR 0026 step EN1).

Checked by the API and again by the database; copied to the account on conversion (a new account
gets them, an existing one only where it has nothing yet).
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.modules.accounts.models import Account
from app.modules.leads.models import Lead
from tests.db.conftest import setup_lead_context
from tests.db.test_leads_api import (  # noqa: F401 - fixtures
    api,
    auth,
    create,
    people,
    qualified_lead,
)

LEADS = "/api/v1/leads"
COMPANY = {
    "company_website": "Example-Builders.in/",
    "company_industry": "real_estate",
    "company_size": "11-50",
}
STORED = {
    "company_website": "https://example-builders.in",
    "company_industry": "real_estate",
    "company_size": "11-50",
}


def patch(api, auth, lead: dict[str, Any], user: str = "alpha.agent1", **fields: Any) -> Any:
    return api.patch(
        f"{LEADS}/{lead['id']}", json={"version": lead["version"], **fields}, headers=auth(user)
    )


# --- the API ------------------------------------------------------------------------------------


def test_a_lead_is_created_with_its_company_details(api, auth, db_session) -> None:
    lead = create(api, auth, "alpha.agent1", last_name="Rao", **COMPANY)
    assert {k: lead[k] for k in STORED} == STORED
    read = api.get(f"{LEADS}/{lead['id']}", headers=auth("alpha.agent1")).json()
    assert {k: read[k] for k in STORED} == STORED
    [audit] = db_session.scalars(
        select(AuditLog).where(AuditLog.entity_id == uuid.UUID(lead["id"]))
    ).all()
    assert audit.changes["company_website"] == {"old": None, "new": "https://example-builders.in"}


def test_the_fields_are_optional(api, auth) -> None:
    lead = create(api, auth, "alpha.agent1", last_name="Plain")
    assert [lead[k] for k in STORED] == [None, None, None]


def test_the_fields_can_be_changed_and_cleared(api, auth, db_session) -> None:
    lead = create(api, auth, "alpha.agent1", last_name="Rao", **COMPANY)
    changed = patch(api, auth, lead, company_size="51-200", company_website="https://other.in")
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert (body["company_size"], body["company_website"]) == ("51-200", "https://other.in")
    cleared = patch(api, auth, body, company_industry=None, company_website=None)
    assert cleared.status_code == 200, cleared.text
    assert (cleared.json()["company_industry"], cleared.json()["company_website"]) == (None, None)
    updates = db_session.scalars(
        select(AuditLog)
        .where(AuditLog.entity_id == uuid.UUID(lead["id"]), AuditLog.action == "lead.updated")
        .order_by(AuditLog.seq)
    ).all()
    assert updates[0].changes == {
        "company_size": {"old": "11-50", "new": "51-200"},
        "company_website": {"old": "https://example-builders.in", "new": "https://other.in"},
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"company_industry": "castles"},
        {"company_industry": "Real estate"},  # the label is not a key
        {"company_size": "12"},
        {"company_size": "1000+"},
        {"company_website": "https://example.com/about"},
        {"company_website": "http://127.0.0.1"},
        {"company_website": "https://example.com:8080"},
        {"company_website": "jamie@example.com"},
        {"company_website": "javascript:alert(1)"},
        {"company_website": "   "},
    ],
)
def test_impossible_values_are_refused(api, auth, fields) -> None:
    response = api.post(LEADS, json={"last_name": "Bad", **fields}, headers=auth("alpha.agent1"))
    assert response.status_code == 422, response.text


def test_another_agent_or_organisation_cannot_change_them(api, auth) -> None:
    lead = create(api, auth, "alpha.agent1", last_name="Rao", **COMPANY)
    assert patch(api, auth, lead, "alpha.agent2", company_size="1-10").status_code == 404
    assert patch(api, auth, lead, "beta.admin", company_size="1-10").status_code == 404


# --- the database refuses impossible rows by itself ---------------------------------------------


def _insert(people, db_session: Session, **values: Any) -> None:
    owner = people["alpha.agent1"]
    setup_lead_context(db_session, owner.tenant_id, owner.id)
    db_session.add(Lead(tenant_id=owner.tenant_id, owner_id=owner.id, last_name="Db", **values))
    db_session.flush()


@pytest.mark.parametrize(
    ("values", "rule"),
    [
        ({"company_website": "http://example.com"}, "company_website_shape"),
        ({"company_website": "https://example.com/about"}, "company_website_shape"),
        ({"company_website": "https://Example.com"}, "company_website_shape"),
        ({"company_website": "https://localhost"}, "company_website_shape"),
        ({"company_website": "https://example.com:443"}, "company_website_shape"),
        ({"company_industry": "castles"}, "company_industry_allowed"),
        ({"company_size": "lots"}, "company_size_allowed"),
    ],
)
def test_the_database_checks_the_fields(people, db_session, values, rule) -> None:
    with pytest.raises(IntegrityError, match=rule), db_session.begin_nested():
        _insert(people, db_session, **values)


def test_the_database_accepts_good_values(people, db_session) -> None:
    _insert(people, db_session, **STORED)
    _insert(people, db_session, company_website="https://xn--bcher-kva.example")


# --- conversion ---------------------------------------------------------------------------------


def test_a_new_account_gets_the_website_and_the_industry(api, auth, db_session) -> None:
    lead = qualified_lead(api, auth, "alpha.agent1", company_name="Example Builders", **COMPANY)
    response = api.post(f"{LEADS}/{lead['id']}/convert", json={}, headers=auth("alpha.agent1"))
    assert response.status_code == 201, response.text
    account = db_session.get(Account, uuid.UUID(response.json()["account_id"]))
    assert account is not None
    assert (account.website, account.industry) == ("https://example-builders.in", "Real estate")


def test_an_existing_account_is_only_filled_where_it_is_empty(
    api, auth, people, db_session, committed_world
) -> None:
    agent = people["alpha.agent1"]
    known = Account(
        tenant_id=agent.tenant_id, name="Known", owner_id=agent.id, industry="Construction"
    )
    committed_world.add(known)
    committed_world.commit()
    lead = qualified_lead(api, auth, "alpha.agent1", **COMPANY)
    response = api.post(
        f"{LEADS}/{lead['id']}/convert",
        json={"account": {"existing_account_id": str(known.id)}},
        headers=auth("alpha.agent1"),
    )
    assert response.status_code == 201, response.text
    db_session.expire_all()
    account = db_session.get(Account, known.id)
    assert account is not None
    # The website was empty and is filled; the industry the account had is kept.
    assert (account.website, account.industry) == ("https://example-builders.in", "Construction")


def test_a_lead_without_company_details_changes_nothing_on_conversion(
    api, auth, people, db_session, committed_world
) -> None:
    agent = people["alpha.agent1"]
    known = Account(tenant_id=agent.tenant_id, name="Known", owner_id=agent.id)
    committed_world.add(known)
    committed_world.commit()
    lead = qualified_lead(api, auth, "alpha.agent1")
    response = api.post(
        f"{LEADS}/{lead['id']}/convert",
        json={"account": {"existing_account_id": str(known.id)}},
        headers=auth("alpha.agent1"),
    )
    assert response.status_code == 201, response.text
    db_session.expire_all()
    account = db_session.get(Account, known.id)
    assert account is not None
    assert (account.website, account.industry) == (None, None)
