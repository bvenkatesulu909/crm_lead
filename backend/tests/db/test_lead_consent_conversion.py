# ruff: noqa: F811 - pytest fixtures imported from test_leads_api are used as parameters
"""The e-mail answer travels with the person when a lead is converted (ADR 0036, FM1)."""

import uuid
from typing import Any

from app.modules.contacts.models import Contact
from tests.db.test_leads_api import api, auth, people, qualified_lead  # noqa: F401

LEADS = "/api/v1/leads"


def _convert(api, auth, db_session, consent: str | None) -> Contact:
    lead = qualified_lead(api, auth, "alpha.agent1")
    if consent is not None:
        body: dict[str, Any] = {"version": lead["version"], "email_consent": consent}
        done = api.patch(f"{LEADS}/{lead['id']}", json=body, headers=auth("alpha.agent1"))
        assert done.status_code == 200, done.text
    response = api.post(f"{LEADS}/{lead['id']}/convert", json={}, headers=auth("alpha.agent1"))
    assert response.status_code == 201, response.text
    contact = db_session.get(Contact, uuid.UUID(response.json()["contact_id"]))
    assert isinstance(contact, Contact)
    return contact


def test_a_withdrawn_answer_survives_conversion(api, auth, people, db_session) -> None:
    contact = _convert(api, auth, db_session, "withdrawn")
    assert contact.email_consent == "withdrawn"
    assert contact.email_consent_at is not None


def test_a_granted_answer_survives_conversion(api, auth, people, db_session) -> None:
    contact = _convert(api, auth, db_session, "granted")
    assert contact.email_consent == "granted"
    assert contact.email_consent_at is not None


def test_an_unknown_answer_stays_unknown_on_conversion(api, auth, people, db_session) -> None:
    contact = _convert(api, auth, db_session, None)
    assert (contact.email_consent, contact.email_consent_at) == ("unknown", None)
