# ruff: noqa: F811 - pytest fixtures imported from test_leads_api are used as parameters
"""Real-estate fields on leads (ADR 0013, step PC2 / ticket CRM-105).

property_type (apartment | villa | plot | commercial), budget_min_inr / budget_max_inr (whole
rupees, min <= max) and location. Checked by the API and again by the database itself.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.modules.leads.models import Lead
from tests.db.conftest import setup_lead_context
from tests.db.test_leads_api import api, auth, create, people  # noqa: F401 - fixtures

LEADS = "/api/v1/leads"
HOME = {
    "property_type": "apartment",
    "budget_min_inr": 12_000_000,  # 1.2 crore
    "budget_max_inr": 15_000_000,  # 1.5 crore
    "location": "Kokapet, Hyderabad",
}


def patch(api, auth, lead: dict[str, Any], user: str = "alpha.agent1", **fields: Any) -> Any:
    return api.patch(
        f"{LEADS}/{lead['id']}", json={"version": lead["version"], **fields}, headers=auth(user)
    )


# --- the API ------------------------------------------------------------------------------------


def test_a_lead_is_created_with_its_property_wishes(api, auth, db_session) -> None:
    lead = create(api, auth, "alpha.agent1", last_name="Rao", **HOME)
    assert {k: lead[k] for k in HOME} == HOME
    read = api.get(f"{LEADS}/{lead['id']}", headers=auth("alpha.agent1")).json()
    assert {k: read[k] for k in HOME} == HOME
    [audit] = db_session.scalars(
        select(AuditLog).where(AuditLog.entity_id == uuid.UUID(lead["id"]))
    ).all()
    assert audit.changes["property_type"] == {"old": None, "new": "apartment"}
    assert audit.changes["budget_max_inr"] == {"old": None, "new": 15_000_000}


def test_the_fields_are_optional(api, auth) -> None:
    lead = create(api, auth, "alpha.agent1", last_name="Plain")
    assert [lead[k] for k in HOME] == [None, None, None, None]


def test_the_fields_can_be_changed_and_cleared(api, auth, db_session) -> None:
    lead = create(api, auth, "alpha.agent1", last_name="Rao", **HOME)
    changed = patch(api, auth, lead, property_type="villa", budget_max_inr=30_000_000)
    assert changed.status_code == 200, changed.text
    assert (changed.json()["property_type"], changed.json()["budget_max_inr"]) == (
        "villa",
        30_000_000,
    )
    cleared = patch(api, auth, changed.json(), location=None, budget_min_inr=None)
    assert cleared.status_code == 200, cleared.text
    assert (cleared.json()["location"], cleared.json()["budget_min_inr"]) == (None, None)
    updates = db_session.scalars(
        select(AuditLog)
        .where(AuditLog.entity_id == uuid.UUID(lead["id"]), AuditLog.action == "lead.updated")
        .order_by(AuditLog.seq)
    ).all()
    assert updates[0].changes == {
        "property_type": {"old": "apartment", "new": "villa"},
        "budget_max_inr": {"old": 15_000_000, "new": 30_000_000},
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"property_type": "castle"},
        {"budget_min_inr": -1},
        {"budget_max_inr": 1_000_000_000_001},  # more than 1 lakh crore: surely a typo
        {"budget_min_inr": 1.5},  # whole rupees only
        {"budget_min_inr": "12 lakh"},
        {"location": "x" * 161},
        {"location": "   "},
        {"budget_min_inr": 20_000_000, "budget_max_inr": 10_000_000},  # min above max
    ],
)
def test_impossible_values_are_refused(api, auth, fields) -> None:
    response = api.post(LEADS, json={"last_name": "Bad", **fields}, headers=auth("alpha.agent1"))
    assert response.status_code == 422, response.text


def test_a_change_may_not_put_the_budget_out_of_order(api, auth) -> None:
    """Only one side sent: it's compared with the saved other side."""
    lead = create(api, auth, "alpha.agent1", last_name="Rao", **HOME)
    too_high = patch(api, auth, lead, budget_min_inr=20_000_000)  # saved max is 1.5 crore
    assert too_high.status_code == 422
    assert too_high.json()["code"] == "budget_out_of_order"
    too_low = patch(api, auth, lead, budget_max_inr=1_000_000)  # saved min is 1.2 crore
    assert too_low.json()["code"] == "budget_out_of_order"
    # Moving both at once in the right order is fine.
    both = patch(api, auth, lead, budget_min_inr=20_000_000, budget_max_inr=25_000_000)
    assert both.status_code == 200, both.text


def test_another_agent_cannot_change_the_fields(api, auth) -> None:
    lead = create(api, auth, "alpha.agent1", last_name="Rao", **HOME)
    assert patch(api, auth, lead, "alpha.agent2", location="Elsewhere").status_code == 404
    assert patch(api, auth, lead, "beta.admin", location="Elsewhere").status_code == 404


# --- the database refuses impossible rows by itself ---------------------------------------------


def _insert(people, db_session: Session, **values: Any) -> None:
    owner = people["alpha.agent1"]
    setup_lead_context(db_session, owner.tenant_id, owner.id)
    db_session.add(Lead(tenant_id=owner.tenant_id, owner_id=owner.id, last_name="Db", **values))
    db_session.flush()


@pytest.mark.parametrize(
    "values, rule",
    [
        ({"property_type": "castle"}, "property_type_allowed"),
        ({"budget_min_inr": -5}, "budget_not_negative"),
        ({"budget_max_inr": -5}, "budget_not_negative"),
        ({"budget_min_inr": 10, "budget_max_inr": 9}, "budget_in_order"),
    ],
)
def test_the_database_checks_the_fields(people, db_session, values, rule) -> None:
    with pytest.raises(IntegrityError, match=rule), db_session.begin_nested():
        _insert(people, db_session, **values)


def test_the_database_accepts_one_sided_budgets(people, db_session) -> None:
    _insert(people, db_session, budget_min_inr=5_000_000)
    _insert(
        people, db_session, budget_max_inr=9_000_000, property_type="plot", location="Shamshabad"
    )
