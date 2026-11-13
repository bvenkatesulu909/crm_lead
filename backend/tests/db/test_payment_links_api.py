"""UPI payment links through the real API, webhook and worker (ADR 0031, UP2).

Real PostgreSQL, rolled back. Razorpay is the scripted fake provider; webhook bodies are signed here
with the same HMAC Razorpay uses. Invoices come from the real invoices API.

tenant ALPHA: admin, manager, agent1 (owns A1), agent2 (owns A2), support, customer1 -> A1,
              customer2 -> A2
tenant BETA:  admin, customer -> B1
"""

# ruff: noqa: F811 - the fixtures are imported and used by name

import json
import uuid
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Connection, select, text
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.mail import MemoryMailer
from app.core.observability.metrics import PAYMENT_WEBHOOKS
from app.core.outbox import Job, OutboxJob
from app.core.storage import MemoryFileStore
from app.modules.invoices.models import Invoice, Payment
from app.modules.notifications.models import Notification
from app.modules.payment_links import rules, service
from app.modules.payment_links.models import PaymentEvent, PaymentLink
from app.modules.payment_links.provider import FakeProvider, ProviderError
from app.worker import WorkerServices, job_handlers, run_due_jobs
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import forget_request_user, session_factory_for
from tests.db.test_invoices_api import (  # noqa: F401 - fixtures used by name
    LINES,
    Headers,
    World,
    api,
    auth,
    issued_invoice,
    ok,
    pay,
    world,
)

SECRET = "whsec-up2-test"  # noqa: S105 - a made-up test value
HOOK = "/api/v1/integrations/razorpay/webhook"
TOTAL_PAISE = 21416  # the invoices API's standard invoice: 214.16


@pytest.fixture
def hooked(api: TestClient) -> TestClient:
    """The API with a webhook secret, the way production has one."""
    app = cast(FastAPI, api.app)
    app.state.settings = app.state.settings.model_copy(
        update={"razorpay_webhook_secret": SecretStr(SECRET)}
    )
    return api


@pytest.fixture
def fake(hooked: TestClient) -> FakeProvider:
    provider = cast(FastAPI, hooked.app).state.payment_provider
    assert isinstance(provider, FakeProvider)
    return provider


def app_of(api: TestClient) -> FastAPI:
    return cast(FastAPI, api.app)


def switch(api: TestClient, auth: Headers, on: bool = True) -> None:
    url = "/api/v1/agents/payment_links"
    current = api.get(url, headers=auth("alpha.admin")).json()
    body: dict[str, Any] = {"enabled": on}
    if current.get("version") is not None:
        body["version"] = current["version"]
    ok(api.patch(url, json=body, headers=auth("alpha.admin")))


@pytest.fixture
def on(hooked: TestClient, auth: Headers) -> None:
    switch(hooked, auth, True)


def inr_invoice(
    api: TestClient,
    auth: Headers,
    world: World,
    account: str = "A1",
    currency: str = "INR",
    issue: bool = True,
) -> dict[str, Any]:
    """An issued invoice in INR (the invoices tests' default currency is EUR)."""
    admin = auth("alpha.admin")
    order = ok(
        api.post(
            "/api/v1/orders",
            json={"account_id": str(world.accounts[account]), "currency": currency, "lines": LINES},
            headers=admin,
        ),
        201,
    )
    order = ok(
        api.post(
            f"/api/v1/orders/{order['id']}/status",
            json={"status": "confirmed", "version": order["version"]},
            headers=admin,
        )
    )
    draft = ok(api.post("/api/v1/invoices", json={"order_id": order["id"]}, headers=admin), 201)
    if not issue:
        return draft
    return ok(
        api.post(
            f"/api/v1/invoices/{draft['id']}/issue",
            json={"version": draft["version"]},
            headers=admin,
        )
    )


def invoice_of(api: TestClient, auth: Headers, world: World, account: str = "A1") -> str:
    return str(inr_invoice(api, auth, world, account)["id"])


