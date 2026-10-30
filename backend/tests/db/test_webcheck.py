# ruff: noqa: F811, S608 - fixtures are used by name; the one f-string SQL holds fixed test values
"""The web check (ADR 0019, step WC2b) through the service, the worker job and the real database.

A check is REQUESTED by a person (permission, record-level read, limits, a valid query - and a
job is queued with ids and keys only), then RUN by the worker (the real fetcher and parser, with
only the network replaced by the demo registry), which stores insert-only evidence.
People come from test_quotes_api.py: tenant alpha has admin, manager, agent1 (owns A1, C1),
agent2 (owns A2, C2), support, customers; tenant beta has admin and agent.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.errors import DomainError, ForbiddenError, NotFoundError
from app.core.mail import MemoryMailer
from app.core.outbox import Job, OutboxJob
from app.core.storage import MemoryFileStore
from app.modules.webcheck import service
from app.modules.webcheck.fake import DEMO_HOST, DemoRegistry
from app.modules.webcheck.models import WebEvidence
from app.worker import WorkerServices, job_handlers, run_due_jobs, run_schedules
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import forget_request_user, session_factory_for
from tests.db.test_approvals import ROLES, add_lead, alpha, principal_for
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

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


class Acting:
    def __init__(self, session: Session, world: World) -> None:
        self.session, self.world = session, world
        self.demo = DemoRegistry()

    def who(self, name: str):
        from tests.db.conftest import bind_principal

        principal = principal_for(self.world.users[name], ROLES[name])
        bind_principal(self.session, principal)
        return principal

    def request(self, name: str, target_id: uuid.UUID, query: str = RERA, **values: Any):
        config = values.pop("config", settings())
        values.setdefault("target_type", "lead")
        values.setdefault("source_key", "demo_rera")
        return service.request_check(
            self.session,
            self.who(name),
            target_id=target_id,
            query=query,
            settings=config,
            **values,
        )

    def jobs(self) -> list[OutboxJob]:
        bind_tenant(self.session, alpha(self.world))
        return list(
            self.session.scalars(
                select(OutboxJob)
                .where(OutboxJob.kind == service.CHECK_JOB)
                .order_by(OutboxJob.created_at)
            )
        )

    def run(self, job: OutboxJob, *, attempt: int = 1, config: Settings | None = None) -> None:
        """What the worker does with one queued job, with the demo registry as the network."""
        bind_tenant(self.session, job.tenant_id)
        service.run_check(
            self.session,
            Job(job.id, job.tenant_id, job.kind, job.payload, attempt),
            settings=config or settings(),
            resolver=self.demo.resolver,
            transport=self.demo.transport,
        )
        self.session.flush()

    def evidence(self) -> list[WebEvidence]:
        bind_tenant(self.session, alpha(self.world))
        return list(self.session.scalars(select(WebEvidence).order_by(WebEvidence.created_at)))


@pytest.fixture
def acting(db_session: Session, world: World) -> Acting:
    return Acting(db_session, world)


# --- requesting a check ---------------------------------------------------------------------


def test_a_check_is_queued_with_ids_and_keys_only(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    asked = acting.request("alpha.agent1", lead.id)
    [job] = acting.jobs()
    assert job.payload == {
        "request_id": str(asked.request_id),
        "target_type": "lead",
        "target_id": str(lead.id),
        "source_key": "demo_rera",
        "query": RERA,
        "requested_by_user_id": str(world.users["alpha.agent1"].id),
    }
    assert acting.evidence() == []  # nothing is fetched while the person waits


def test_the_request_is_audited_with_source_and_query(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    asked = acting.request("alpha.agent1", lead.id)
    [row] = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "webcheck.requested")
    ).all()
    assert row.entity_id == asked.request_id
    assert row.changes == {
        "target_type": "lead",
        "target_id": str(lead.id),
        "source_key": "demo_rera",
        "query": RERA,
    }


def test_an_account_can_be_checked_too(acting, db_session, world) -> None:
    acting.request("alpha.agent1", world.ids["A1"], target_type="account")
    [job] = acting.jobs()
    assert job.payload["target_type"] == "account"


def test_a_company_check_uses_the_company_source(acting, db_session, world) -> None:
    acting.request(
        "alpha.agent1",
        world.ids["A1"],
        "Demo Builders Pvt Ltd",
        target_type="account",
        source_key="demo_company",
    )
    [job] = acting.jobs()
    assert job.payload["source_key"] == "demo_company"


# record-level access, tenant isolation, ID tampering


def test_a_person_cannot_check_a_record_they_may_not_read(acting, db_session, world) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    with pytest.raises(NotFoundError):
        acting.request("alpha.agent2", lead.id)  # another agent's lead: same answer as "no such"
    assert acting.jobs() == []


def test_a_manager_may_check_any_lead_of_the_organisation(acting, db_session, world) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    acting.request("alpha.manager", lead.id)
    assert len(acting.jobs()) == 1


def test_another_organisations_record_is_not_found(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(NotFoundError):
        acting.request("beta.admin", lead.id)


def test_a_made_up_record_is_not_found(acting, db_session, world) -> None:
    with pytest.raises(NotFoundError):
        acting.request("alpha.agent1", uuid.uuid4())
    with pytest.raises(NotFoundError):
        acting.request("alpha.agent1", uuid.uuid4(), target_type="account")


def test_an_account_the_person_may_not_read_is_not_found(acting, db_session, world) -> None:
    with pytest.raises(NotFoundError):
        acting.request("alpha.agent1", world.ids["A2"], target_type="account")  # agent2's


def test_an_unknown_kind_of_record_is_refused(acting, db_session, world) -> None:
    with pytest.raises(DomainError):
        acting.request("alpha.agent1", world.ids["A1"], target_type="opportunity")


def test_a_person_without_the_permission_is_refused(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(ForbiddenError):
        acting.request("alpha.customer", lead.id)  # a portal customer has no web check
    assert acting.jobs() == []


def test_support_may_check_an_account_but_not_a_lead(acting, db_session, world) -> None:
    """Support agents read all accounts but no leads: the record rule decides, as for anyone."""
    lead = add_lead(db_session, world)
    with pytest.raises(NotFoundError):
        acting.request("alpha.support", lead.id)
    acting.request("alpha.support", world.ids["A1"], target_type="account")
    assert len(acting.jobs()) == 1


# the query and the source


@pytest.mark.parametrize("query", ["", "https://evil.example/x", "DEMO RERA", "x" * 80])
def test_a_query_in_the_wrong_shape_queues_nothing(acting, db_session, world, query) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(DomainError) as refused:
        acting.request("alpha.agent1", lead.id, query)
    assert refused.value.code == "invalid_query" and "evil.example" not in refused.value.detail
    assert acting.jobs() == []


def test_a_source_that_is_not_enabled_is_refused(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    off = settings(webcheck_demo=False)
    with pytest.raises(DomainError) as refused:
        acting.request("alpha.agent1", lead.id, config=off)
    assert refused.value.code == "source_unavailable" and acting.jobs() == []


def test_a_source_that_does_not_exist_is_refused(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(DomainError) as refused:
        acting.request("alpha.agent1", lead.id, source_key="../etc")
    assert refused.value.code == "source_unavailable"


def test_a_source_of_the_wrong_kind_for_the_query_is_refused(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(DomainError):
        acting.request(
            "alpha.agent1", lead.id, "Demo Builders Pvt Ltd"
        )  # a name for the RERA source


def test_a_configured_source_is_enabled_without_the_demo_switch(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    acting.request(
        "alpha.agent1", lead.id, config=settings(webcheck_demo=False, webcheck_sources="demo_rera")
    )
    assert len(acting.jobs()) == 1


def test_the_platform_switch_stops_every_request(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    with pytest.raises(DomainError) as refused:
        acting.request("alpha.agent1", lead.id, config=settings(webcheck_disabled=True))
    assert refused.value.code == "webcheck_disabled" and refused.value.status_code == 503


# limits


def test_one_person_has_an_hourly_limit(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    config = settings(webcheck_per_user_hour=2)
    acting.request("alpha.agent1", lead.id, config=config)
    acting.request("alpha.agent1", lead.id, config=config)
    with pytest.raises(DomainError) as refused:
        acting.request("alpha.agent1", lead.id, config=config)
    assert refused.value.code == "webcheck_limit_reached" and refused.value.status_code == 429
    assert len(acting.jobs()) == 2


def test_the_hourly_limit_is_per_person(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    config = settings(webcheck_per_user_hour=1)
    acting.request("alpha.agent1", lead.id, config=config)
    acting.request("alpha.manager", lead.id, config=config)  # another person: their own count
    assert len(acting.jobs()) == 2


def test_old_requests_do_not_count_against_the_hour(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    config = settings(webcheck_per_user_hour=1)
    acting.request("alpha.agent1", lead.id, config=config)
    db_session.execute(
        text("update outbox_jobs set created_at = now() - interval '2 hours' where kind = :k"),
        {"k": service.CHECK_JOB},
    )
    acting.request("alpha.agent1", lead.id, config=config)
    assert len(acting.jobs()) == 2


def test_the_organisation_has_a_daily_limit(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    config = settings(webcheck_per_tenant_day=2, webcheck_per_user_hour=100)
    acting.request("alpha.agent1", lead.id, config=config)
    acting.request("alpha.manager", lead.id, config=config)
    with pytest.raises(DomainError) as refused:
        acting.request("alpha.admin", lead.id, config=config)
    assert refused.value.code == "webcheck_limit_reached"


# --- running a check ------------------------------------------------------------------------


def run_one(
    acting: Acting, db_session: Session, world: World, query: str = RERA, **values: Any
) -> WebEvidence:
    lead = add_lead(db_session, world)
    acting.request("alpha.agent1", lead.id, query, **values)
    [job] = acting.jobs()
    acting.run(job)
    [row] = acting.evidence()
    return row


def test_a_found_registration_becomes_evidence(acting, db_session, world) -> None:
    row = run_one(acting, db_session, world)
    assert (row.verdict, row.status, row.registered_name) == (
        "found",
        "active",
        "Lakeview Residency",
    )
    assert row.valid_until is not None and row.valid_until.isoformat() == "2028-03-31"
    assert (row.source_key, row.query, row.target_type) == ("demo_rera", RERA, "lead")
    assert row.requested_by_user_id == world.users["alpha.agent1"].id
    assert row.http_status == 200 and row.error_code is None
    assert row.final_url == f"https://{DEMO_HOST}/rera/search?number=DEMO%2FRERA%2F2026%2F001"
    assert "Lakeview Residency" in row.excerpt


def test_the_evidence_keeps_a_hash_of_what_was_fetched(acting, db_session, world) -> None:
    row = run_one(acting, db_session, world)
    page = DemoRegistry().transport
    from app.core.webfetch import PinnedRequest

    body = page(
        PinnedRequest(
            "93.184.216.34",
            DEMO_HOST,
            "/rera/search?number=DEMO%2FRERA%2F2026%2F001",
            {},
            5.0,
            10**6,
        )
    ).body
    assert row.body_sha256 == hashlib.sha256(body).hexdigest()


def test_the_evidence_does_not_store_the_address_we_connected_to(acting, db_session, world) -> None:
    row = run_one(acting, db_session, world)
    assert "93.184.216.34" not in json.dumps(
        {c.name: str(getattr(row, c.name)) for c in WebEvidence.__table__.columns}
    )


@pytest.mark.parametrize(
    ("query", "source", "verdict"),
    [
        ("DEMO/RERA/2026/000", "demo_rera", "not_found"),
        ("DEMO/RERA/2026/777", "demo_rera", "unclear"),
        ("DEMO/RERA/2026/999", "demo_rera", "unclear"),
        ("Ghost Constructions", "demo_company", "not_found"),
        ("Sunrise Homes", "demo_company", "unclear"),
        ("Demo Builders Pvt Ltd", "demo_company", "found"),
    ],
)
def test_each_kind_of_answer_is_stored(acting, db_session, world, query, source, verdict) -> None:
    row = run_one(acting, db_session, world, query, source_key=source)
    assert row.verdict == verdict


def test_a_poisoned_page_is_stored_cleaned(acting, db_session, world) -> None:
    row = run_one(acting, db_session, world, "DEMO/RERA/2026/666")
    assert row.verdict == "found"
    stored = (row.registered_name or "") + row.excerpt
    assert "evil.example" not in stored and "<img" not in stored and "​" not in stored
    assert "instruction_phrase" in row.cleaned and "link" in row.cleaned


def test_the_job_is_safe_to_run_twice(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    acting.request("alpha.agent1", lead.id)
    [job] = acting.jobs()
    acting.run(job)
    acting.run(job)
    assert len(acting.evidence()) == 1


def test_a_source_switched_off_after_the_request_stores_an_error(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    acting.request("alpha.agent1", lead.id)
    [job] = acting.jobs()
    acting.run(job, config=settings(webcheck_demo=False))
    [row] = acting.evidence()
    assert (row.verdict, row.error_code) == ("error", "source_unavailable")
    assert row.http_status is None and row.body_sha256 is None


def test_a_site_that_refuses_is_stored_as_an_error(acting, db_session, world) -> None:
    acting.demo.transport = lambda request: _refuse_robots(request)
    lead = add_lead(db_session, world)
    acting.request("alpha.agent1", lead.id)
    [job] = acting.jobs()
    acting.run(job)
    [row] = acting.evidence()
    assert (row.verdict, row.error_code) == ("error", "robots_disallowed")


def _refuse_robots(request: Any):
    from app.core.webfetch import TransportResponse

    if request.target == "/robots.txt":
        return TransportResponse(
            200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /\n", False
        )
    raise AssertionError("the page must not be requested")


def test_a_temporary_failure_is_retried_before_it_is_stored(acting, db_session, world) -> None:
    def broken(request: Any):
        raise TimeoutError

    acting.demo.transport = broken
    lead = add_lead(db_session, world)
    acting.request("alpha.agent1", lead.id)
    [job] = acting.jobs()
    with pytest.raises(service.TemporaryFailure):
        acting.run(job, attempt=1)
    assert acting.evidence() == []
    acting.run(job, attempt=service.MAX_ATTEMPTS)  # the last try is stored
    [row] = acting.evidence()
    assert (row.verdict, row.error_code) == ("error", "timeout")


def test_a_job_with_a_broken_payload_is_a_permanent_failure(acting, db_session, world) -> None:
    from app.core.outbox import PermanentJobError

    bind_tenant(db_session, alpha(world))
    with pytest.raises(PermanentJobError):
        service.run_check(
            db_session,
            Job(uuid.uuid4(), alpha(world), service.CHECK_JOB, {"query": "x"}, 1),
            settings=settings(),
            resolver=acting.demo.resolver,
            transport=acting.demo.transport,
        )


# --- reading evidence -----------------------------------------------------------------------


def test_evidence_of_a_lead_is_listed_for_those_who_may_read_it(acting, db_session, world) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    acting.request("alpha.agent1", lead.id)
    acting.run(acting.jobs()[0])
    own = service.list_evidence(db_session, acting.who("alpha.agent1"), "lead", lead.id)
    boss = service.list_evidence(db_session, acting.who("alpha.manager"), "lead", lead.id)
    assert [e.verdict for e in own] == ["found"] and [e.id for e in boss] == [e.id for e in own]


def test_evidence_of_someone_elses_lead_is_not_found(acting, db_session, world) -> None:
    lead = add_lead(db_session, world, "alpha.agent1")
    acting.request("alpha.agent1", lead.id)
    acting.run(acting.jobs()[0])
    with pytest.raises(NotFoundError):
        service.list_evidence(db_session, acting.who("alpha.agent2"), "lead", lead.id)
    with pytest.raises(NotFoundError):
        service.list_evidence(db_session, acting.who("beta.admin"), "lead", lead.id)
    with pytest.raises(NotFoundError):
        service.list_evidence(db_session, acting.who("alpha.support"), "lead", lead.id)
    with pytest.raises(ForbiddenError):
        service.list_evidence(db_session, acting.who("alpha.customer"), "lead", lead.id)


def test_evidence_is_listed_newest_first(acting, db_session, world) -> None:
    lead = add_lead(db_session, world)
    for number in ("DEMO/RERA/2026/001", "DEMO/RERA/2026/002"):
        acting.request("alpha.agent1", lead.id, number)
    for job in acting.jobs():
        acting.run(job)
    rows = service.list_evidence(db_session, acting.who("alpha.agent1"), "lead", lead.id)
    assert [r.query for r in rows] == ["DEMO/RERA/2026/002", "DEMO/RERA/2026/001"]


# --- the table itself -----------------------------------------------------------------------


def stored_row(acting, db_session, world) -> WebEvidence:
    return run_one(acting, db_session, world)


def test_evidence_cannot_be_changed_by_the_application(acting, db_session, world) -> None:
    row = stored_row(acting, db_session, world)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("update web_evidence set verdict = 'not_found' where id = :i"), {"i": row.id}
            )


def test_fresh_evidence_cannot_be_deleted(acting, db_session, world) -> None:
    row = stored_row(acting, db_session, world)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("delete from web_evidence where id = :i"), {"i": row.id})


def test_evidence_of_another_organisation_is_invisible(acting, db_session, world) -> None:
    stored_row(acting, db_session, world)
    bind_tenant(db_session, world.users["beta.admin"].tenant_id)
    assert db_session.scalars(select(WebEvidence)).all() == []


IMPOSSIBLE = [
    {"verdict": "'maybe'"},
    {"target_type": "'contact'"},
    {"excerpt": "repeat('x', 5000)"},
    {"verdict": "'error'", "error_code": "null"},  # an error says which
    {"verdict": "'found'", "error_code": "'timeout'"},  # only an error has an error code
    {"body_sha256": "'abc'"},  # a hash is 64 characters
    {"source_key": "'../etc'"},
]


@pytest.mark.parametrize("bad", IMPOSSIBLE, ids=lambda case: "+".join(case))
def test_the_database_refuses_impossible_rows(acting, db_session, world, bad) -> None:
    row = stored_row(acting, db_session, world)
    fields = {
        "target_type": "'lead'",
        "source_key": "'demo_rera'",
        "verdict": "'found'",
        "error_code": "null",
        "excerpt": "'ok'",
        "body_sha256": "null",
    } | bad
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "insert into web_evidence (tenant_id, request_id, target_type, target_id, "
                    "source_key, query, requested_by_user_id, verdict, error_code, excerpt, "
                    "body_sha256, cleaned) values (:t, :r, "
                    f"{fields['target_type']}, :g, {fields['source_key']}, 'q', :u, "
                    f"{fields['verdict']}, {fields['error_code']}, {fields['excerpt']}, "
                    f"{fields['body_sha256']}, '[]')"
                ),
                {
                    "t": row.tenant_id,
                    "r": uuid.uuid4(),
                    "g": row.target_id,
                    "u": row.requested_by_user_id,
                },
            )


def test_a_good_row_of_the_same_shape_is_accepted(acting, db_session, world) -> None:
    """The refusals above are about the bad values, not about the way the test inserts."""
    row = stored_row(acting, db_session, world)
    db_session.execute(
        text(
            "insert into web_evidence (tenant_id, request_id, target_type, target_id, source_key, "
            "query, requested_by_user_id, verdict, excerpt, cleaned) values "
            "(:t, :r, 'lead', :g, 'demo_rera', 'q', :u, 'found', 'ok', '[]')"
        ),
        {"t": row.tenant_id, "r": uuid.uuid4(), "g": row.target_id, "u": row.requested_by_user_id},
    )
    assert len(acting.evidence()) == 2


# --- retention ------------------------------------------------------------------------------


def insert_old(db_session: Session, row: WebEvidence, months: int) -> uuid.UUID:
    """An old row: inserting is allowed, changing is not, so age is set when it is created."""
    old_id = uuid.uuid4()
    db_session.execute(
        text(
            "insert into web_evidence (id, tenant_id, request_id, target_type, target_id, "
            "source_key, query, requested_by_user_id, verdict, excerpt, cleaned, created_at) "
            "values (:i, :t, :r, 'lead', :g, 'demo_rera', 'old', :u, 'found', 'ok', '[]', "
            "now() - make_interval(months => :m))"
        ),
        {
            "i": old_id,
            "t": row.tenant_id,
            "r": uuid.uuid4(),
            "g": row.target_id,
            "u": row.requested_by_user_id,
            "m": months,
        },
    )
    return old_id


def test_old_evidence_is_deleted_and_new_evidence_is_kept(acting, db_session, world) -> None:
    fresh = stored_row(acting, db_session, world)
    old_id = insert_old(db_session, fresh, 13)
    removed = service.delete_expired(db_session, datetime.now(UTC), tenant_id=alpha(world))
    assert removed == 1
    assert [e.id for e in acting.evidence()] == [fresh.id] and old_id != fresh.id


def test_evidence_just_inside_the_retention_is_kept(acting, db_session, world) -> None:
    fresh = stored_row(acting, db_session, world)
    insert_old(db_session, fresh, 11)
    assert service.delete_expired(db_session, datetime.now(UTC), tenant_id=alpha(world)) == 0


def test_the_database_itself_refuses_to_delete_young_evidence(acting, db_session, world) -> None:
    """Even a delete that skips the service: only rows older than the retention may go."""
    fresh = stored_row(acting, db_session, world)
    insert_old(db_session, fresh, 13)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("delete from web_evidence"))
    with db_session.begin_nested():
        db_session.execute(
            text("delete from web_evidence where created_at < now() - interval '1 year'")
        )
    assert [e.id for e in acting.evidence()] == [fresh.id]


def test_the_retention_period_is_twelve_months() -> None:
    assert service.RETENTION == timedelta(days=365)


# --- the real worker ------------------------------------------------------------------------


@pytest.fixture
def worker(db_connection: Connection):
    config = settings()
    factory = session_factory_for(db_connection)
    handlers = job_handlers(WorkerServices(config, MemoryFileStore(), MemoryMailer()))

    def run_jobs() -> int:
        with factory() as fresh, fresh.begin():
            forget_request_user(fresh)  # like a real worker transaction
        return run_due_jobs(factory, handlers, config)

    def run_sweeps() -> int:
        return run_schedules(factory, config)

    return run_jobs, run_sweeps


def test_the_worker_runs_a_queued_check_and_stores_the_evidence(
    acting, db_session, world, worker
) -> None:
    run_jobs, _ = worker
    lead = add_lead(db_session, world)
    acting.request("alpha.agent1", lead.id)
    db_session.flush()  # like the request's commit: the job is written before the worker runs
    assert run_jobs() >= 1
    [row] = acting.evidence()
    assert (row.verdict, row.registered_name) == (
        "found",
        "Lakeview Residency",
    )  # the demo registry


def test_the_workers_schedule_deletes_old_evidence_only(acting, db_session, world, worker) -> None:
    _, run_sweeps = worker
    fresh = stored_row(acting, db_session, world)
    old_id = insert_old(db_session, fresh, 13)
    db_session.flush()
    run_sweeps()
    remaining = {e.id for e in acting.evidence()}
    assert fresh.id in remaining and old_id not in remaining
