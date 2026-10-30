# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The web check through the real API and the real worker (ADR 0019, steps WC2c and the
notification of WC4): who may ask, who may read, what the answers hold, and the notification
the person who asked gets when the evidence is stored.

People come from test_quotes_api.py: tenant alpha has admin, manager, agent1 (owns A1, C1),
agent2 (owns A2, C2), support, customers; tenant beta has admin and agent.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core import events
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.mail import MemoryMailer
from app.core.storage import MemoryFileStore
from app.main import create_app
from app.modules.notifications import service as notifications
from app.modules.notifications.models import Notification
from app.worker import WorkerServices, job_handlers, run_due_jobs
from tests.auth_helpers import TEST_ISSUER, TokenFactory
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import forget_request_user, session_factory_for
from tests.db.test_approvals import add_lead, alpha
from tests.db.test_quotes_api import Headers, World, auth, code_of, ok, world  # noqa: F401

CHECKS = "/api/v1/webcheck/checks"
EVIDENCE = "/api/v1/webcheck/evidence"
SOURCES = "/api/v1/webcheck/sources"
RERA = "DEMO/RERA/2026/001"


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"webcheck_demo": True}
    values.update(overrides)
    return Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
        **values,
    )


@pytest.fixture
def make_api(db_connection: Connection, token_factory: TokenFactory) -> Iterator[Any]:
    clients: list[TestClient] = []

    def build(**overrides: Any) -> TestClient:
        app = create_app(settings(**overrides), token_verifier=token_factory.verifier())
        app.state.session_factory = session_factory_for(db_connection)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def api(make_api: Any) -> TestClient:
    return make_api()  # type: ignore[no-any-return]


@pytest.fixture
def worker(db_connection: Connection) -> Any:
    factory = session_factory_for(db_connection)

    def run(config: Settings | None = None) -> int:
        config = config or settings()
        handlers = job_handlers(WorkerServices(config, MemoryFileStore(), MemoryMailer()))
        with factory() as fresh, fresh.begin():
            forget_request_user(fresh)  # like a real worker transaction
        return run_due_jobs(factory, handlers, config)

    return run


def ask(api: TestClient, auth: Headers, user: str, target_id: Any, **values: Any):
    body = {
        "target_type": "lead",
        "target_id": str(target_id),
        "source_key": "demo_rera",
        "query": RERA,
    } | values
    return api.post(CHECKS, json=body, headers=auth(user))


def evidence(api: TestClient, auth: Headers, user: str, target_id: Any, kind: str = "lead"):
    return api.get(
        EVIDENCE, params={"target_type": kind, "target_id": str(target_id)}, headers=auth(user)
    )


# --- asking -------------------------------------------------------------------------------------


