"""Communication Center, step CC1: the database layer (migration 0038, ADR 0012).

The table rules are enforced by PostgreSQL itself, so these tests go straight to the database
as the restricted crm_app role (the one the API uses). Setup data is built as crm_owner.
"""

# ruff: noqa: F811 - the imported world fixture is used as a test parameter

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.db import bind_tenant, clear_tenant
from app.modules.communications.models import EmailMessage, EmailTemplate
from app.modules.contacts.models import Contact
from app.modules.leads.models import Lead
from tests.db.test_quotes_api import world  # noqa: F401


@pytest.fixture
def leads(world, committed_world: Session) -> dict[str, uuid.UUID]:
    """One lead per organisation (the shared quotes world has accounts and contacts only)."""
    alpha_lead = Lead(
        tenant_id=world.users["alpha.agent1"].tenant_id,
        last_name="Lead A",
        email="lead.a@example.test",
        owner_id=world.users["alpha.agent1"].id,
    )
    beta_lead = Lead(
        tenant_id=world.users["beta.agent"].tenant_id,
        last_name="Lead B",
        email="lead.b@example.test",
        owner_id=world.users["beta.agent"].id,
    )
    committed_world.add_all([alpha_lead, beta_lead])
    committed_world.commit()
    return {"alpha": alpha_lead.id, "beta": beta_lead.id}


def _message(world, **values: Any) -> EmailMessage:
    """A valid queued e-mail to contact C1 in tenant alpha; tests change one field at a time."""
    base: dict[str, Any] = {
        "tenant_id": world.users["alpha.agent1"].tenant_id,
        "direction": "outbound",
        "status": "queued",
        "contact_id": world.ids["C1"],
        "to_address": "c1@example.test",
        "subject": "Your enquiry",
        "body": "Hello, thank you for your interest.",
        "sent_by_user_id": world.users["alpha.agent1"].id,
    }
    base.update(values)
    return EmailMessage(**base)


def _template(world, **values: Any) -> EmailTemplate:
    base: dict[str, Any] = {
        "tenant_id": world.users["alpha.manager"].tenant_id,
        "name": "First reply",
        "subject": "Thank you, {{recipient.first_name}}",
        "body": "Hello {{recipient.first_name}}, thank you for contacting us.",
        "created_by_user_id": world.users["alpha.manager"].id,
    }
    base.update(values)
    return EmailTemplate(**base)


def _alpha(world, db_session: Session) -> None:
    bind_tenant(db_session, world.users["alpha.agent1"].tenant_id)


def _refused(db_session: Session, row: Any, match: str) -> None:
    with pytest.raises(IntegrityError, match=match), db_session.begin_nested():
        db_session.add(row)
        db_session.flush()


# --- e-mail templates -------------------------------------------------------------------------


def test_a_template_gets_sensible_defaults(world, db_session) -> None:
    _alpha(world, db_session)
    template = _template(world)
    db_session.add(template)
    db_session.flush()
    db_session.refresh(template)
    assert template.is_active is True
    assert template.version == 1
    assert template.created_at is not None


def test_template_names_are_unique_inside_one_organisation(world, db_session) -> None:
    _alpha(world, db_session)
    db_session.add(_template(world))
    db_session.flush()
    _refused(db_session, _template(world), "uq_email_templates_tenant_id_name")
    # The same name in the OTHER organisation is fine.
    beta = world.users["beta.admin"].tenant_id
    bind_tenant(db_session, beta)
    db_session.add(
        _template(world, tenant_id=beta, created_by_user_id=world.users["beta.admin"].id)
    )
    db_session.flush()


@pytest.mark.parametrize(
    "values, rule",
    [
        ({"name": "   "}, "name_not_blank"),
        ({"subject": ""}, "subject_not_blank"),
        ({"body": ""}, "body_not_blank"),
        ({"body": "x" * 20_001}, "body_length"),
    ],
)
def test_the_database_refuses_empty_or_huge_templates(world, db_session, values, rule) -> None:
    _alpha(world, db_session)
    _refused(db_session, _template(world, **values), rule)


def test_a_template_cannot_name_a_user_of_another_organisation(world, db_session) -> None:
    _alpha(world, db_session)
    _refused(
        db_session,
        _template(world, created_by_user_id=world.users["beta.admin"].id),
        "fk_email_templates_tenant_id_created_by_user_id_users",
    )


# --- e-mail messages --------------------------------------------------------------------------


def test_a_queued_e_mail_to_a_contact_is_stored(world, db_session) -> None:
    _alpha(world, db_session)
    message = _message(world, account_id=world.ids["A1"])
    db_session.add(message)
    db_session.flush()
    db_session.refresh(message)
    assert message.status == "queued"
    assert message.sent_at is None
    assert message.created_at is not None


def test_an_e_mail_to_a_lead_and_a_logged_received_e_mail_are_stored(
    world, leads, db_session
) -> None:
    _alpha(world, db_session)
    db_session.add(_message(world, contact_id=None, lead_id=leads["alpha"]))
    db_session.add(_message(world, direction="inbound_logged", status="logged"))
    db_session.flush()


def test_a_sent_e_mail_has_a_send_time_and_a_template_link(world, db_session) -> None:
    _alpha(world, db_session)
    template = _template(world)
    db_session.add(template)
    db_session.flush()
    message = _message(world, status="sent", sent_at=text("now()"), template_id=template.id)
    db_session.add(message)
    db_session.flush()
    assert message.template_id == template.id


