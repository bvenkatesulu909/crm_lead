# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""Company details: how real-looking sites behave end to end (BP-02, ADR 0026 step EN5).

The EN3 tests cover the API rules; these play whole sites through the real worker, fetcher and
parser (only the network is the in-process demo): a page with no facts, a redirect to ``www.``, a
redirect somewhere else, a site that forbids robots, and a free-mail lead. Whatever happens, nothing
is written on the lead until a person saves, and a refusal is recorded, not raised."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core.outbox import OutboxJob, enqueue
from app.modules.webcheck.company_details import COMPANY_JOB
from app.modules.webcheck.models import WebEvidence
from tests.db.conftest import setup_lead_context
from tests.db.test_approvals import alpha
from tests.db.test_company_details_api import (  # noqa: F401
    add_lead,
    apply,
    ask,
    looked_up,
    read,
    switch,
)
from tests.db.test_quotes_api import auth, code_of, ok, world  # noqa: F401
from tests.db.test_webcheck_api import api, make_api, settings, worker  # noqa: F401


def test_a_page_without_facts_suggests_no_industry_or_size(
    api, auth, world, db_session, worker
) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website="https://plain.demo.example")
    latest = looked_up(api, auth, worker, lead)["latest"]
    assert latest["verdict"] == "not_found"
    assert (latest["company_industry"], latest["company_size"]) == (None, None)
    refused = apply(api, auth, lead, latest, ["company_industry"], 1)
    assert code_of(refused) == (422, "field_not_suggested")


def test_nothing_is_written_on_the_lead_until_a_person_saves(
    api, auth, world, db_session, worker
) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website="https://acme-builders.demo.example")
    body = looked_up(api, auth, worker, lead)
    assert body["latest"]["verdict"] == "found"
    assert body["current"]["company_industry"] is None
    assert body["current"]["version"] == 1


def test_a_redirect_to_www_is_followed(api, auth, world, db_session, worker) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website="https://redirect.demo.example")
    latest = looked_up(api, auth, worker, lead)["latest"]
    assert latest["verdict"] != "error"
    assert latest["company_website"] == "https://www.redirect.demo.example"


def test_a_redirect_to_another_site_is_refused_and_nothing_is_suggested(
    api, auth, world, db_session, worker
) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website="https://elsewhere.demo.example")
    latest = looked_up(api, auth, worker, lead)["latest"]
    assert latest["company_website"] is None
    assert "evil.example" not in str(latest)


def test_a_site_that_forbids_robots_is_not_read(api, auth, world, db_session, worker) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website="https://blocked.demo.example")
    latest = looked_up(api, auth, worker, lead)["latest"]
    assert (latest["verdict"], latest["error_code"]) == ("unclear", "robots_disallowed") or (
        latest["verdict"],
        latest["error_code"],
    ) == ("error", "robots_disallowed")
    assert latest["company_website"] is None


@pytest.mark.parametrize("email", ["jamie@gmail.com", "jamie@yahoo.com", "jamie@outlook.com"])
def test_a_free_mail_lead_is_refused_before_anything_is_queued(
    api, auth, world, db_session, worker, email
) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, email=email)
    refused: Any = ask(api, auth, lead)
    assert code_of(refused) == (422, "company_host_free_mail")
    assert ok(read(api, auth, lead))["latest"] is None


def _queue(db_session: Any, world: Any, lead: Any, host: str, request_id: Any = None) -> Any:
    """Put a company job on the queue directly, as if an older or forged one were waiting."""
    request_id = request_id or uuid.uuid4()
    enqueue(
        db_session,
        tenant_id=alpha(world),
        kind=COMPANY_JOB,
        payload={
            "request_id": str(request_id),
            "target_type": "lead",
            "target_id": str(lead.id),
            "host": host,
            "requested_by_user_id": str(world.users["alpha.agent1"].id),
        },
    )
    db_session.flush()
    return request_id


def _stored(db_session: Any, world: Any, lead: Any) -> list[WebEvidence]:
    setup_lead_context(db_session, alpha(world), scope="all")
    return list(db_session.scalars(select(WebEvidence).where(WebEvidence.target_id == lead.id)))


def test_a_job_with_a_private_host_is_refused_by_the_worker_itself(
    api, auth, world, db_session, worker
) -> None:
    # The asking side checks the host too; the worker checks again because a job can wait a while
    # and the rules can tighten, or a job can be forged.
    switch(api, auth)
    lead = add_lead(db_session, world, company_website="https://acme-builders.demo.example")
    _queue(db_session, world, lead, "10.0.0.5")
    worker()
    (row,) = _stored(db_session, world, lead)
    assert (row.verdict, row.error_code, row.suggestions) == ("error", "host_ip_literal", None)


def test_the_same_request_is_read_only_once(api, auth, world, db_session, worker) -> None:
    switch(api, auth)
    lead = add_lead(db_session, world, company_website="https://acme-builders.demo.example")
    request_id = _queue(db_session, world, lead, "acme-builders.demo.example")
    worker()
    _queue(db_session, world, lead, "acme-builders.demo.example", request_id)
    worker()
    assert len(_stored(db_session, world, lead)) == 1
    # The repeat finished quietly; it did not fail against the table and wait to be retried.
    jobs = db_session.scalars(select(OutboxJob).where(OutboxJob.kind == COMPANY_JOB)).all()
    assert [j.status for j in jobs] == ["done", "done"]
