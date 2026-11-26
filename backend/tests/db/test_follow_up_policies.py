# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""The follow-up settings table (ADR 0036, FM3): newest row wins, rows are never changed, the
bounds are enforced by the database as well as by the rules, and organisations stay apart.

People come from test_quotes_api.py (tenant alpha has an admin and agents, tenant beta its own).
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.db import bind_tenant, clear_tenant
from app.modules.communications import follow_up_rules as rules
from app.modules.communications import repository
from app.modules.communications.models import EmailTemplate, FollowUpPolicy
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name


def alpha(world: World) -> uuid.UUID:
    return world.users["alpha.admin"].tenant_id


def beta(world: World) -> uuid.UUID:
    return world.users["beta.admin"].tenant_id


@pytest.fixture
def templates(world: World, committed_world: Session) -> dict[str, uuid.UUID]:
    """One template in each organisation (made as the table owner, then committed)."""
    made = {}
    for key, admin in (("alpha", "alpha.admin"), ("beta", "beta.admin")):
        template = EmailTemplate(
            tenant_id=world.users[admin].tenant_id,
            name="Follow-up",
            subject="Checking in",
            body="Hello {{recipient.first_name}}",
            created_by_user_id=world.users[admin].id,
        )
        committed_world.add(template)
        committed_world.flush()
        made[key] = template.id
    committed_world.commit()
    return made


def policy(templates: dict[str, uuid.UUID], **values: Any) -> rules.Policy:
    base: dict[str, Any] = {"enabled": True, "template_id": templates["alpha"]}
    return rules.Policy(**(base | values))


def insert(db_session: Session, world: World, **values: Any) -> None:
    """A raw row, as if code skipped the repository: only the database is left to refuse it."""
    admin = world.users["alpha.admin"]
    bind_tenant(db_session, admin.tenant_id)
    row = {"tenant_id": admin.tenant_id, "created_by_user_id": admin.id} | values
    db_session.add(FollowUpPolicy(**row))
    db_session.flush()


# --- reading and writing through the repository ----------------------------------------------


def test_without_a_saved_row_the_policy_is_the_default_and_off(world, db_session) -> None:
    bind_tenant(db_session, alpha(world))
    current = repository.current_follow_up_policy(db_session, alpha(world))
    assert current == rules.Policy()
    assert current.enabled is False


def test_the_newest_row_is_the_policy_in_force_and_the_history_is_kept(
    world, templates, db_session
) -> None:
    bind_tenant(db_session, alpha(world))
    admin = world.users["alpha.admin"].id
    repository.add_follow_up_policy(db_session, alpha(world), admin, policy(templates))
    repository.add_follow_up_policy(
        db_session, alpha(world), admin, policy(templates, enabled=False, monthly_cap=2)
    )
    current = repository.current_follow_up_policy(db_session, alpha(world))
    assert (current.enabled, current.monthly_cap) == (False, 2)
    history = repository.follow_up_policy_history(db_session, alpha(world))
    assert [(h.enabled, h.monthly_cap) for h in history] == [(False, 2), (True, 3)]
    assert {h.created_by_user_id for h in history} == {admin}


def test_a_saved_row_round_trips_every_number(world, templates, db_session) -> None:
    bind_tenant(db_session, alpha(world))
    wanted = policy(
        templates, monthly_cap=5, daily_cap=40, pending_cap=9, expiry_days=14, cooldown_days=10
    )
    repository.add_follow_up_policy(db_session, alpha(world), world.users["alpha.admin"].id, wanted)
    assert repository.current_follow_up_policy(db_session, alpha(world)) == wanted


def test_the_repository_refuses_numbers_outside_the_bounds_before_the_database(
    world, templates, db_session
) -> None:
    bind_tenant(db_session, alpha(world))
    with pytest.raises(ValueError, match="monthly_cap"):
        repository.add_follow_up_policy(
            db_session,
            alpha(world),
            world.users["alpha.admin"].id,
            policy(templates, monthly_cap=9),
        )
    assert repository.follow_up_policy_history(db_session, alpha(world)) == []


