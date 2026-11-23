"""Computing and storing deal risk (ADR 0037, DR2).

``compute`` works the risk out and stores nothing. ``snapshot_on_demand`` is for a person
(permission ``deal_risk:read`` plus the deal's own read rules); ``run_nightly`` walks the open deals
of one organisation as its Automation identity and stores one snapshot per deal per day. Both are
safe to run twice. Nothing here calls a model.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ForbiddenError
from app.modules.deal_risk import repository, signals
from app.modules.deal_risk.models import DealRiskSnapshot
from app.modules.deal_risk.rules import Risk, assess
from app.modules.identity import api as identity_api
from app.modules.sales import api as sales_api

RETENTION = timedelta(days=365)
# The nightly pass is idempotent over this window: a deal already snapshotted by the nightly job
# in the last 20 hours is skipped, so the worker may call it every minute.
NIGHTLY_WINDOW = timedelta(hours=20)


class DealRiskNotAllowedError(ForbiddenError):
    code = "deal_risk_not_allowed"

    def __init__(self) -> None:
        super().__init__("You may not see deal risk.")


def _require(principal: Principal) -> uuid.UUID:
    """Permission and organisation: the caller's tenant id, else not allowed."""
    if principal.tenant_id is None or not principal.has_permission(Permission.DEAL_RISK_READ):
        raise DealRiskNotAllowedError
    return principal.tenant_id


def compute(
    session: Session,
    principal: Principal,
    opp_id: uuid.UUID,
    now: datetime,
    history: sales_api.WonHistory | None = None,
) -> Risk:
    """The risk of an open deal this person may read; stores nothing."""
    won = history if history is not None else sales_api.won_history(session, principal)
    return assess(signals.gather(session, principal, opp_id, now, won))


def _store(
    session: Session,
    principal: Principal,
    opp_id: uuid.UUID,
    risk: Risk,
    *,
    source: str,
    requested_by: uuid.UUID | None,
) -> DealRiskSnapshot:
    tenant_id = principal.tenant_id
    if tenant_id is None:
        raise DealRiskNotAllowedError
    return repository.add(
        session,
        DealRiskSnapshot(
            tenant_id=tenant_id,
            opportunity_id=opp_id,
            level=risk.level,
            score=risk.score,
            rules_version=risk.rules_version,
            source=source,
            requested_by_user_id=requested_by,
            factors=[
                {"code": f.code, "sentence": f.sentence, "points": f.points, "source": f.source}
                for f in risk.factors
            ],
            unknown=list(risk.unknown),
        ),
    )


def snapshot_on_demand(
    session: Session, principal: Principal, opp_id: uuid.UUID, now: datetime
) -> DealRiskSnapshot:
    _require(principal)
    risk = compute(session, principal, opp_id, now)  # 404 when not readable or not open
    snapshot = _store(
        session, principal, opp_id, risk, source="on_demand", requested_by=principal.user_id
    )
    record_audit(
        session,
        principal,
        action="deal_risk.computed",
        entity_type="opportunity",
        entity_id=opp_id,
        changes={"level": risk.level, "score": risk.score, "factors": len(risk.factors)},
    )
    return snapshot


def latest_snapshot(
    session: Session, principal: Principal, opp_id: uuid.UUID
) -> DealRiskSnapshot | None:
    """The newest stored snapshot of a deal this person may read (else not found)."""
    tenant_id = _require(principal)
    if not sales_api.is_readable_opportunity(session, principal, opp_id):
        raise signals.DealNotFoundError
    return repository.latest(session, tenant_id, opp_id)


def run_nightly(session: Session, now: datetime, *, tenant_id: uuid.UUID) -> int:
    """One snapshot per open deal of the organisation, as its Automation identity.

    The caller has bound the tenant. A deal that fails (for example an account that cannot be
    read) is skipped and the rest go on; each deal runs in its own savepoint."""
    since = now - NIGHTLY_WINDOW
    done_today = repository.nightly_done_for(session, tenant_id, since)
    robot = identity_api.automation_principal(session, tenant_id)
    identity_api.bind_reader(session, robot)
    deals = [d for d in sales_api.open_deal_ids(session, robot) if d not in done_today]
    if not deals:
        return 0
    history = sales_api.won_history(session, robot)
    stored = 0
    for opp_id in deals:
        try:
            with session.begin_nested():
                risk = compute(session, robot, opp_id, now, history)
                _store(session, robot, opp_id, risk, source="nightly", requested_by=None)
            stored += 1
        except signals.DealNotFoundError:
            continue
    return stored


def delete_expired(session: Session, now: datetime, *, tenant_id: uuid.UUID) -> int:
    """Delete snapshots older than the retention (the worker, per organisation)."""
    return repository.delete_older_than(session, tenant_id, now - RETENTION)