def make_link(
    api: TestClient, auth: Headers, invoice_id: str, user: str = "alpha.admin", code: int = 201
) -> dict[str, Any]:
    response = api.post(
        "/api/v1/payment-links", json={"invoice_id": invoice_id}, headers=auth(user)
    )
    assert response.status_code == code, response.text
    result: dict[str, Any] = response.json()
    return result


def event_body(
    link_id: str,
    payment_id: str = "pay_1",
    amount: int = TOTAL_PAISE,
    currency: str = "INR",
    event: str = "payment_link.paid",
) -> bytes:
    return json.dumps(
        {
            "event": event,
            "payload": {
                "payment_link": {"entity": {"id": link_id}},
                "payment": {"entity": {"id": payment_id, "amount": amount, "currency": currency}},
            },
        }
    ).encode()


def post_hook(
    api: TestClient,
    body: bytes,
    *,
    secret: str | None = SECRET,
    signature: str | None = None,
    event_id: str | None = None,
) -> Any:
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Razorpay-Signature"] = signature
    elif secret is not None:
        headers["X-Razorpay-Signature"] = rules.sign(body, secret)
    headers["X-Razorpay-Event-Id"] = event_id or f"evt_{uuid.uuid4().hex[:12]}"
    return api.post(HOOK, content=body, headers=headers)


def provider_id(db_session: Session, world: World, link: dict[str, Any]) -> str:
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    return str(
        db_session.scalar(select(PaymentLink.provider_link_id).where(PaymentLink.id == link["id"]))
    )


@pytest.fixture
def run_worker(db_connection: Connection):
    config = Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
    )
    factory = session_factory_for(db_connection)
    handlers = job_handlers(WorkerServices(config, MemoryFileStore(), MemoryMailer()))

    def run() -> int:
        with factory() as fresh, fresh.begin():
            forget_request_user(fresh)  # like a real worker transaction
        return run_due_jobs(factory, handlers, config)

    return run


def alpha_rows(db_session: Session, world: World, model: Any) -> list[Any]:
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    return list(db_session.scalars(select(model)).all())


def balance(db_session: Session, world: World, invoice_id: str) -> Decimal:
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    row = db_session.scalars(select(Invoice).where(Invoice.id == invoice_id)).one()
    db_session.refresh(row)
    return row.balance_due


def counter(result: str) -> float:
    return float(PAYMENT_WEBHOOKS.labels(result)._value.get())


# --- creating a link -------------------------------------------------------------------------


def test_the_feature_is_off_until_an_administrator_switches_it_on(hooked, auth, world) -> None:
    invoice = invoice_of(hooked, auth, world)
    problem = make_link(hooked, auth, invoice, code=503)
    assert problem["code"] == "payment_links_unavailable"


def test_an_administrator_creates_a_link_for_the_balance(hooked, auth, world, on, fake) -> None:
    invoice = invoice_of(hooked, auth, world)
    link = make_link(hooked, auth, invoice)
    assert (link["status"], link["amount"], link["currency"]) == ("created", "214.16", "INR")
    assert link["invoice_id"] == invoice and link["short_url"].startswith("https://")
    [sent] = fake.links.values()
    assert sent["amount_paise"] == TOTAL_PAISE and sent["currency"] == "INR"


def test_a_manager_may_create_a_link_too(hooked, auth, world, on) -> None:
    make_link(hooked, auth, invoice_of(hooked, auth, world), "alpha.manager")


def test_the_client_cannot_choose_the_amount_or_anything_else(hooked, auth, world, on) -> None:
    invoice = invoice_of(hooked, auth, world)
    for extra in ({"amount": "1.00"}, {"tenant_id": str(uuid.uuid4())}, {"status": "paid"}):
        response = hooked.post(
            "/api/v1/payment-links",
            json={"invoice_id": invoice, **extra},
            headers=auth("alpha.admin"),
        )
        assert response.status_code == 422, extra