# --- the database is the second wall ---------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "rule"),
    [
        ({"monthly_cap": 0}, "monthly_cap_bounds"),
        ({"monthly_cap": 9}, "monthly_cap_bounds"),
        ({"daily_cap": 0}, "daily_cap_bounds"),
        ({"daily_cap": 101}, "daily_cap_bounds"),
        ({"pending_cap": 0}, "pending_cap_bounds"),
        ({"pending_cap": 21}, "pending_cap_bounds"),
        ({"expiry_days": 0}, "expiry_days_bounds"),
        ({"expiry_days": 31}, "expiry_days_bounds"),
        ({"cooldown_days": 0}, "cooldown_days_bounds"),
        ({"cooldown_days": 61}, "cooldown_days_bounds"),
        ({"enabled": True}, "enabled_has_template"),
    ],
)
def test_the_database_refuses_impossible_rows(world, db_session, values, rule) -> None:
    with pytest.raises(IntegrityError, match=rule), db_session.begin_nested():
        insert(db_session, world, **values)


def test_the_database_bounds_are_the_same_as_the_rules(world, templates, db_session) -> None:
    """Every edge the rules accept is accepted by the database, so the two cannot drift apart."""
    for name, (low, high) in rules.BOUNDS.items():
        for value in (low, high):
            with db_session.begin_nested():
                insert(db_session, world, **{name: value})


def test_switched_off_needs_no_template(world, db_session) -> None:
    insert(db_session, world, enabled=False)


def test_a_template_of_another_organisation_is_refused(world, templates, db_session) -> None:
    with pytest.raises(IntegrityError, match="template_id"), db_session.begin_nested():
        insert(db_session, world, enabled=True, template_id=templates["beta"])


def test_a_person_of_another_organisation_cannot_be_the_author(world, db_session) -> None:
    bind_tenant(db_session, alpha(world))
    with pytest.raises(IntegrityError, match="created_by_user_id"), db_session.begin_nested():
        insert(db_session, world, created_by_user_id=world.users["beta.admin"].id)


# --- insert-only ------------------------------------------------------------------------------


def test_a_saved_row_cannot_be_changed(world, templates, db_session) -> None:
    bind_tenant(db_session, alpha(world))
    row = repository.add_follow_up_policy(
        db_session, alpha(world), world.users["alpha.admin"].id, policy(templates)
    )
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            update(FollowUpPolicy).where(FollowUpPolicy.id == row.id).values(monthly_cap=1)
        )


def test_a_young_row_cannot_be_deleted(world, templates, db_session) -> None:
    bind_tenant(db_session, alpha(world))
    row = repository.add_follow_up_policy(
        db_session, alpha(world), world.users["alpha.admin"].id, policy(templates)
    )
    with pytest.raises(DBAPIError, match="365 days"), db_session.begin_nested():
        db_session.execute(delete(FollowUpPolicy).where(FollowUpPolicy.id == row.id))


def test_the_application_cannot_truncate_the_table(world, db_session) -> None:
    bind_tenant(db_session, alpha(world))
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(text("TRUNCATE follow_up_policies"))


# --- organisations stay apart ---------------------------------------------------------------


def test_another_organisation_sees_neither_the_rows_nor_the_settings(
    world, templates, db_session
) -> None:
    bind_tenant(db_session, alpha(world))
    repository.add_follow_up_policy(
        db_session, alpha(world), world.users["alpha.admin"].id, policy(templates)
    )
    bind_tenant(db_session, beta(world))
    assert db_session.scalars(select(FollowUpPolicy)).all() == []
    assert repository.current_follow_up_policy(db_session, beta(world)) == rules.Policy()
    # Asking for alpha's id while bound to beta still finds nothing (the database decides).
    assert repository.follow_up_policy_history(db_session, alpha(world)) == []


def test_a_row_cannot_be_written_for_another_organisation(world, templates, db_session) -> None:
    bind_tenant(db_session, alpha(world))
    with pytest.raises(DBAPIError), db_session.begin_nested():
        repository.add_follow_up_policy(
            db_session, beta(world), world.users["beta.admin"].id, policy(templates)
        )


def test_without_a_tenant_nothing_is_visible(world, templates, db_session) -> None:
    bind_tenant(db_session, alpha(world))
    repository.add_follow_up_policy(
        db_session, alpha(world), world.users["alpha.admin"].id, policy(templates)
    )
    clear_tenant(db_session)
    assert db_session.scalars(select(FollowUpPolicy)).all() == []
