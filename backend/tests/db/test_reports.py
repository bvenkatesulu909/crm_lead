# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Reports and the report builder (Phase 18), through the real API and PostgreSQL.

People come from test_quotes_api.py: tenant alpha has admin, manager, manager2, agent1 (owns
A1, contact C1, deal O1), agent2 (owns A2, deal O2), support, customers; tenant beta has admin
and agent (owns B1).
"""

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.db import bind_tenant
from app.modules.leads.models import Lead
from app.modules.sales.models import Opportunity
from tests.db.conftest import setup_lead_context
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    Headers,
    World,
    api,
    auth,
    code_of,
    new_quote,
    ok,
    step,
    world,
)

REPORTS = "/api/v1/reports"


def get(api, auth, user: str, path: str = "", **params: Any) -> Any:
    return api.get(f"{REPORTS}{path}", params=params, headers=auth(user))


def rows(section: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = section["rows"]
    return found


def csv_rows(response: Any) -> list[list[str]]:
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["cache-control"] == "private, no-store"
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


def alpha(world: World) -> uuid.UUID:
    return world.users["alpha.agent1"].tenant_id


def add_deal(db_session: Session, world: World, owner: str, stage: str, amount: str, **kw: Any):
    now = datetime.now(UTC)
    bind_tenant(db_session, alpha(world))  # created as if in an alpha request
    deal = Opportunity(
        tenant_id=alpha(world),
        name=f"Deal {owner} {stage} {amount}",
        account_id=world.ids["A1" if owner == "alpha.agent1" else "A2"],
        owner_id=world.users[owner].id,
        stage=stage,
        amount=Decimal(amount),
        currency="EUR",
        closed_at=now if stage.startswith("closed") else None,
        lost_reason="Chose a cheaper offer" if stage == "closed_lost" else None,
        **kw,
    )
    db_session.add(deal)
    db_session.flush()
    return deal


# --- catalogue -------------------------------------------------------------------------------


def test_each_role_sees_its_own_reports_and_record_types(api, auth, world) -> None:
    agent = ok(get(api, auth, "alpha.agent1"))
    assert [r["key"] for r in agent["reports"]] == ["sales", "leads", "revenue", "support"]
    assert agent["can_filter_by_rep"] is False
    assert "contacts" in {t["key"] for t in agent["record_types"]}
    support = ok(get(api, auth, "alpha.support"))
    assert [r["key"] for r in support["reports"]] == ["revenue", "support"]
    assert {t["key"] for t in support["record_types"]} >= {"accounts", "orders", "tickets"}
    assert "leads" not in {t["key"] for t in support["record_types"]}
    assert ok(get(api, auth, "alpha.manager"))["can_filter_by_rep"] is True


@pytest.mark.parametrize("user", ["alpha.customer", "beta.admin"])
def test_customers_have_no_reports(api, auth, world, user) -> None:
    if user == "alpha.customer":
        assert get(api, auth, user).status_code == 403
        assert get(api, auth, user, "/sales").status_code == 403
    else:  # another organisation: its own, empty, reports
        assert ok(get(api, auth, user, "/sales"))["sections"][0]["rows"] == []


# --- sales: win rate -------------------------------------------------------------------------


def test_win_rate_counts_only_what_the_user_may_see(api, auth, world, db_session) -> None:
    add_deal(db_session, world, "alpha.agent1", "closed_won", "1000.00")
    add_deal(db_session, world, "alpha.agent1", "closed_won", "500.00")
    add_deal(db_session, world, "alpha.agent1", "closed_lost", "300.00")
    add_deal(db_session, world, "alpha.agent2", "closed_won", "250.00")
    add_deal(db_session, world, "alpha.agent2", "prospecting", "999.00")  # not closed: ignored

    manager = ok(get(api, auth, "alpha.manager", "/sales"))
    table = manager["sections"][0]
    by_rep = {r["owner_id"]: r for r in rows(table)}
    assert by_rep["alpha.agent1"] | {} == by_rep["alpha.agent1"]  # names, not IDs
    one = by_rep["alpha.agent1"]
    assert (one["won"], one["lost"], one["win_rate"], one["won_value"], one["average_won"]) == (
        2, 1, "66.7", "1500.00", "750.00",
    )  # fmt: skip
    assert by_rep["alpha.agent2"]["win_rate"] == "100.0"

    # An agent only sees their own deals; no one else's rep column leaks.
    mine = ok(get(api, auth, "alpha.agent1", "/sales"))["sections"][0]
    assert [r["owner_id"] for r in rows(mine)] == ["alpha.agent1"]
    # Managers can narrow to one rep; agents can't ask for someone else's figures.
    narrowed = ok(
        get(api, auth, "alpha.manager", "/sales", owner_id=str(world.users["alpha.agent2"].id))
    )
    assert [r["owner_id"] for r in rows(narrowed["sections"][0])] == ["alpha.agent2"]
    other = get(api, auth, "alpha.agent1", "/sales", owner_id=str(world.users["alpha.agent2"].id))
    assert other.status_code == 403
    # The other organisation sees nothing of this.
    assert rows(ok(get(api, auth, "beta.admin", "/sales"))["sections"][0]) == []


# fmt: skip


def test_the_period_decides_which_closed_deals_count(api, auth, world, db_session) -> None:
    old = add_deal(db_session, world, "alpha.agent1", "closed_won", "100.00")
    old.closed_at = datetime.now(UTC) - timedelta(days=90)
    db_session.flush()
    default = ok(get(api, auth, "alpha.manager", "/sales"))["sections"][0]
    assert rows(default) == []  # default: last 30 days
    start = (date.today() - timedelta(days=120)).isoformat()
    wide = ok(get(api, auth, "alpha.manager", "/sales", start=start))["sections"][0]
    assert rows(wide)[0]["won"] == 1


@pytest.mark.parametrize(
    "params",
    [
        {"start": "2026-02-01", "end": "2026-01-01"},
        {"start": "2020-01-01", "end": "2026-10-01"},
        {"start": "not-a-date"},
    ],
)
def test_bad_periods_are_refused(api, auth, world, params) -> None:
    assert get(api, auth, "alpha.manager", "/sales", **params).status_code == 422
    assert get(api, auth, "alpha.manager", "/sales/csv", **params).status_code == 422


# --- leads -----------------------------------------------------------------------------------


def test_lead_conversion_by_source(api, auth, world, db_session) -> None:
    owner = world.users["alpha.agent1"].id
    setup_lead_context(db_session, alpha(world), owner)
    for source, status in [
        ("web", "new"),
        ("web", "unqualified"),
        ("referral", "new"),
        (None, "new"),
    ]:
        db_session.add(
            Lead(
                tenant_id=alpha(world), last_name="X", source=source, status=status, owner_id=owner
            )
        )
    db_session.flush()
    table = ok(get(api, auth, "alpha.agent1", "/leads"))["sections"][0]
    by_source = {r["source"]: r for r in rows(table)}
    assert (
        by_source["web"]["created"],
        by_source["web"]["unqualified"],
        by_source["web"]["open"],
    ) == (2, 1, 1)
    assert by_source["(none)"]["created"] == 1
    assert (by_source["Total"]["created"], by_source["Total"]["conversion_rate"]) == (4, "0.0")
    # Another agent has no leads of their own: nothing of agent1's.
    assert rows(ok(get(api, auth, "alpha.agent2", "/leads"))["sections"][0]) == []


# fmt: skip


# --- revenue & quotes & support --------------------------------------------------------------


def test_revenue_report_has_quote_figures_per_rep(api, auth, world) -> None:
    quote = new_quote(api, auth, world)
    quote = ok(step(api, auth, "alpha.agent1", quote, "submit"))
    quote = ok(step(api, auth, "alpha.agent1", quote, "send"))
    ok(
        api.post(
            f"/api/v1/portal/quotes/{quote['id']}/accept",
            json={"version": quote["version"]},
            headers=auth("alpha.customer"),
        )
    )
    report = ok(get(api, auth, "alpha.manager", "/revenue"))
    quotes = [s for s in report["sections"] if s["title"] == "Quotes"][0]
    [row] = rows(quotes)
    assert (row["owner_id"], row["sent"], row["accepted"], row["acceptance_rate"]) == (
        "alpha.agent1",
        1,
        1,
        "100.0",
    )
    # Support staff may read invoices/orders but not quotes: their report has no quote section.
    support = ok(get(api, auth, "alpha.support", "/revenue"))
    assert "Quotes" not in {s["title"] for s in support["sections"]}


# fmt: skip


def test_support_report_sections(api, auth, world) -> None:
    report = ok(get(api, auth, "alpha.support", "/support"))
    assert [s["title"] for s in report["sections"]] == [
        "Support by priority",
        "Support by category",
    ]
    assert get(api, auth, "alpha.agent1", "/nonsense").status_code == 404


# --- CSV -------------------------------------------------------------------------------------


def test_standard_reports_download_as_csv(api, auth, world, db_session) -> None:
    add_deal(db_session, world, "alpha.agent1", "closed_won", "1000.00")
    response = get(api, auth, "alpha.manager", "/sales/csv")
    assert response.headers["content-disposition"].startswith('attachment; filename="sales-')
    table = csv_rows(response)
    assert table[0] == [
        "Sales rep",
        "Won",
        "Lost",
        "Win rate %",
        "Won value",
        "Average won deal",
        "Currency",
    ]
    assert table[1][:4] == ["alpha.agent1", "1", "0", "100.0"]
    assert response.content.startswith(b"\xef\xbb\xbf")  # BOM for Excel


# fmt: skip


def test_csv_cells_cannot_run_as_formulas(api, auth, world, db_session) -> None:
    setup_lead_context(db_session, alpha(world), world.users["alpha.agent1"].id)
    for name in ('=HYPERLINK("http://evil.example")', "+cmd", "-1+1", "@SUM(A1)", "Normal Ltd"):
        db_session.add(
            Lead(tenant_id=alpha(world), last_name=name, owner_id=world.users["alpha.agent1"].id)
        )
    db_session.flush()
    response = get(api, auth, "alpha.agent1", "/builder/leads/csv", columns=["last_name"])
    cells = sorted(r[0] for r in csv_rows(response)[1:])
    assert '\'=HYPERLINK("http://evil.example")' in cells and "'+cmd" in cells
    assert "'-1+1" in cells and "'@SUM(A1)" in cells and "Normal Ltd" in cells
    assert not any(c.startswith(("=", "+", "-", "@")) for c in cells)


# --- report builder --------------------------------------------------------------------------


def test_builder_lists_only_what_the_user_may_see(api, auth, world, db_session) -> None:
    for owner, name in [("alpha.agent1", "Mine"), ("alpha.agent2", "Theirs")]:
        setup_lead_context(db_session, alpha(world), world.users[owner].id)
        db_session.add(Lead(tenant_id=alpha(world), last_name=name, owner_id=world.users[owner].id))
    db_session.flush()
    mine = ok(
        get(
            api, auth, "alpha.agent1", "/builder/leads", columns=["last_name", "status", "owner_id"]
        )
    )
    assert [c["key"] for c in mine["columns"]] == ["last_name", "status", "owner_id"]
    assert [r["last_name"] for r in mine["rows"]] == ["Mine"]
    assert mine["rows"][0]["owner_id"] == "alpha.agent1"
    everyone = ok(get(api, auth, "alpha.manager", "/builder/leads", columns=["last_name"]))
    assert {r["last_name"] for r in everyone["rows"]} >= {"Mine", "Theirs"}
    only_theirs = ok(get(api, auth, "alpha.manager", "/builder/leads", columns=["last_name"],
                         owner_id=str(world.users["alpha.agent2"].id)))  # fmt: skip
    assert [r["last_name"] for r in only_theirs["rows"]] == ["Theirs"]
    # Other organisations never appear.
    beta = ok(get(api, auth, "beta.admin", "/builder/leads", columns=["last_name"]))
    assert beta["rows"] == []


def test_builder_filters_by_status_and_period(api, auth, world, db_session) -> None:
    owner = world.users["alpha.agent1"].id
    setup_lead_context(db_session, alpha(world), owner)
    new = Lead(tenant_id=alpha(world), last_name="NewOne", status="new", owner_id=owner)
    contacted = Lead(
        tenant_id=alpha(world), last_name="Contacted", status="contacted", owner_id=owner
    )
    ancient = Lead(tenant_id=alpha(world), last_name="Ancient", status="new", owner_id=owner)
    db_session.add_all([new, contacted, ancient])
    db_session.flush()
    db_session.execute(
        update(Lead)
        .where(Lead.id == ancient.id)
        .values(created_at=datetime(2020, 1, 1, tzinfo=UTC))
    )
    got = ok(
        get(
            api,
            auth,
            "alpha.agent1",
            "/builder/leads",
            columns=["last_name"],
            status="new",
            start=(date.today() - timedelta(days=5)).isoformat(),
        )
    )
    assert [r["last_name"] for r in got["rows"]] == ["NewOne"]
    assert get(api, auth, "alpha.agent1", "/builder/leads", status="hacked").status_code == 422


@pytest.mark.parametrize(
    "column", ["tenant_id", "internal_note", "password", "owner_id;drop table x"]
)
def test_builder_only_exports_whitelisted_columns(api, auth, world, column) -> None:
    assert get(api, auth, "alpha.agent1", "/builder/leads", columns=[column]).status_code == 422
    assert (
        get(api, auth, "alpha.agent1", "/builder/quotes", columns=["internal_note"]).status_code
        == 422
    )


def test_builder_respects_roles(api, auth, world) -> None:
    for user, kind, expected in [
        ("alpha.support", "leads", 404),  # support has no lead access
        ("alpha.support", "tickets", 200),
        ("alpha.agent1", "tickets", 200),
        ("alpha.customer", "tickets", 403),
        ("alpha.agent1", "nonsense", 404),
    ]:
        assert get(api, auth, user, f"/builder/{kind}").status_code == expected, (user, kind)


def test_every_record_type_exports(api, auth, world) -> None:
    kinds = ok(get(api, auth, "alpha.admin"))["record_types"]
    assert {k["key"] for k in kinds} == {"leads", "accounts", "contacts", "opportunities", "quotes",
                                         "orders", "invoices", "tickets", "tasks"}  # fmt: skip
    for kind in kinds:
        everything = ok(get(api, auth, "alpha.admin", f"/builder/{kind['key']}"))
        assert [c["key"] for c in everything["columns"]] == [c["key"] for c in kind["columns"]]


def test_exports_are_audited_but_previews_are_not(api, auth, world, db_session) -> None:
    get(api, auth, "alpha.agent1", "/builder/leads", columns=["last_name"])
    assert (
        db_session.scalars(select(AuditLog).where(AuditLog.action == "report.exported")).all() == []
    )
    assert (
        get(
            api, auth, "alpha.agent1", "/builder/leads/csv", columns=["last_name", "email"]
        ).status_code
        == 200
    )
    [entry] = db_session.scalars(select(AuditLog).where(AuditLog.action == "report.exported")).all()
    assert entry.actor_user_id == world.users["alpha.agent1"].id
    assert entry.changes["record_type"] == "leads" and entry.changes["columns"] == [
        "last_name",
        "email",
    ]
    assert "rows" in entry.changes and entry.changes["status"] is None
