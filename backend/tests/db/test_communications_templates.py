# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Communication Center, step CC3 (ADR 0012): e-mail templates through the real API.

Managers and tenant admins maintain templates; everyone who may send e-mails uses the active
ones. Placeholders come from a fixed list and are filled by plain text replacement.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.modules.contacts.models import Contact
from app.modules.leads.models import Lead
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    World,
    api,
    auth,
    code_of,
    ok,
    world,
)

TEMPLATES = "/api/v1/communications/templates"
GREETING = "Hello {{recipient.first_name}}, thank you for contacting {{organisation.name}}."


def create(api: TestClient, auth, user: str = "alpha.manager", **body: Any) -> Any:
    payload = {"name": "First reply", "subject": "Thank you, {{recipient.first_name}}"}
    payload |= {"body": GREETING, **body}
    return api.post(TEMPLATES, json=payload, headers=auth(user))


def patch(api: TestClient, auth, template: Any, user: str = "alpha.manager", **body: Any) -> Any:
    return api.patch(
        f"{TEMPLATES}/{template['id']}",
        json={"version": template["version"], **body},
        headers=auth(user),
    )


def preview(api: TestClient, auth, template: Any, user: str = "alpha.agent1", **body: Any) -> Any:
    return api.post(f"{TEMPLATES}/{template['id']}/preview", json=body, headers=auth(user))


def names(api: TestClient, auth, user: str, **params: Any) -> list[str]:
    return [t["name"] for t in ok(api.get(TEMPLATES, params=params, headers=auth(user)))]


def set_contact(db_session: Session, world: World, **values: Any) -> None:
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    db_session.execute(update(Contact).where(Contact.id == world.ids["C1"]).values(**values))
    db_session.flush()


# --- create, read, list -------------------------------------------------------------------------


def test_a_manager_creates_a_template_that_agents_can_use(api, auth, world) -> None:
    response = create(api, auth)
    template = ok(response, 201)
    assert response.headers["Location"] == f"{TEMPLATES}/{template['id']}"
    assert (template["is_active"], template["version"]) == (True, 1)
    assert template["created_by_user_id"] == str(world.users["alpha.manager"].id)
    assert names(api, auth, "alpha.agent1") == ["First reply"]
    assert names(api, auth, "alpha.support") == ["First reply"]
    got = ok(api.get(f"{TEMPLATES}/{template['id']}", headers=auth("alpha.agent1")))
    assert got["body"] == GREETING


def test_tenant_admins_may_manage_templates_too(api, auth, world) -> None:
    ok(create(api, auth, "alpha.admin"), 201)


@pytest.mark.parametrize("user", ["alpha.agent1", "alpha.support", "alpha.customer"])
def test_only_managers_and_admins_create_templates(api, auth, world, user) -> None:
    assert create(api, auth, user).status_code == 403


def test_customers_cannot_see_templates(api, auth, world) -> None:
    template = ok(create(api, auth), 201)
    assert api.get(TEMPLATES, headers=auth("alpha.customer")).status_code == 403
    url = f"{TEMPLATES}/{template['id']}"
    assert api.get(url, headers=auth("alpha.customer")).status_code == 403


def test_another_organisation_cannot_see_or_change_a_template(api, auth, world) -> None:
    template = ok(create(api, auth), 201)
    url = f"{TEMPLATES}/{template['id']}"
    assert code_of(api.get(url, headers=auth("beta.admin"))) == (404, "template_not_found")
    assert patch(api, auth, template, "beta.admin", name="Stolen").status_code == 404
    assert preview(api, auth, template, "beta.agent").status_code == 404
    assert names(api, auth, "beta.admin") == []
    assert api.get(f"{TEMPLATES}/{uuid.uuid4()}", headers=auth("alpha.manager")).status_code == 404


# --- validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"name": " "},
        {"subject": ""},
        {"body": "   "},
        {"body": "x" * 20_001},
        {"name": "x" * 121},
        {"tenant_id": str(uuid.uuid4())},  # server-controlled
        {"created_by_user_id": str(uuid.uuid4())},  # server-controlled
        {"version": 3},  # only for changes
    ],
)
def test_invalid_templates_are_refused(api, auth, world, body) -> None:
    assert create(api, auth, **body).status_code == 422


@pytest.mark.parametrize(
    "field, text, problem",
    [
        ("body", "Dear {{recipient.salary}}", "recipient.salary"),
        ("body", "{{ system.password }}", "system.password"),
        ("subject", "Hi {{recipient.FIRST_NAME}}", "recipient.FIRST_NAME"),
        ("body", "Hello {{recipient.first_name", "{{"),  # never closed
        ("body", "Hello recipient.first_name}}", "}}"),  # never opened
        ("body", "{{}}", "{{}}"),
    ],
)
def test_unknown_or_broken_placeholders_are_refused(api, auth, world, field, text, problem):
    response = create(api, auth, **{field: text})
    assert code_of(response) == (422, "unknown_placeholder")
    assert problem in response.json()["detail"]


def test_names_are_unique_per_organisation(api, auth, world) -> None:
    ok(create(api, auth), 201)
    assert code_of(create(api, auth)) == (409, "template_name_taken")
    ok(create(api, auth, "beta.admin"), 201)  # the same name in another organisation is fine


# --- edit and deactivate ------------------------------------------------------------------------