@pytest.mark.parametrize(
    "values, rule",
    [
        ({"direction": "sideways"}, "direction_allowed"),
        ({"status": "lost"}, "status_allowed"),
        # Exactly one recipient: a lead OR a contact.
        ({"contact_id": None}, "one_recipient"),
        # A received e-mail is "logged"; an outgoing one is never "logged".
        ({"direction": "inbound_logged", "status": "queued"}, "logged_means_inbound"),
        ({"status": "logged"}, "logged_means_inbound"),
        # "sent" and the send time always go together.
        ({"status": "sent"}, "sent_has_time"),
        ({"sent_at": text("now()")}, "sent_has_time"),
        ({"to_address": "not-an-address"}, "address_shape"),
        ({"subject": " "}, "subject_not_blank"),
        ({"body": ""}, "body_not_blank"),
        ({"body": "x" * 50_001}, "body_length"),
        ({"error_code": "smtp_down"}, "error_only_if_failed"),
    ],
)
def test_the_database_refuses_impossible_messages(world, db_session, values, rule) -> None:
    _alpha(world, db_session)
    _refused(db_session, _message(world, **values), rule)


def test_a_message_has_one_recipient_not_two(world, leads, db_session) -> None:
    _alpha(world, db_session)
    _refused(db_session, _message(world, lead_id=leads["alpha"]), "one_recipient")


def test_a_message_links_to_at_most_one_record_and_never_for_a_lead(
    world, leads, db_session
) -> None:
    _alpha(world, db_session)
    _refused(
        db_session,
        _message(world, account_id=world.ids["A1"], opportunity_id=world.ids["O1"]),
        "one_related_record",
    )
    # A lead has no account or deal yet, so its e-mails can't be filed under one.
    _refused(
        db_session,
        _message(world, contact_id=None, lead_id=leads["alpha"], account_id=world.ids["A1"]),
        "lead_has_no_related_record",
    )


def test_a_failed_e_mail_keeps_a_reason_code(world, db_session) -> None:
    _alpha(world, db_session)
    db_session.add(_message(world, status="failed", error_code="recipient_refused"))
    db_session.flush()


def test_a_message_cannot_point_at_another_organisations_records(world, leads, db_session) -> None:
    """ID tampering at the database level: alpha's message to beta's records is refused."""
    _alpha(world, db_session)
    beta_template = uuid.uuid4()
    cases = [
        ({"contact_id": None, "lead_id": leads["beta"]}, "fk_email_messages_tenant_id_lead_id"),
        ({"account_id": world.ids["B1"]}, "fk_email_messages_tenant_id_account_id"),
        ({"sent_by_user_id": world.users["beta.agent"].id}, "fk_email_messages_tenant_id_sent_by"),
        ({"template_id": beta_template}, "fk_email_messages_tenant_id_template_id"),
    ]
    for values, rule in cases:
        _refused(db_session, _message(world, **values), rule)


def test_tenants_only_see_their_own_messages_and_templates(
    world, committed_world, db_session
) -> None:
    alpha = world.users["alpha.agent1"].tenant_id
    beta = world.users["beta.agent"].tenant_id
    # Built as the owner (it bypasses RLS), then read back as the restricted app role.
    beta_contact = Contact(
        tenant_id=beta,
        last_name="Beta contact",
        account_id=world.ids["B1"],
        owner_id=world.users["beta.agent"].id,
    )
    committed_world.add(beta_contact)
    committed_world.flush()
    committed_world.add_all(
        [
            _message(world, subject="Alpha mail"),
            _message(
                world,
                tenant_id=beta,
                contact_id=beta_contact.id,
                sent_by_user_id=world.users["beta.agent"].id,
                subject="Beta mail",
            ),
            _template(world, name="Alpha template"),
            _template(
                world,
                tenant_id=beta,
                name="Beta template",
                created_by_user_id=world.users["beta.admin"].id,
            ),
        ]
    )
    committed_world.commit()

    clear_tenant(db_session)
    assert db_session.scalars(select(EmailMessage)).all() == []  # no tenant: nothing visible
    assert db_session.scalars(select(EmailTemplate)).all() == []
    bind_tenant(db_session, alpha)
    assert [m.subject for m in db_session.scalars(select(EmailMessage))] == ["Alpha mail"]
    assert [t.name for t in db_session.scalars(select(EmailTemplate))] == ["Alpha template"]
    bind_tenant(db_session, beta)
    assert [m.subject for m in db_session.scalars(select(EmailMessage))] == ["Beta mail"]
    assert [t.name for t in db_session.scalars(select(EmailTemplate))] == ["Beta template"]


def test_a_tenant_cannot_write_into_another_tenant(world, db_session) -> None:
    beta = world.users["beta.admin"].tenant_id
    _alpha(world, db_session)
    planted = [
        _template(world, tenant_id=beta, created_by_user_id=world.users["beta.admin"].id),
        _message(world, tenant_id=beta, sent_by_user_id=world.users["beta.agent"].id),
    ]
    for row in planted:
        with pytest.raises(ProgrammingError, match="row-level security"):
            with db_session.begin_nested():
                db_session.add(row)
                db_session.flush()


def test_messages_can_change_status_but_never_be_deleted(world, db_session) -> None:
    _alpha(world, db_session)
    message = _message(world)
    db_session.add(message)
    db_session.flush()
    # The worker moves the status forward...
    db_session.execute(
        text("update email_messages set status = 'sent', sent_at = now() where id = :id"),
        {"id": message.id},
    )
    # ...but the application can never remove history.
    with pytest.raises(DBAPIError, match="permission denied"), db_session.begin_nested():
        db_session.execute(text("delete from email_messages where id = :id"), {"id": message.id})