def test_the_amount_follows_what_is_still_owed(hooked, auth, world, on, fake) -> None:
    invoice = inr_invoice(hooked, auth, world)
    ok(pay(hooked, auth, invoice, "100.00"), 201)
    link = make_link(hooked, auth, invoice["id"])
    assert link["amount"] == "114.16"
    assert next(iter(fake.links.values()))["amount_paise"] == 11416


def test_a_new_link_replaces_the_open_one(hooked, auth, world, on, fake) -> None:
    invoice = invoice_of(hooked, auth, world)
    first = make_link(hooked, auth, invoice)
    second = make_link(hooked, auth, invoice)
    assert first["id"] != second["id"]
    listed = ok(
        hooked.get(f"/api/v1/payment-links?invoice_id={invoice}", headers=auth("alpha.admin"))
    )["items"]
    assert [item["status"] for item in listed] == ["created", "cancelled"]
    assert len(fake.cancelled) == 1


def test_a_replaced_link_is_replaced_even_if_the_provider_cannot_cancel_it(
    hooked, auth, world, on, fake
) -> None:
    invoice = invoice_of(hooked, auth, world)
    make_link(hooked, auth, invoice)
    fake.cancel_link = lambda _id: (_ for _ in ()).throw(ProviderError("gone"))
    make_link(hooked, auth, invoice)


def test_every_link_gets_its_own_reference(hooked, auth, world, on, fake) -> None:
    invoice = invoice_of(hooked, auth, world)
    make_link(hooked, auth, invoice)
    make_link(hooked, auth, invoice)
    references = [link["reference_id"] for link in fake.links.values()]
    assert len(set(references)) == 2 and all(len(r) <= 40 for r in references)


def test_a_draft_invoice_cannot_be_paid(hooked, auth, world, on) -> None:
    draft = inr_invoice(hooked, auth, world, issue=False)
    problem = make_link(hooked, auth, draft["id"], code=409)
    assert problem["code"] == "invoice_not_payable" and "issued" in problem["detail"]


def test_only_invoices_in_rupees_can_be_paid_by_upi(hooked, auth, world, on) -> None:
    euro = inr_invoice(hooked, auth, world, currency="EUR")
    problem = make_link(hooked, auth, euro["id"], code=409)
    assert problem["code"] == "invoice_not_payable" and "INR" in problem["detail"]


def test_a_fully_paid_invoice_cannot_be_paid_again(hooked, auth, world, on) -> None:
    invoice = inr_invoice(hooked, auth, world)
    ok(pay(hooked, auth, invoice, "214.16"), 201)
    problem = make_link(hooked, auth, invoice["id"], code=409)
    assert problem["code"] == "invoice_not_payable" and "nothing left" in problem["detail"]


def test_a_made_up_invoice_is_not_found(hooked, auth, world, on) -> None:
    assert make_link(hooked, auth, str(uuid.uuid4()), code=404)["code"] == "invoice_not_found"


def test_another_organisations_invoice_is_not_found(hooked, auth, world, on) -> None:
    invoice = invoice_of(hooked, auth, world)
    switch_beta = hooked.get("/api/v1/agents/payment_links", headers=auth("beta.admin"))
    ok(
        hooked.patch(
            "/api/v1/agents/payment_links",
            json={
                "enabled": True,
                **(
                    {"version": switch_beta.json()["version"]}
                    if switch_beta.json().get("version") is not None
                    else {}
                ),
            },
            headers=auth("beta.admin"),
        )
    )
    assert make_link(hooked, auth, invoice, "beta.admin", code=404)["code"] == "invoice_not_found"


@pytest.mark.parametrize("who", ["alpha.agent1", "alpha.support", "alpha.customer1"])
def test_only_those_who_collect_payments_may_create_a_link(hooked, auth, world, on, who) -> None:
    invoice = invoice_of(hooked, auth, world)
    make_link(hooked, auth, invoice, who, code=403)


