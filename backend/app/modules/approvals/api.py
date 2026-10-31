"""Public interface of the approvals module (ADR 0014). Other modules import only this."""

from app.modules.approvals.sentinel import Limits as SentinelLimits
from app.modules.approvals.service import (
    LimitReachedError,
    ProposalBlockedError,
    action_brief,
    audit_blocked,
    describe,
    expire_due,
    propose,
    propose_external,
    requester_of,
)

__all__ = [
    "LimitReachedError",
    "ProposalBlockedError",
    "SentinelLimits",
    "action_brief",
    "audit_blocked",
    "describe",
    "expire_due",
    "propose",
    "propose_external",
    "requester_of",
]
