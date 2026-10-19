"""Unit tests for ticket status flow, SLA calculation and ticket permissions (no database)."""

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from app.core.auth.rbac import Permission, Role, permissions_for
from app.modules.support.rules import (
    ALLOWED_TRANSITIONS,
    InvalidTicketTransitionError,
    check_transition,
    due_times,
    sla_state,
)

STATUSES = ["new", "open", "pending_customer", "resolved", "closed"]
T0 = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(("current", "target"), list(itertools.product(STATUSES, STATUSES)))
def test_transitions_follow_the_table(current: str, target: str) -> None:
    if target in ALLOWED_TRANSITIONS[current]:
        check_transition(current, target)
    else:
        with pytest.raises(InvalidTicketTransitionError):
            check_transition(current, target)


def test_closed_is_final_and_resolved_can_reopen() -> None:
    assert ALLOWED_TRANSITIONS["closed"] == frozenset()
    assert "open" in ALLOWED_TRANSITIONS["resolved"]


@pytest.mark.parametrize(
    ("priority", "first", "resolution"),
    [("urgent", 1, 8), ("high", 4, 24), ("normal", 8, 72), ("low", 24, 120)],
)
def test_due_times_per_priority(priority: str, first: int, resolution: int) -> None:
    assert due_times(priority, T0) == (
        T0 + timedelta(hours=first),
        T0 + timedelta(hours=resolution),
    )


def state(now_hours: float, **overrides: object) -> str:
    first_due, resolution_due = due_times("normal", T0)  # 8 h / 72 h
    values: dict[str, object] = {
        "status": "open",
        "now": T0 + timedelta(hours=now_hours),
        "created_at": T0,
        "first_response_due_at": first_due,
        "resolution_due_at": resolution_due,
        "first_responded_at": None,
        "resolved_at": None,
    }
    values.update(overrides)
    return sla_state(**values)  # type: ignore[arg-type]


def test_sla_on_track_at_risk_and_breached_before_first_response() -> None:
    assert state(1) == "on_track"
    assert state(6.5) == "at_risk"  # < 25 % of the 8 h left
    assert state(9) == "breached"  # first response is overdue


def test_sla_after_timely_first_response_tracks_resolution() -> None:
    responded = T0 + timedelta(hours=2)
    assert state(9, first_responded_at=responded) == "on_track"
    assert state(60, first_responded_at=responded) == "at_risk"
    assert state(73, first_responded_at=responded) == "breached"


def test_sla_late_first_response_stays_breached() -> None:
    assert state(10, first_responded_at=T0 + timedelta(hours=9)) == "breached"


def test_sla_for_finished_tickets() -> None:
    responded = T0 + timedelta(hours=1)
    met = state(
        100, status="resolved", first_responded_at=responded, resolved_at=T0 + timedelta(hours=20)
    )
    late = state(
        100, status="closed", first_responded_at=responded, resolved_at=T0 + timedelta(hours=80)
    )
    assert (met, late) == ("met", "breached")


TICKET_PERMISSIONS = {p for p in Permission if "ticket" in p.value}


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.SUPPORT_AGENT, {Permission.TICKET_READ_ALL, Permission.TICKET_MANAGE}),
        (Role.TENANT_ADMIN, {Permission.TICKET_READ_ALL, Permission.TICKET_MANAGE}),
        (Role.SALES_MANAGER, {Permission.TICKET_READ_ALL}),
        (Role.SALES_AGENT, {Permission.TICKET_READ_OWN_ACCOUNTS}),
        (Role.CUSTOMER, {Permission.PORTAL_TICKET_READ, Permission.PORTAL_TICKET_WRITE}),
        (Role.SUPER_ADMIN, set()),
    ],
)
def test_ticket_permissions_per_role(role: Role, expected: set[Permission]) -> None:
    assert permissions_for(frozenset({role})) & TICKET_PERMISSIONS == expected