def test_editing_a_template(api, auth, world, db_session) -> None:
    template = ok(create(api, auth), 201)
    changed = ok(patch(api, auth, template, name="Welcome", body="Hi {{recipient.full_name}}"))
    assert (changed["name"], changed["version"]) == ("Welcome", 2)
    assert changed["updated_by_user_id"] == str(world.users["alpha.manager"].id)
    # A second click with the old version is a conflict, not a silent overwrite.
    assert code_of(patch(api, auth, template, name="Lost update")) == (409, "version_conflict")
    assert code_of(patch(api, auth, changed, body="{{recipient.age}}")) == (
        422,
        "unknown_placeholder",
    )
    assert patch(api, auth, changed).status_code == 422  # nothing to change
    assert patch(api, auth, changed, "alpha.agent1", name="Mine").status_code == 403

    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    audits = db_session.scalars(
        select(AuditLog)
        .where(AuditLog.entity_id == uuid.UUID(template["id"]))
        .order_by(AuditLog.seq)
    ).all()
    assert [a.action for a in audits] == ["template.created", "template.updated"]
    assert audits[1].changes["name"] == {"old": "First reply", "new": "Welcome"}
    assert audits[1].changes["body"] == {"changed": True}  # what changed, not the whole text


def test_renaming_onto_another_template_is_refused(api, auth, world) -> None:
    ok(create(api, auth), 201)
    second = ok(create(api, auth, name="Follow-up"), 201)
    assert code_of(patch(api, auth, second, name="First reply")) == (409, "template_name_taken")


def test_a_deactivated_template_is_hidden_from_agents(api, auth, world) -> None:
    template = ok(create(api, auth), 201)
    off = ok(patch(api, auth, template, is_active=False))
    assert off["is_active"] is False
    assert names(api, auth, "alpha.agent1") == []
    assert names(api, auth, "alpha.agent1", include_inactive=True) == []  # agents: active only
    assert names(api, auth, "alpha.manager") == []
    assert names(api, auth, "alpha.manager", include_inactive=True) == ["First reply"]
    url = f"{TEMPLATES}/{template['id']}"
    assert api.get(url, headers=auth("alpha.agent1")).status_code == 404
    assert api.get(url, headers=auth("alpha.manager")).status_code == 200
    assert preview(api, auth, template).status_code == 404
    ok(patch(api, auth, off, is_active=True))
    assert names(api, auth, "alpha.agent1") == ["First reply"]


# --- preview ------------------------------------------------------------------------------------


def test_preview_fills_in_a_contact(api, auth, world, db_session) -> None:
    set_contact(db_session, world, first_name="Ada", email="ada@example.test")
    template = ok(
        create(
            api,
            auth,
            subject="Hi {{recipient.first_name}}",
            body=(
                "{{recipient.full_name}} / {{recipient.company}} / {{sender.name}} / "
                "{{sender.email}} / {{organisation.name}}"
            ),
        ),
        201,
    )
    shown = ok(preview(api, auth, template, contact_id=str(world.ids["C1"])))
    assert shown["subject"] == "Hi Ada"
    assert shown["body"] == (
        "Ada C1 / Quote A1 / alpha.agent1 / alpha.agent1@example.test / Alpha Quotes Test"
    )
    assert shown["missing"] == []


def test_preview_fills_in_a_lead_and_reports_empty_values(
    api, auth, world, committed_world
) -> None:
    lead = Lead(
        tenant_id=world.users["alpha.agent1"].tenant_id,
        last_name="Rao",
        company_name="Rao Builders",
        owner_id=world.users["alpha.agent1"].id,
    )
    committed_world.add(lead)
    committed_world.commit()
    body = "Dear {{recipient.first_name}} of {{recipient.company}}"
    template = ok(create(api, auth, body=body), 201)
    shown = ok(preview(api, auth, template, lead_id=str(lead.id)))
    assert shown["body"] == "Dear  of Rao Builders"
    assert shown["missing"] == ["recipient.first_name"]  # the lead has no first name


def test_preview_without_a_recipient_uses_sample_values(api, auth, world) -> None:
    template = ok(create(api, auth), 201)
    shown = ok(preview(api, auth, template, "alpha.manager"))
    assert shown["subject"] == "Thank you, Ada"
    assert "thank you for contacting Alpha Quotes Test" in shown["body"]


def test_values_are_inserted_as_plain_text_once(api, auth, world, db_session) -> None:
    # A name that looks like a placeholder is NOT expanded again (no template injection).
    set_contact(db_session, world, first_name="{{sender.email}}")
    template = ok(create(api, auth), 201)
    shown = ok(preview(api, auth, template, contact_id=str(world.ids["C1"])))
    assert shown["subject"] == "Thank you, {{sender.email}}"
    assert "alpha.agent1@example.test" not in shown["body"]


def test_line_breaks_in_values_never_reach_the_subject(api, auth, world, db_session) -> None:
    set_contact(db_session, world, first_name="Ada\r\nBcc: victim@example.test")
    template = ok(create(api, auth), 201)
    shown = ok(preview(api, auth, template, contact_id=str(world.ids["C1"])))
    assert "\n" not in shown["subject"] and "\r" not in shown["subject"]


def test_preview_follows_the_recipients_read_rules(api, auth, world) -> None:
    template = ok(create(api, auth), 201)
    other = preview(api, auth, template, "alpha.agent2", contact_id=str(world.ids["C1"]))
    assert code_of(other) == (404, "recipient_not_found")
    both = preview(api, auth, template, contact_id=str(world.ids["C1"]), lead_id=str(uuid.uuid4()))
    assert both.status_code == 422
    assert preview(api, auth, template, "alpha.customer").status_code == 403


def test_the_placeholder_list_is_published(api, auth, world) -> None:
    listed = ok(api.get("/api/v1/communications/placeholders", headers=auth("alpha.agent1")))
    assert [p["name"] for p in listed] == [
        "recipient.first_name",
        "recipient.full_name",
        "recipient.company",
        "sender.name",
        "sender.email",
        "organisation.name",
    ]
    assert all(p["description"] for p in listed)