def test_a_provider_that_is_down_stores_nothing(hooked, auth, world, on, fake, db_session) -> None:
    def down(**_: Any) -> None:
        raise ProviderError("Razorpay answered with status 500.")

    fake.create_link = down
    invoice = invoice_of(hooked, auth, world)
    problem = make_link(hooked, auth, invoice, code=503)
    assert problem["code"] == "payment_provider_unavailable"
    assert alpha_rows(db_session, world, PaymentLink) == []
    assert "500" not in json.dumps(problem)


def test_the_hourly_limit_stops_a_flood(hooked, auth, world, on) -> None:
    app_of(hooked).state.settings = app_of(hooked).state.settings.model_copy(
        update={"razorpay_links_per_user_hour": 2}
    )
    invoice = invoice_of(hooked, auth, world)
    make_link(hooked, auth, invoice)
    make_link(hooked, auth, invoice)
    assert make_link(hooked, auth, invoice, code=429)["code"] == "payment_link_rate_limited"


def test_creating_a_link_is_audited_with_ids_only(hooked, auth, world, on, db_session) -> None:
    link = make_link(hooked, auth, invoice_of(hooked, auth, world))
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    row = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "payment_link.created")
    ).one()
    assert str(row.entity_id) == link["id"]
    assert "pay.fake.invalid" not in json.dumps(row.changes, default=str)


# --- reading links ---------------------------------------------------------------------------


def test_the_owner_of_the_account_sees_the_links_of_its_invoice(hooked, auth, world, on) -> None:
    invoice = invoice_of(hooked, auth, world, "A1")
    make_link(hooked, auth, invoice)
    url = f"/api/v1/payment-links?invoice_id={invoice}"
    assert len(ok(hooked.get(url, headers=auth("alpha.agent1")))["items"]) == 1
    assert hooked.get(url, headers=auth("alpha.agent2")).status_code == 404  # not their account


def test_a_customer_sees_only_the_open_link_of_their_own_invoice(hooked, auth, world, on) -> None:
    invoice = invoice_of(hooked, auth, world, "A1")
    make_link(hooked, auth, invoice)
    open_one = make_link(hooked, auth, invoice)
    url = f"/api/v1/portal/payment-links?invoice_id={invoice}"
    items = ok(hooked.get(url, headers=auth("alpha.customer1")))["items"]
    assert [item["id"] for item in items] == [open_one["id"]]
    assert hooked.get(url, headers=auth("alpha.customer2")).status_code == 404


def test_a_customer_sees_nothing_when_there_is_no_open_link(hooked, auth, world, on) -> None:
    invoice = invoice_of(hooked, auth, world, "A1")
    url = f"/api/v1/portal/payment-links?invoice_id={invoice}"
    assert ok(hooked.get(url, headers=auth("alpha.customer1")))["items"] == []


def test_staff_endpoints_refuse_a_customer_and_the_portal_refuses_staff(
    hooked, auth, world, on
) -> None:
    invoice = invoice_of(hooked, auth, world, "A1")
    staff = f"/api/v1/payment-links?invoice_id={invoice}"
    portal = f"/api/v1/portal/payment-links?invoice_id={invoice}"
    assert hooked.get(staff, headers=auth("alpha.customer1")).status_code == 403
    assert hooked.get(portal, headers=auth("alpha.admin")).status_code == 403


def test_the_endpoints_need_a_sign_in_but_the_webhook_does_not(hooked, auth, world, on) -> None:
    assert hooked.get("/api/v1/payment-links?invoice_id=" + str(uuid.uuid4())).status_code == 401
    assert hooked.post("/api/v1/payment-links", json={}).status_code == 401
    assert hooked.post(HOOK, content=b"{}").status_code == 401  # refused for the signature only


# --- the webhook: who may speak --------------------------------------------------------------


def paid_link(hooked, auth, world, db_session) -> tuple[str, dict[str, Any], str]:
    invoice = invoice_of(hooked, auth, world)
    link = make_link(hooked, auth, invoice)
    return invoice, link, provider_id(db_session, world, link)


