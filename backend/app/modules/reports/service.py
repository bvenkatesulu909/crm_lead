"""Reports (Phase 18). Each figure comes from the owning module's api.py, computed with that
module's own record-level policy - a report can never show more than the module's screens.

- Standard reports: sales win rate, lead conversion, revenue & quotes, support SLA.
- Report builder: a list of one record type with chosen columns and filters.
- CSV: the same data as the screen; builder exports are audited (who exported what).
"""

import csv
import io
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import DomainError, ForbiddenError, NotFoundError
from app.core.reporting import Cell, Column, ExportFilters, ExportSpec, Filters, Period, Table
from app.modules.accounts import api as accounts_api
from app.modules.activities import api as activities_api
from app.modules.contacts import api as contacts_api
from app.modules.identity import api as identity_api
from app.modules.invoices import api as invoices_api
from app.modules.leads import api as leads_api
from app.modules.orders import api as orders_api
from app.modules.quotes import api as quotes_api
from app.modules.reports.schemas import (
    ColumnOut,
    RecordTypeInfo,
    ReportCatalogue,
    ReportInfo,
    ReportOut,
    TableOut,
)
from app.modules.sales import api as sales_api
from app.modules.support import api as support_api

P = Permission
PREVIEW_ROWS = 200
CSV_ROWS = 5000
MAX_DAYS = 3 * 366


class ReportNotFoundError(NotFoundError):
    code = "report_not_found"


class InvalidReportFilterError(DomainError):
    status_code = 422
    code = "invalid_report_filter"


# --- what exists, and who may use it -----------------------------------------------------

Section = tuple[frozenset[Permission], Callable[[Session, Principal, Filters], Table]]


@dataclass(frozen=True)
class ReportDef:
    title: str
    description: str
    sections: tuple[Section, ...]


def _any(*permissions: Permission) -> frozenset[Permission]:
    return frozenset(permissions)


SALES_ALL_OR_OWN = _any(P.DASHBOARD_SALES_ALL, P.DASHBOARD_SALES_OWN)
REPORTS: dict[str, ReportDef] = {
    "sales": ReportDef(
        "Sales: win rate",
        "Deals won and lost in the period, win rate and deal values per sales rep.",
        ((SALES_ALL_OR_OWN, sales_api.win_loss_table),),
    ),
    "leads": ReportDef(
        "Leads: conversion",
        "Leads created in the period by source, and how many were converted.",
        ((SALES_ALL_OR_OWN, leads_api.conversion_table),),
    ),
    "revenue": ReportDef(
        "Revenue & quotes",
        "Invoiced and paid per month, orders per month, and quote acceptance per sales rep.",
        (
            (
                _any(P.INVOICE_READ_ALL, P.INVOICE_READ_OWN_ACCOUNTS),
                invoices_api.revenue_by_month_table,
            ),
            (_any(P.ORDER_READ_ALL, P.ORDER_READ_OWN_ACCOUNTS), orders_api.orders_by_month_table),
            (_any(P.QUOTE_READ_ALL, P.QUOTE_READ_OWN), quotes_api.quote_table),
        ),
    ),
    "support": ReportDef(
        "Support: SLA & satisfaction",
        "Tickets created and resolved, resolved on time, overdue now and ratings.",
        (
            (_any(P.TICKET_READ_ALL, P.TICKET_READ_OWN_ACCOUNTS),
             lambda s, p, f: support_api.sla_table(s, p, f, by="priority")),
            (_any(P.TICKET_READ_ALL, P.TICKET_READ_OWN_ACCOUNTS),
             lambda s, p, f: support_api.sla_table(s, p, f, by="category")),
        ),
    ),
}  # fmt: skip


@dataclass(frozen=True)
class RecordType:
    label: str
    permissions: frozenset[Permission]
    spec: ExportSpec
    export: Callable[[Session, Principal, ExportFilters, list[str]], list[dict[str, Cell]]]


def _type(label: str, permissions: frozenset[Permission], module: Any) -> RecordType:
    return RecordType(label, permissions, module.EXPORT, module.export_table)


