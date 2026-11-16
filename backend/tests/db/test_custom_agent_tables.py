# ruff: noqa: F811, S608 - pytest fixtures are imported and used as parameters; SQL here is constants
"""The tables of the no-code agent builder (ADR 0034, AB1) through the real database: forced
row-level security, the two menus enforced by the database itself, and insert-only versions."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.modules.custom_agents import rules
from app.modules.custom_agents.models import CustomAgent, CustomAgentVersion
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name


@pytest.fixture(autouse=True)
def end_the_owner_transaction(committed_world: Session) -> Iterator[None]:
    """These tests leave rows uncommitted; end the owner's transaction before the fixtures clean
    the tables, or the cleanup waits for its locks forever."""
    yield
    committed_world.rollback()


def make_agent(session: Session, world: World, who: str = "alpha.admin") -> CustomAgent:
    person = world.users[who]
    bind_tenant(session, person.tenant_id)
    agent = CustomAgent(
        tenant_id=person.tenant_id, name="Quiet lead helper", created_by_user_id=person.id
    )
    session.add(agent)
    session.flush()
    return agent


def version_of(agent: CustomAgent, world: World, **changes: Any) -> CustomAgentVersion:
    values: dict[str, Any] = {
        "tenant_id": agent.tenant_id,
        "custom_agent_id": agent.id,
        "version_no": 1,
        "purpose": "Suggest a follow-up task.",
        "instruction": "Read the lead. Suggest a follow-up task if it went quiet.",
        "read_sets": ["lead", "lead_activity"],
        "suggestion_kinds": ["activity.create_task"],
        "cleaned": [],
        "created_by_user_id": agent.created_by_user_id,
    }
    return CustomAgentVersion(**{**values, **changes})


def add_version(session: Session, agent: CustomAgent, world: World, **changes: Any) -> Any:
    row = version_of(agent, world, **changes)
    session.add(row)
    session.flush()
    return row


def test_an_agent_and_its_first_version_are_stored(committed_world: Session, world: World) -> None:
    session = committed_world
    agent = make_agent(session, world)
    row = add_version(session, agent, world)
    assert rules.is_custom_key(agent.agent_key)
    assert (agent.current_version, agent.version, agent.archived_at) == (1, 1, None)
    assert row.seq >= 1 and row.read_sets == ["lead", "lead_activity"]


def test_each_agent_gets_its_own_key(committed_world: Session, world: World) -> None:
    first, second = make_agent(committed_world, world), make_agent(committed_world, world)
    assert first.agent_key != second.agent_key


@pytest.mark.parametrize(
    "changes",
    [
        {"read_sets": []},
        {"read_sets": ["tickets"]},
        {"read_sets": ["lead", "account", "deal", "deal_quotes"]},
        {"suggestion_kinds": []},
        {"suggestion_kinds": ["lead.convert"]},
        {"suggestion_kinds": ["agent_action.approve"]},
        {"suggestion_kinds": ["lead.set_status", "activity.create_task", "lead.assign"]},
        {"suggestion_kinds": ["lead.assign"]},
        {"purpose": ""},
        {"purpose": "p" * (rules.PURPOSE_MAX + 1)},
        {"instruction": ""},
        {"instruction": "i" * (rules.INSTRUCTION_MAX + 1)},
        {"version_no": 0},
        {"cleaned": {"link": True}},
    ],
    ids=[
        "no-read-set",
        "read-set-off-menu",
        "four-read-sets",
        "no-suggestion",
        "convert-not-allowed",
        "approve-not-allowed",
        "three-suggestions",
        "assign-not-allowed-in-v1",
        "empty-purpose",
        "long-purpose",
        "empty-instruction",
        "long-instruction",
        "version-zero",
        "cleaned-not-a-list",
    ],
)
def test_the_database_itself_refuses_a_version_outside_the_menus_and_limits(
    committed_world: Session, world: World, changes: dict[str, Any]
) -> None:
    session = committed_world
    agent = make_agent(session, world)
    with pytest.raises((IntegrityError, DBAPIError)), session.begin_nested():
        add_version(session, agent, world, **changes)


def test_every_item_on_the_menus_is_accepted_by_the_database(
    committed_world: Session, world: World
) -> None:
    session = committed_world
    agent = make_agent(session, world)
    for number, (read_set, kind) in enumerate(
        zip(rules.READ_SETS, rules.SUGGESTION_KINDS * 2, strict=False), start=1
    ):
        add_version(
            session,
            agent,
            world,
            version_no=number,
            read_sets=[read_set],
            suggestion_kinds=[kind],
        )


def test_a_version_number_is_used_once_per_agent(committed_world: Session, world: World) -> None:
    session = committed_world
    agent = make_agent(session, world)
    add_version(session, agent, world)
    with pytest.raises(IntegrityError), session.begin_nested():
        add_version(session, agent, world)
    add_version(session, agent, world, version_no=2)


def test_the_agent_key_must_look_like_a_custom_key(committed_world: Session, world: World) -> None:
    person = world.users["alpha.admin"]
    bind_tenant(committed_world, person.tenant_id)
    for bad in ("staff_assistant", "custom_XYZ", "custom_0123456789ab", "custom_abcdefghijkl1", ""):
        with pytest.raises(IntegrityError), committed_world.begin_nested():
            committed_world.add(
                CustomAgent(
                    tenant_id=person.tenant_id,
                    agent_key=bad,
                    name="x agent",
                    created_by_user_id=person.id,
                )
            )
            committed_world.flush()


def test_a_name_must_be_one_to_sixty_characters(committed_world: Session, world: World) -> None:
    person = world.users["alpha.admin"]
    bind_tenant(committed_world, person.tenant_id)
    for bad in ("", "n" * (rules.NAME_MAX + 1)):
        with pytest.raises((IntegrityError, DBAPIError)), committed_world.begin_nested():
            committed_world.add(
                CustomAgent(tenant_id=person.tenant_id, name=bad, created_by_user_id=person.id)
            )
            committed_world.flush()


def test_versions_can_never_be_changed_or_deleted_early(
    committed_world: Session, world: World
) -> None:
    session = committed_world
    agent = make_agent(session, world)
    row = add_version(session, agent, world)
    for statement in (
        "UPDATE custom_agent_versions SET instruction = 'changed' WHERE id = :i",
        "UPDATE custom_agent_versions SET read_sets = ARRAY['deal'] WHERE id = :i",
        "UPDATE custom_agent_versions SET suggestion_kinds = ARRAY['lead.assign'] WHERE id = :i",
    ):
        with pytest.raises(DBAPIError, match="cannot be changed"), session.begin_nested():
            session.execute(text(statement), {"i": row.id})
    with pytest.raises(DBAPIError, match="only after 365 days"), session.begin_nested():
        session.execute(text("DELETE FROM custom_agent_versions WHERE id = :i"), {"i": row.id})


def test_a_version_cannot_point_at_another_organisations_agent(
    committed_world: Session, world: World
) -> None:
    session = committed_world
    agent = make_agent(session, world, "alpha.admin")
    foreign = world.users["beta.admin"]
    bind_tenant(session, foreign.tenant_id)
    with pytest.raises((IntegrityError, DBAPIError)), session.begin_nested():
        add_version(
            session,
            agent,
            world,
            tenant_id=foreign.tenant_id,
            created_by_user_id=foreign.id,
        )


def test_an_agent_cannot_be_deleted_while_it_has_versions(
    committed_world: Session, world: World
) -> None:
    session = committed_world
    agent = make_agent(session, world)
    add_version(session, agent, world)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text("DELETE FROM custom_agents WHERE id = :i"), {"i": agent.id})


def test_an_agent_can_be_renamed_and_archived_but_keeps_its_key(
    committed_world: Session, world: World
) -> None:
    session = committed_world
    agent = make_agent(session, world)
    key = agent.agent_key
    agent.name = "Renamed helper"
    agent.current_version = 2
    session.flush()
    session.refresh(agent)
    assert (agent.name, agent.current_version, agent.version, agent.agent_key) == (
        "Renamed helper",
        2,
        2,
        key,
    )


def test_two_organisations_never_see_each_others_agents(
    committed_world: Session, world: World, db_session: Session
) -> None:
    agent = make_agent(committed_world, world, "alpha.admin")
    add_version(committed_world, agent, world)
    committed_world.commit()
    alpha = world.users["alpha.admin"].tenant_id
    beta = world.users["beta.admin"].tenant_id
    # db_session is the restricted application role, like the API: row-level security applies.
    bind_tenant(db_session, beta)
    assert db_session.scalars(select(CustomAgent)).all() == []
    assert db_session.scalars(select(CustomAgentVersion)).all() == []
    bind_tenant(db_session, alpha)
    assert [a.id for a in db_session.scalars(select(CustomAgent))] == [agent.id]
    assert len(db_session.scalars(select(CustomAgentVersion)).all()) == 1
    # Writing a row for another organisation is refused too.
    bind_tenant(db_session, alpha)
    with pytest.raises((IntegrityError, DBAPIError)), db_session.begin_nested():
        db_session.add(
            CustomAgent(
                tenant_id=beta, name="not mine", created_by_user_id=world.users["beta.admin"].id
            )
        )
        db_session.flush()


def test_the_application_role_cannot_update_or_truncate_versions(db_session: Session) -> None:
    grants = {
        row[0]
        for row in db_session.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE table_name = 'custom_agent_versions' AND grantee = 'crm_app'"
            )
        )
    }
    assert "UPDATE" not in grants and "TRUNCATE" not in grants
    assert {"SELECT", "INSERT"} <= grants