def test_a_wrong_signature_is_refused_and_stores_nothing(
    hooked, auth, world, on, db_session
) -> None:
    _, _, pid = paid_link(hooked, auth, world, db_session)
    before = counter("bad_signature")
    response = post_hook(hooked, event_body(pid), signature="0" * 64)
    assert response.status_code == 401 and response.json()["code"] == "invalid_signature"
    assert alpha_rows(db_session, world, PaymentEvent) == []
    assert counter("bad_signature") == before + 1


def test_a_missing_signature_is_refused(hooked, auth, world, on, db_session) -> None:
    _, _, pid = paid_link(hooked, auth, world, db_session)
    assert post_hook(hooked, event_body(pid), secret=None).status_code == 401


def test_a_body_changed_after_signing_is_refused(hooked, auth, world, on, db_session) -> None:
    _, _, pid = paid_link(hooked, auth, world, db_session)
    signed = event_body(pid, amount=TOTAL_PAISE)
    forged = event_body(pid, amount=100)
    response = post_hook(hooked, forged, signature=rules.sign(signed, SECRET))
    assert response.status_code == 401


def test_a_signature_made_with_another_secret_is_refused(
    hooked, auth, world, on, db_session
) -> None:
    _, _, pid = paid_link(hooked, auth, world, db_session)
    assert post_hook(hooked, event_body(pid), secret="someone-elses-secret").status_code == 401  # noqa: S106


def test_without_a_configured_secret_every_delivery_is_refused(
    api, auth, world, db_session
) -> None:
    """No secret on the server must refuse, never accept: otherwise anyone could post a payment."""
    body = event_body("plink_x")
    assert post_hook(api, body, signature=rules.sign(body, "")).status_code == 401
    assert post_hook(api, body, secret=SECRET).status_code == 401


def test_an_oversized_body_is_refused_before_it_is_read(hooked, auth, world, on) -> None:
    body = b"x" * (service.MAX_BODY_BYTES + 1)
    assert post_hook(hooked, body).status_code == 413


def test_an_oversized_body_without_a_declared_length_is_refused_too(
    hooked, auth, world, on
) -> None:
    """A sender can skip Content-Length (chunked): the size is checked on what was really read."""
    chunks = iter([b"x" * 40_000, b"x" * 40_000])
    response = hooked.post(HOOK, content=chunks, headers={"X-Razorpay-Signature": "0" * 64})
    assert response.status_code == 413


# --- the webhook: what a verified delivery does ----------------------------------------------


def test_a_verified_payment_is_stored_and_changes_nothing_until_the_worker_runs(
    hooked, auth, world, on, db_session
) -> None:
    invoice, _, pid = paid_link(hooked, auth, world, db_session)
    response = post_hook(hooked, event_body(pid))
    assert response.status_code == 200 and response.json() == {"result": "stored"}
    [event] = alpha_rows(db_session, world, PaymentEvent)
    assert (event.outcome, event.event_type) == (None, "payment_link.paid")
    assert event.facts == {"payment_id": "pay_1", "amount_paise": TOTAL_PAISE, "currency": "INR"}
    assert balance(db_session, world, invoice) == Decimal("214.16")  # nothing yet
    jobs = db_session.scalars(select(OutboxJob).where(OutboxJob.kind == "payment_link.apply")).all()
    assert len(jobs) == 1 and jobs[0].payload == {"event_id": str(event.id)}