RECORD_TYPES: dict[str, RecordType] = {
    "leads": _type("Leads", _any(P.LEAD_READ_ALL, P.LEAD_READ_OWN), leads_api),
    "accounts": _type("Accounts", _any(P.ACCOUNT_READ_ALL, P.ACCOUNT_READ_OWN), accounts_api),
    "contacts": _type("Contacts", _any(P.CONTACT_READ_ALL, P.CONTACT_READ_OWN), contacts_api),
    "opportunities": _type(
        "Deals", _any(P.OPPORTUNITY_READ_ALL, P.OPPORTUNITY_READ_OWN), sales_api
    ),
    "quotes": _type("Quotes", _any(P.QUOTE_READ_ALL, P.QUOTE_READ_OWN), quotes_api),
    "orders": _type("Orders", _any(P.ORDER_READ_ALL, P.ORDER_READ_OWN_ACCOUNTS), orders_api),
    "invoices": _type(
        "Invoices", _any(P.INVOICE_READ_ALL, P.INVOICE_READ_OWN_ACCOUNTS), invoices_api
    ),
    "tickets": _type("Tickets", _any(P.TICKET_READ_ALL, P.TICKET_READ_OWN_ACCOUNTS), support_api),
    "tasks": _type(
        "Tasks & activities", _any(P.ACTIVITY_READ_ALL, P.ACTIVITY_READ_OWN), activities_api
    ),
}
# fmt: skip


def _allowed(principal: Principal, permissions: frozenset[Permission]) -> bool:
    return principal.user_type == "staff" and bool(permissions & principal.permissions)


def catalogue(principal: Principal) -> ReportCatalogue:
    reports = [
        ReportInfo(key=k, title=r.title, description=r.description)
        for k, r in REPORTS.items()
        if any(_allowed(principal, perms) for perms, _ in r.sections)
    ]
    types = [
        RecordTypeInfo(
            key=k,
            label=t.label,
            columns=[ColumnOut(key=c.key, label=c.label, kind=c.kind) for c in t.spec.columns],
            statuses=list(t.spec.statuses),
        )
        for k, t in RECORD_TYPES.items()
        if _allowed(principal, t.permissions)
    ]
    return ReportCatalogue(
        reports=reports,
        record_types=types,
        can_filter_by_rep=principal.has_permission(P.DASHBOARD_SALES_ALL),
    )


# --- filters ---------------------------------------------------------------------------


def period_of(start: date | None, end: date | None) -> Period:
    today = datetime.now(UTC).date()
    end = end or today
    start = start or end - timedelta(days=29)
    if start > end:
        raise InvalidReportFilterError("The start date must be before the end date.")
    if (end - start).days > MAX_DAYS:
        raise InvalidReportFilterError("Choose a period of at most three years.")
    return Period(start, end)


def _check_owner_filter(principal: Principal, owner_id: uuid.UUID | None) -> None:
    # Choosing someone else's figures is for people who may see everyone's (managers, admins).
    if (
        owner_id is not None
        and owner_id != principal.user_id
        and not principal.has_permission(P.DASHBOARD_SALES_ALL)
    ):
        raise ForbiddenError("You can only see your own figures.")


# --- turning tables into screen values / CSV -----------------------------------------------


def _names(
    session: Session, principal: Principal, tables: Sequence[Table]
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, str]]:
    users: set[uuid.UUID] = set()
    accounts: set[uuid.UUID] = set()
    for table in tables:
        for col in table.columns:
            target = users if col.kind == "user" else accounts if col.kind == "account" else None
            if target is not None:
                target |= {r[col.key] for r in table.rows if isinstance(r.get(col.key), uuid.UUID)}  # type: ignore[misc]
    tenant = principal.tenant_id
    assert tenant is not None  # noqa: S101 - staff always belong to a tenant
    people = {k: v[0] for k, v in identity_api.people_by_id(session, tenant, users).items()}
    return people, accounts_api.account_names(session, tenant, accounts)


def _text(
    value: Cell, col: Column, people: dict[uuid.UUID, str], accounts: dict[uuid.UUID, str]
) -> str | int | None:
    if value is None:
        return None
    if col.kind == "user" and isinstance(value, uuid.UUID):
        return people.get(value, "Former colleague")
    if col.kind == "account" and isinstance(value, uuid.UUID):
        return accounts.get(value, "Account")
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return str(value)


