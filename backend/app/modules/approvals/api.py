"""Public interface of the approvals module (ADR 0014). Other modules import only this."""

from app.modules.approvals.metrics import qualifier_suggestions_table
from app.modules.approvals.sentinel import Limits as SentinelLimits
from app.modules.approvals.service import (
    InvalidActionError,
    LimitReachedError,
    ProposalBlockedError,
    action_brief,
    audit_blocked,
    deciders_for_notice,
    describe,
    expire_due,
    follow_up_drafts_today,
    follow_up_history,
    follow_up_waiting_for,
    propose,
    propose_external,
    requester_of,
)

__all__ = [
    "InvalidActionError",
    "LimitReachedError",
    "ProposalBlockedError",
    "SentinelLimits",
    "action_brief",
    "audit_blocked",
    "deciders_for_notice",
    "describe",
    "expire_due",
    "follow_up_drafts_today",
    "follow_up_history",
    "follow_up_waiting_for",
    "propose",
    "propose_external",
    "qualifier_suggestions_table",
    "requester_of",
]