def test_the_worker_records_the_payment_and_closes_the_link(
    hooked, auth, world, on, db_session, run_worker
) -> None:
    invoice, link, pid = paid_link(hooked, auth, world, db_session)
    post_hook(hooked, event_body(pid, "pay_42"))
    run_worker()
    assert balance(db_session, world, invoice) == Decimal("0.00")
    [payment] = alpha_rows(db_session, world, Payment)
    assert (payment.method, payment.reference, payment.amount) == (
        "upi",
        "pay_42",
        Decimal("214.16"),
    )
    [row] = alpha_rows(db_session, world, PaymentLink)
    assert (row.status, row.provider_payment_id) == ("paid", "pay_42") and row.paid_at
    [event] = alpha_rows(db_session, world, PaymentEvent)
    assert event.outcome == "applied" and event.processed_at is not None
    detail = ok(hooked.get(f"/api/v1/invoices/{invoice}", headers=auth("alpha.admin")))
    assert detail["payment_state"] == "paid" and detail["payments"][0]["method"] == "upi"


def test_the_person_who_made_the_link_is_told(
    hooked, auth, world, on, db_session, run_worker
) -> None:
    _, _, pid = paid_link(hooked, auth, world, db_session)
    post_hook(hooked, event_body(pid))
    run_worker()
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    notes = db_session.scalars(
        select(Notification).where(Notification.type == "payment_link.paid")
    ).all()
    assert [n.user_id for n in notes] == [world.users["alpha.admin"].id]
    assert notes[0].title.startswith("UPI payment received: Invoice")
    assert notes[0].link.startswith("/invoices/")


def test_the_payment_is_audited_as_the_automation_identity(
    hooked, auth, world, on, db_session, run_worker
) -> None:
    _, _, pid = paid_link(hooked, auth, world, db_session)
    post_hook(hooked, event_body(pid))
    run_worker()
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    actions = {a.action for a in db_session.scalars(select(AuditLog)).all()}
    assert {"payment_link.paid", "payment.recorded"} <= actions


def test_the_same_delivery_twice_is_one_event_and_one_payment(
    hooked, auth, world, on, db_session, run_worker
) -> None:
    invoice, _, pid = paid_link(hooked, auth, world, db_session)
    body = event_body(pid)
    assert post_hook(hooked, body, event_id="evt_same").json() == {"result": "stored"}
    assert post_hook(hooked, body, event_id="evt_same").json() == {"result": "duplicate"}
    run_worker()
    assert len(alpha_rows(db_session, world, PaymentEvent)) == 1
    assert len(alpha_rows(db_session, world, Payment)) == 1
    assert balance(db_session, world, invoice) == Decimal("0.00")


def test_the_same_payment_under_a_new_event_id_adds_no_second_payment(
    hooked, auth, world, on, db_session, run_worker
) -> None:
    _, _, pid = paid_link(hooked, auth, world, db_session)
    post_hook(hooked, event_body(pid, "pay_9"), event_id="evt_a")
    post_hook(hooked, event_body(pid, "pay_9"), event_id="evt_b")
    run_worker()
    assert len(alpha_rows(db_session, world, Payment)) == 1
    outcomes = sorted(e.outcome for e in alpha_rows(db_session, world, PaymentEvent))
    assert outcomes == ["already_applied", "applied"]


def test_the_job_is_safe_to_run_twice(hooked, auth, world, on, db_session, run_worker) -> None:
    _, _, pid = paid_link(hooked, auth, world, db_session)
    post_hook(hooked, event_body(pid))
    run_worker()
    [job] = db_session.scalars(
        select(OutboxJob).where(OutboxJob.kind == "payment_link.apply")
    ).all()
    bind_tenant(db_session, job.tenant_id)
    service.apply_event(db_session, Job(job.id, job.tenant_id, job.kind, job.payload, 2))
    assert len(alpha_rows(db_session, world, Payment)) == 1


def test_a_different_amount_is_not_recorded_and_a_person_is_told(
    hooked, auth, world, on, db_session, run_worker
) -> None:
    invoice, _, pid = paid_link(hooked, auth, world, db_session)
    post_hook(hooked, event_body(pid, amount=TOTAL_PAISE - 100))
    run_worker()
    assert balance(db_session, world, invoice) == Decimal("214.16")
    assert alpha_rows(db_session, world, Payment) == []
    [event] = alpha_rows(db_session, world, PaymentEvent)
    assert event.outcome == "amount_mismatch"
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    notes = db_session.scalars(
        select(Notification).where(Notification.type == "payment_link.needs_review")
    ).all()
    assert notes and "differs from the link" in notes[0].title
    assert {n.user_id for n in notes} >= {world.users["alpha.admin"].id}


