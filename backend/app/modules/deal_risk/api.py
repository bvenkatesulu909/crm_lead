"""The deal risk forecast as other modules and the worker may use it (ADR 0037)."""

from app.modules.deal_risk.coach import AdviceInvalidError, CoachRateLimitedError, run_coach
from app.modules.deal_risk.service import (
    DealRiskNotAllowedError,
    NotComputedError,
    RateLimitedError,
    compute,
    delete_expired,
    history,
    latest_snapshot,
    list_latest,
    per_user_hour,
    run_nightly,
    snapshot_on_demand,
)
from app.modules.deal_risk.signals import DealNotFoundError

__all__ = [
    "AdviceInvalidError",
    "CoachRateLimitedError",
    "run_coach",
    "DealNotFoundError",
    "DealRiskNotAllowedError",
    "NotComputedError",
    "RateLimitedError",
    "compute",
    "delete_expired",
    "history",
    "list_latest",
    "per_user_hour",
    "latest_snapshot",
    "run_nightly",
    "snapshot_on_demand",
]