def _out(tables: Sequence[Table], session: Session, principal: Principal) -> list[TableOut]:
    people, accounts = _names(session, principal, tables)
    return [
        TableOut(
            title=t.title,
            columns=[ColumnOut(key=c.key, label=c.label, kind=c.kind) for c in t.columns],
            rows=[
                {c.key: _text(r.get(c.key), c, people, accounts) for c in t.columns} for r in t.rows
            ],
        )
        for t in tables
    ]


FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value: str | int | None, kind: str) -> str:
    """Spreadsheets run cells starting with =, +, -, @ as formulas. Text cells get a leading
    apostrophe so a name like "=HYPERLINK(...)" is shown as text, never executed."""
    if value is None:
        return ""
    text = str(value)
    if kind in ("number", "money", "percent") and isinstance(value, int | str):
        return text
    return "'" + text if text.startswith(FORMULA_START) else text


def to_csv(tables: Sequence[TableOut]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    for i, table in enumerate(tables):
        if len(tables) > 1:
            if i:
                writer.writerow([])
            writer.writerow([table.title])
        writer.writerow([c.label for c in table.columns])
        for row in table.rows:
            writer.writerow([_safe_cell(row.get(c.key), c.kind) for c in table.columns])
    return ("﻿" + out.getvalue()).encode("utf-8")  # BOM: Excel reads it as UTF-8


# --- standard reports ----------------------------------------------------------------------


def run_report(
    session: Session,
    principal: Principal,
    key: str,
    *,
    start: date | None,
    end: date | None,
    owner_id: uuid.UUID | None,
) -> ReportOut:
    report = REPORTS.get(key)
    sections = [fn for perms, fn in report.sections if _allowed(principal, perms)] if report else []
    if report is None or not sections:
        raise ReportNotFoundError("This report doesn't exist or isn't available to you.")
    _check_owner_filter(principal, owner_id)
    period = period_of(start, end)
    filters = Filters(period=period, owner_id=owner_id)
    tables = [fn(session, principal, filters) for fn in sections]
    return ReportOut(key=key, title=report.title, start=period.start_date, end=period.end_date,
                     sections=_out(tables, session, principal))  # fmt: skip


# --- report builder -------------------------------------------------------------------------


def run_builder(
    session: Session,
    principal: Principal,
    record_type: str,
    *,
    columns: list[str],
    start: date | None,
    end: date | None,
    owner_id: uuid.UUID | None,
    status: str | None,
    limit: int,
    export: bool,
) -> TableOut:
    kind = RECORD_TYPES.get(record_type)
    if kind is None or not _allowed(principal, kind.permissions):
        raise ReportNotFoundError("This record type doesn't exist or isn't available to you.")
    allowed = [c for c in kind.spec.columns]
    wanted = [c for c in dict.fromkeys(columns)] or [c.key for c in allowed]
    unknown = set(wanted) - {c.key for c in allowed}
    if unknown:
        raise InvalidReportFilterError(f"Unknown column(s): {', '.join(sorted(unknown))}.")
    if status is not None and status not in kind.spec.statuses:
        raise InvalidReportFilterError("Choose a status from the list.")
    _check_owner_filter(principal, owner_id)
    period = period_of(start, end) if (start or end) else None
    filters = ExportFilters(period=period, owner_id=owner_id, status=status, limit=limit)
    rows = kind.export(session, principal, filters, wanted)
    chosen = tuple(c for c in allowed if c.key in wanted)
    if export:
        # Exports leave the CRM (often with personal data): record who took what.
        record_audit(session, principal, action="report.exported", entity_type="report",
                     entity_id=uuid.uuid4(), changes={
                         "record_type": record_type, "columns": wanted, "rows": len(rows),
                         "status": status, "owner_id": owner_id,
                         "period": [period.start_date, period.end_date] if period else None,
                     })  # fmt: skip
    [table] = _out([Table(kind.label, chosen, rows)], session, principal)
    return table