def test_a_check_is_accepted_and_nothing_is_fetched_yet(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    body = ok(ask(api, auth, "alpha.agent1", lead.id), 202)
    assert uuid.UUID(body["request_id"]) and body["status"] == "checking"
    assert evidence(api, auth, "alpha.agent1", lead.id).json()["items"] == []


def test_nobody_can_ask_without_signing_in(api, world, db_session) -> None:
    lead = add_lead(db_session, world)
    body = {
        "target_type": "lead",
        "target_id": str(lead.id),
        "source_key": "demo_rera",
        "query": RERA,
    }
    assert api.post(CHECKS, json=body).status_code == 401
    assert (
        api.get(EVIDENCE, params={"target_type": "lead", "target_id": str(lead.id)}).status_code
        == 401
    )
    assert api.get(SOURCES).status_code == 401


def test_a_customer_may_not_ask(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    assert code_of(ask(api, auth, "alpha.customer", lead.id))[0] == 403


@pytest.mark.parametrize("user", ["alpha.agent2", "alpha.support", "beta.admin"])
def test_a_lead_the_person_may_not_read_is_not_found(api, auth, world, db_session, user) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    assert code_of(ask(api, auth, user, lead.id)) == (404, "record_not_found")


def test_a_made_up_record_is_not_found(api, auth, world) -> None:
    assert code_of(ask(api, auth, "alpha.agent1", uuid.uuid4())) == (404, "record_not_found")


def test_a_manager_may_check_any_lead_and_support_an_account(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    ok(ask(api, auth, "alpha.manager", lead.id), 202)
    ok(ask(api, auth, "alpha.support", world.ids["A1"], target_type="account"), 202)


def test_the_client_cannot_name_the_tenant_or_the_person(api, auth, world, db_session) -> None:
    """Only the fields of the form exist: anything else is refused, not ignored."""
    lead = add_lead(db_session, world)
    for extra in (
        {"tenant_id": str(uuid.uuid4())},
        {"requested_by_user_id": str(world.users["alpha.admin"].id)},
        {"address": "https://evil.example/x"},
        {"url": "https://evil.example/x"},
    ):
        assert ask(api, auth, "alpha.agent1", lead.id, **extra).status_code == 422


@pytest.mark.parametrize(
    "values",
    [
        {"query": ""},
        {"query": "https://evil.example/x"},
        {"source_key": "../etc"},
        {"source_key": "nope"},
        {"target_type": "opportunity"},
        {"target_type": ""},
    ],
)
def test_bad_input_is_refused_with_a_stable_code(api, auth, world, db_session, values) -> None:
    lead = add_lead(db_session, world)
    response = ask(api, auth, "alpha.agent1", lead.id, **values)
    assert response.status_code in (404, 422) and "evil.example" not in response.text


def test_a_query_in_the_wrong_shape_has_its_own_code_and_is_not_echoed(
    api, auth, world, db_session
) -> None:
    lead = add_lead(db_session, world)
    response = ask(api, auth, "alpha.agent1", lead.id, query="https://evil.example/x")
    assert code_of(response) == (422, "invalid_query") and "evil.example" not in response.text


def test_a_missing_field_is_refused(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    body = {"target_type": "lead", "target_id": str(lead.id), "query": RERA}
    assert api.post(CHECKS, json=body, headers=auth("alpha.agent1")).status_code == 422
    assert api.post(CHECKS, json={}, headers=auth("alpha.agent1")).status_code == 422


def test_a_source_that_is_off_is_refused(make_api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    off = make_api(webcheck_demo=False)
    assert code_of(ask(off, auth, "alpha.agent1", lead.id)) == (422, "source_unavailable")


def test_the_platform_switch_answers_503(make_api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    off = make_api(webcheck_disabled=True)
    assert code_of(ask(off, auth, "alpha.agent1", lead.id)) == (503, "webcheck_disabled")


def test_the_limit_answers_429(make_api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    small = make_api(webcheck_per_user_hour=1)
    ok(ask(small, auth, "alpha.agent1", lead.id), 202)
    assert code_of(ask(small, auth, "alpha.agent1", lead.id)) == (429, "webcheck_limit_reached")


# --- the sources the screen offers ------------------------------------------------------------


def test_the_sources_list_holds_what_a_form_needs(api, auth, world) -> None:
    items = ok(api.get(SOURCES, headers=auth("alpha.agent1")))["items"]
    assert {i["key"] for i in items} == {"demo_rera", "demo_company"}
    rera = next(i for i in items if i["key"] == "demo_rera")
    assert set(rera) == {"key", "title", "kind", "query_hint", "demo"}
    assert rera["kind"] == "rera" and rera["demo"] is True


def test_rera_sources_come_first_so_the_form_starts_with_the_common_case(
    api, auth, world
) -> None:
    items = ok(api.get(SOURCES, headers=auth("alpha.agent1")))["items"]
    assert [i["kind"] for i in items] == ["rera", "company"]
    assert items[0]["key"] == "demo_rera"


def test_no_source_is_listed_when_none_is_switched_on(make_api, auth, world) -> None:
    off = make_api(webcheck_demo=False)
    assert ok(off.get(SOURCES, headers=auth("alpha.agent1")))["items"] == []


def test_a_customer_gets_no_source_list(api, auth, world) -> None:
    assert api.get(SOURCES, headers=auth("alpha.customer")).status_code == 403


# --- reading the evidence ---------------------------------------------------------------------


def run_check(api, auth, worker, user, target_id, **values: Any) -> None:
    ok(ask(api, auth, user, target_id, **values), 202)
    assert worker() >= 1


def test_the_evidence_appears_once_the_worker_has_run(api, auth, world, db_session, worker) -> None:
    lead = add_lead(db_session, world)
    run_check(api, auth, worker, "alpha.agent1", lead.id)
    [item] = ok(evidence(api, auth, "alpha.agent1", lead.id))["items"]
    assert item["verdict"] == "found" and item["status"] == "active"
    assert item["registered_name"] == "Lakeview Residency" and item["valid_until"] == "2028-03-31"
    assert item["source_key"] == "demo_rera" and item["query"] == RERA
    assert item["requested_by_user_id"] == str(world.users["alpha.agent1"].id)
    assert item["error_code"] is None and item["cleaned"] == []
    assert "Lakeview Residency" in item["excerpt"] and item["final_url"].startswith("https://")


def test_the_evidence_does_not_carry_internal_columns(api, auth, world, db_session, worker) -> None:
    lead = add_lead(db_session, world)
    run_check(api, auth, worker, "alpha.agent1", lead.id)
    [item] = ok(evidence(api, auth, "alpha.agent1", lead.id))["items"]
    assert not {"tenant_id", "seq", "body_sha256", "target_id", "target_type"} & set(item)
    assert set(item) == {
        "id", "request_id", "source_key", "query", "requested_by_user_id", "verdict",
        "error_code", "http_status", "final_url", "registered_name", "status", "valid_until",
        "excerpt", "cleaned", "created_at",
    }  # fmt: skip


def test_a_poisoned_page_reaches_the_screen_clean(api, auth, world, db_session, worker) -> None:
    lead = add_lead(db_session, world)
    run_check(api, auth, worker, "alpha.agent1", lead.id, query="DEMO/RERA/2026/666")
    [item] = ok(evidence(api, auth, "alpha.agent1", lead.id))["items"]
    assert "evil.example" not in str(item) and "<img" not in str(item)
    assert "instruction_phrase" in item["cleaned"]


def test_a_manager_reads_the_evidence_of_another_persons_lead(
    api, auth, world, db_session, worker
) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    run_check(api, auth, worker, "alpha.agent1", lead.id)
    assert len(ok(evidence(api, auth, "alpha.manager", lead.id))["items"]) == 1


@pytest.mark.parametrize("user", ["alpha.agent2", "alpha.support", "beta.admin"])
def test_the_evidence_of_a_lead_nobody_may_read_is_not_found(
    api, auth, world, db_session, worker, user
) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    run_check(api, auth, worker, "alpha.agent1", lead.id)
    assert code_of(evidence(api, auth, user, lead.id)) == (404, "record_not_found")


def test_a_customer_cannot_read_evidence(api, auth, world, db_session) -> None:
    lead = add_lead(db_session, world)
    assert evidence(api, auth, "alpha.customer", lead.id).status_code == 403


def test_the_evidence_of_an_account(api, auth, world, worker) -> None:
    run_check(
        api, auth, worker, "alpha.agent1", world.ids["A1"],
        target_type="account", source_key="demo_company", query="Demo Builders Pvt Ltd",
    )  # fmt: skip
    [item] = ok(evidence(api, auth, "alpha.agent1", world.ids["A1"], "account"))["items"]
    assert item["verdict"] == "found" and item["source_key"] == "demo_company"
    assert code_of(evidence(api, auth, "alpha.agent1", world.ids["A2"], "account")) == (
        404,
        "record_not_found",
    )


def test_the_evidence_is_newest_first(api, auth, world, db_session, worker) -> None:
    lead = add_lead(db_session, world)
    run_check(api, auth, worker, "alpha.agent1", lead.id, query="DEMO/RERA/2026/001")
    run_check(api, auth, worker, "alpha.agent1", lead.id, query="DEMO/RERA/2026/002")
    items = ok(evidence(api, auth, "alpha.agent1", lead.id))["items"]
    assert [i["query"] for i in items] == ["DEMO/RERA/2026/002", "DEMO/RERA/2026/001"]


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"target_type": "lead"},
        {"target_id": "x"},
        {"target_type": "lead", "target_id": "not-a-uuid"},
        {"target_type": "contact", "target_id": str(uuid.uuid4())},
    ],
)
def test_the_evidence_query_is_checked(api, auth, world, params) -> None:
    assert api.get(EVIDENCE, params=params, headers=auth("alpha.agent1")).status_code in (404, 422)


# --- the notification -------------------------------------------------------------------------


def notifications_of(db_session: Session, world: World, user: str) -> list[Notification]:
    bind_tenant(db_session, alpha(world))
    return list(
        db_session.scalars(select(Notification).where(Notification.user_id == world.users[user].id))
    )


def test_the_event_and_its_notification_type_exist() -> None:
    assert "webcheck.completed" in events.EVENT_NAMES
    assert (
        "webcheck.completed" in notifications.TYPES and "webcheck.completed" in notifications.RULES
    )


def test_the_person_who_asked_is_told_when_the_check_is_done(
    api, auth, world, db_session, worker
) -> None:
    lead = add_lead(db_session, world)
    run_check(api, auth, worker, "alpha.agent1", lead.id)
    [note] = notifications_of(db_session, world, "alpha.agent1")
    assert note.type == "webcheck.completed" and note.link == f"/leads/{lead.id}"
    assert note.title.startswith("Web check finished for Asha Rao") and "found" in note.title


@pytest.mark.parametrize(
    ("query", "source", "words"),
    [
        ("DEMO/RERA/2026/000", "demo_rera", "not found"),
        ("DEMO/RERA/2026/999", "demo_rera", "could not be read with certainty"),
    ],
)
def test_the_notification_says_what_came_back(
    api, auth, world, db_session, worker, query, source, words
) -> None:
    lead = add_lead(db_session, world)
    run_check(api, auth, worker, "alpha.agent1", lead.id, query=query, source_key=source)
    [note] = notifications_of(db_session, world, "alpha.agent1")
    assert words in note.title


def test_a_check_that_could_not_be_made_is_reported_too(
    api, auth, world, db_session, worker
) -> None:
    lead = add_lead(db_session, world)
    ok(ask(api, auth, "alpha.agent1", lead.id), 202)
    # the source is switched off before the worker gets to the job: the evidence says "error"
    assert worker(settings(webcheck_demo=False)) >= 1
    [note] = notifications_of(db_session, world, "alpha.agent1")
    assert "could not be checked" in note.title


def test_nobody_else_is_told(api, auth, world, db_session, worker) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    run_check(api, auth, worker, "alpha.manager", lead.id)
    assert len(notifications_of(db_session, world, "alpha.manager")) == 1
    for other in ("alpha.agent1", "alpha.agent2", "alpha.admin", "alpha.support"):
        assert notifications_of(db_session, world, other) == []


def test_the_event_holds_ids_and_codes_only(api, auth, world, db_session, worker) -> None:
    from app.core.outbox import OutboxJob

    lead = add_lead(db_session, world)
    run_check(api, auth, worker, "alpha.agent1", lead.id, query="DEMO/RERA/2026/666")
    bind_tenant(db_session, alpha(world))
    [job] = db_session.scalars(
        select(OutboxJob).where(OutboxJob.kind == "event.webcheck.completed")
    ).all()
    data = job.payload["data"]
    assert set(data) == {"target_type", "target_id", "verdict", "requested_by_user_id"}
    assert "evil.example" not in str(job.payload) and "Villa" not in str(job.payload)


def test_a_person_who_can_no_longer_read_the_record_is_not_told(
    api, auth, world, db_session, worker
) -> None:
    """The lead was reassigned between asking and the result: the old owner hears nothing."""
    lead = add_lead(db_session, world, "alpha.agent1")
    ok(ask(api, auth, "alpha.agent1", lead.id), 202)
    from sqlalchemy import update

    from app.modules.leads.models import Lead
    from tests.db.conftest import setup_lead_context

    setup_lead_context(db_session, alpha(world), scope="all")
    db_session.execute(
        update(Lead).where(Lead.id == lead.id).values(owner_id=world.users["alpha.agent2"].id)
    )
    db_session.flush()
    assert worker() >= 1
    assert notifications_of(db_session, world, "alpha.agent1") == []


def test_a_person_who_can_no_longer_read_the_account_is_not_told(
    api, auth, world, db_session, worker
) -> None:
    """The same rule for an account: it changed hands between asking and the result."""
    from sqlalchemy import update

    from app.modules.accounts.models import Account

    ok(
        ask(
            api, auth, "alpha.agent1", world.ids["A1"],
            target_type="account", source_key="demo_company", query="Demo Builders Pvt Ltd",
        ),
        202,
    )  # fmt: skip
    bind_tenant(db_session, alpha(world))
    db_session.execute(
        update(Account)
        .where(Account.id == world.ids["A1"])
        .values(owner_id=world.users["alpha.agent2"].id)
    )
    db_session.flush()
    assert worker() >= 1
    assert notifications_of(db_session, world, "alpha.agent1") == []
    # ... and the event was handled cleanly, not by failing and being retried
    from app.core.outbox import OutboxJob

    jobs = db_session.scalars(
        select(OutboxJob).where(OutboxJob.kind == "event.webcheck.completed")
    ).all()
    assert [job.status for job in jobs] == ["done"]


def test_the_person_who_can_read_the_account_is_told_with_its_name(
    api, auth, world, db_session, worker
) -> None:
    run_check(
        api, auth, worker, "alpha.agent1", world.ids["A1"],
        target_type="account", source_key="demo_company", query="Demo Builders Pvt Ltd",
    )  # fmt: skip
    [note] = notifications_of(db_session, world, "alpha.agent1")
    assert note.link == f"/accounts/{world.ids['A1']}" and note.title.endswith(": found")