def test_another_currency_is_not_recorded(hooked, auth, world, on, db_session, run_worker) -> None:
    _, _, pid = paid_link(hooked, auth, world, db_session)
    post_hook(hooked, event_body(pid, currency="USD"))
    run_worker()
    assert alpha_rows(db_session, world, Payment) == []
    assert alpha_rows(db_session, world, PaymentEvent)[0].outcome == "currency_mismatch"


def test_money_that_arrives_after_the_invoice_was_settled_is_flagged(
    hooked, auth, world, on, db_session, run_worker
) -> None:
    invoice, _, pid = paid_link(hooked, auth, world, db_session)
    ok(pay(hooked, auth, {"id": invoice}, "214.16"), 201)  # paid by bank transfer meanwhile
    post_hook(hooked, event_body(pid))
    run_worker()
    assert len(alpha_rows(db_session, world, Payment)) == 1  # only the manual one
    assert alpha_rows(db_session, world, PaymentEvent)[0].outcome == "invoice_closed"


def test_a_payment_after_a_part_payment_that_leaves_too_little_is_flagged(
    hooked, auth, world, on, db_session, run_worker
) -> None:
    invoice, _, pid = paid_link(hooked, auth, world, db_session)
    ok(pay(hooked, auth, {"id": invoice}, "100.00"), 201)
    post_hook(hooked, event_body(pid))  # the link was for the whole 214.16
    run_worker()
    assert alpha_rows(db_session, world, PaymentEvent)[0].outcome == "amount_mismatch"
    assert balance(db_session, world, invoice) == Decimal("114.16")


def test_a_link_that_was_replaced_can_still_be_paid(
    hooked, auth, world, on, db_session, run_worker
) -> None:
    """The buyer paid the old link a moment before it was replaced: the money is real."""
    invoice = invoice_of(hooked, auth, world)
    old = make_link(hooked, auth, invoice)
    old_pid = provider_id(db_session, world, old)
    make_link(hooked, auth, invoice)
    post_hook(hooked, event_body(old_pid))
    run_worker()
    assert balance(db_session, world, invoice) == Decimal("0.00")


def test_payments_on_their_way_are_recorded_even_after_the_switch_is_turned_off(
    hooked, auth, world, on, db_session, run_worker
) -> None:
    invoice, _, pid = paid_link(hooked, auth, world, db_session)
    switch(hooked, auth, False)
    post_hook(hooked, event_body(pid))
    run_worker()
    assert balance(db_session, world, invoice) == Decimal("0.00")


def test_an_expired_event_frees_the_invoice_for_a_new_link(
    hooked, auth, world, on, db_session, run_worker
) -> None:
    invoice, _, pid = paid_link(hooked, auth, world, db_session)
    post_hook(hooked, event_body(pid, event="payment_link.expired"))
    run_worker()
    assert alpha_rows(db_session, world, PaymentLink)[0].status == "expired"
    assert alpha_rows(db_session, world, Payment) == []
    make_link(hooked, auth, invoice)


def test_a_link_nobody_knows_is_acknowledged_and_stores_nothing(
    hooked, auth, world, on, db_session
) -> None:
    before = counter("unknown_link")
    response = post_hook(hooked, event_body("plink_unknown"))
    assert response.status_code == 200 and response.json() == {"result": "unknown_link"}
    assert alpha_rows(db_session, world, PaymentEvent) == []
    assert counter("unknown_link") == before + 1


