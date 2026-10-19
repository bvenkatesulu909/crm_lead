"""Ticket status flow and SLA (service-level agreement) rules. Pure functions, unit-tested.

Status flow:
    new ──► open ◄──► pending_customer        (waiting for the customer's reply)
     │       │              │
     └───────┴──────────────┴──► resolved ──► closed   (closed is final)
                                    │
                                    └──► open   (customer says it isn't fixed)
Any open state may also go straight to closed (e.g. spam, duplicate).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.core.errors import ConflictError

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"open", "pending_customer", "resolved", "closed"}),
    "open": frozenset({"pending_customer", "resolved", "closed"}),
    "pending_customer": frozenset({"open", "resolved", "closed"}),
    "resolved": frozenset({"open", "closed"}),
    "closed": frozenset(),
}


class InvalidTicketTransitionError(ConflictError):
    code = "invalid_status_transition"


def check_transition(current: str, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidTicketTransitionError(f"A ticket cannot go from '{current}' to '{target}'.")


@dataclass(frozen=True)
class SlaTargets:
    first_response: timedelta
    resolution: timedelta


# Default targets per priority. (A per-tenant SLA configuration can replace this later.)
SLA_BY_PRIORITY: dict[str, SlaTargets] = {
    "urgent": SlaTargets(timedelta(hours=1), timedelta(hours=8)),
    "high": SlaTargets(timedelta(hours=4), timedelta(hours=24)),
    "normal": SlaTargets(timedelta(hours=8), timedelta(hours=72)),
    "low": SlaTargets(timedelta(hours=24), timedelta(hours=120)),
}

SlaState = Literal["on_track", "at_risk", "breached", "met"]
AT_RISK_SHARE = 0.25  # "at risk" when less than a quarter of the time is left


def due_times(priority: str, created_at: datetime) -> tuple[datetime, datetime]:
    targets = SLA_BY_PRIORITY[priority]
    return created_at + targets.first_response, created_at + targets.resolution


def sla_state(
    *,
    status: str,
    now: datetime,
    created_at: datetime,
    first_response_due_at: datetime,
    resolution_due_at: datetime,
    first_responded_at: datetime | None,
    resolved_at: datetime | None,
) -> SlaState:
    """How the ticket stands against its SLA right now."""
    if status in ("resolved", "closed"):
        done = resolved_at or now
        late_response = (
            first_responded_at is not None and first_responded_at > first_response_due_at
        )
        return "breached" if done > resolution_due_at or late_response else "met"

    if now > resolution_due_at:
        return "breached"
    if first_responded_at is None and now > first_response_due_at:
        return "breached"
    if first_responded_at is not None and first_responded_at > first_response_due_at:
        return "breached"

    # Which deadline is next: the first response (if not given yet) or the resolution.
    deadline = first_response_due_at if first_responded_at is None else resolution_due_at
    window = (deadline - created_at).total_seconds()
    remaining = (deadline - now).total_seconds()
    return "at_risk" if window > 0 and remaining / window < AT_RISK_SHARE else "on_track"