@pytest.mark.parametrize("event", ["payment.captured", "order.paid", "refund.created"])
def test_events_we_do_not_act_on_are_acknowledged_and_dropped(
    hooked, auth, world, on, db_session, event
) -> None:
    _, _, pid = paid_link(hooked, auth, world, db_session)
    response = post_hook(hooked, event_body(pid, event=event))
    assert response.status_code == 200 and response.json() == {"result": "ignored"}
    assert alpha_rows(db_session, world, PaymentEvent) == []


def test_a_verified_body_in_the_wrong_shape_is_acknowledged_not_an_error(
    hooked, auth, world, on
) -> None:
    for body in (b"not json", b"[]", b'{"event": "payment_link.paid"}'):
        response = post_hook(hooked, body)
        assert response.status_code == 200 and response.json() == {"result": "ignored"}


def test_the_organisation_comes_from_the_link_never_from_the_body(
    hooked, auth, world, on, db_session, run_worker
) -> None:
    invoice, _, pid = paid_link(hooked, auth, world, db_session)
    other = world.users["beta.admin"].tenant_id
    body = json.loads(event_body(pid))
    body["tenant_id"] = str(other)
    body["payload"]["payment_link"]["entity"]["notes"] = {"tenant_id": str(other)}
    post_hook(hooked, json.dumps(body).encode())
    run_worker()
    assert balance(db_session, world, invoice) == Decimal("0.00")  # alpha's invoice, alpha's link
    bind_tenant(db_session, other)
    assert db_session.scalars(select(PaymentEvent)).all() == []


def test_the_webhook_does_not_leak_anything_in_its_answers(
    hooked, auth, world, on, db_session
) -> None:
    _, _, pid = paid_link(hooked, auth, world, db_session)
    for response in (
        post_hook(hooked, event_body(pid)),
        post_hook(hooked, event_body("plink_unknown")),
        post_hook(hooked, b"x", signature="0" * 64),
    ):
        assert pid not in response.text and SECRET not in response.text


# --- a manual UPI payment entered by hand ----------------------------------------------------


def test_a_person_may_record_a_upi_payment_by_hand(hooked, auth, world) -> None:
    invoice = issued_invoice(hooked, auth, world.accounts["A1"])
    payment = ok(pay(hooked, auth, invoice, "10.00", method="upi", reference="ref-1"), 201)
    assert payment["payments"][0]["method"] == "upi"


def test_the_same_upi_reference_cannot_be_recorded_twice(hooked, auth, world) -> None:
    invoice = issued_invoice(hooked, auth, world.accounts["A1"])
    ok(pay(hooked, auth, invoice, "10.00", method="upi", reference="ref-1"), 201)
    again = pay(hooked, auth, invoice, "10.00", method="upi", reference="ref-1")
    assert again.status_code == 409 and again.json()["code"] == "payment_reference_used"


def test_the_database_itself_refuses_a_repeated_upi_reference(
    hooked, auth, world, db_session
) -> None:
    from sqlalchemy.exc import IntegrityError

    invoice = issued_invoice(hooked, auth, world.accounts["A1"])
    ok(pay(hooked, auth, invoice, "10.00", method="upi", reference="ref-2"), 201)
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    first = db_session.scalars(select(Payment)).one()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "insert into payments (tenant_id, invoice_id, amount, received_on, method, "
                    "reference) values (:t, :i, 1, current_date, 'upi', 'ref-2')"
                ),
                {"t": first.tenant_id, "i": first.invoice_id},
            )


def test_a_reversal_of_a_upi_payment_does_not_clash_with_the_reference(hooked, auth, world) -> None:
    invoice = issued_invoice(hooked, auth, world.accounts["A1"])
    done = ok(pay(hooked, auth, invoice, "10.00", method="upi", reference="ref-3"), 201)
    payment_id = done["payments"][0]["id"]
    ok(
        hooked.post(
            f"/api/v1/invoices/{invoice['id']}/payments/{payment_id}/reverse",
            json={"reason": "Bounced"},
            headers=auth("alpha.admin"),
        ),
        201,
    )
