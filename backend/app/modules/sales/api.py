"""Public interface of the sales module. Other modules import only from here."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.reporting import Cell, Column, ExportFilters, ExportSpec, export_rows
from app.modules.sales import repository
from app.modules.sales.metrics import (
    PipelineMetrics,
    StageFigures,
    open_pipeline_by_owner,
    pipeline_metrics,
    win_loss_table,
)
from app.modules.sales.models import (
    OPEN_STAGES,
    OPPORTUNITY_STAGES,
    Opportunity,
    OpportunityStageChange,
)
from app.modules.sales.policies import readable_opportunities

__all__ = [
    "win_loss_table",
    "EXPORT",
    "export_table",
    "PipelineMetrics",
    "StageFigures",
    "create_opportunity",
    "opportunity_account_id",
    "is_readable_opportunity",
    "open_pipeline_by_owner",
    "opportunity_ids_by_account",
    "owned_opportunity_ids",
    "pipeline_metrics",
    "transfer_open_opportunities",
    "won_deals_by_account",
]


def create_opportunity(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    name: str,
    account_id: uuid.UUID,
    primary_contact_id: uuid.UUID | None,
    owner_id: uuid.UUID | None,
    amount: Decimal | None,
    currency: str,
    expected_close_date: date | None,
    created_by_user_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert an opportunity in the caller's transaction (used by lead conversion).
    Authorization is the caller's job; composite foreign keys guarantee account, contact and
    owner belong to the same tenant. The first stage-history entry is written too."""
    opportunity = Opportunity(
        tenant_id=tenant_id,
        name=name,
        account_id=account_id,
        primary_contact_id=primary_contact_id,
        owner_id=owner_id,
        amount=amount,
        currency=currency,
        expected_close_date=expected_close_date,
    )
    session.add(opportunity)
    session.flush()
    session.add(
        OpportunityStageChange(
            tenant_id=tenant_id,
            opportunity_id=opportunity.id,
            from_stage=None,
            to_stage="prospecting",
            note="Created from a converted lead",
            changed_by_user_id=created_by_user_id,
        )
    )
    session.flush()
    return opportunity.id


def is_readable_opportunity(session: Session, principal: Principal, opp_id: uuid.UUID) -> bool:
    return repository.get_readable(session, principal, opp_id) is not None


def owned_opportunity_ids(principal: Principal) -> Select[uuid.UUID]:
    """Subquery: IDs of the (not deleted) opportunities this user owns in their tenant."""
    return select(Opportunity.id).where(
        Opportunity.tenant_id == principal.tenant_id,
        Opportunity.owner_id == principal.user_id,
        Opportunity.deleted_at.is_(None),
    )


def opportunity_ids_by_account(
    session: Session, tenant_id: uuid.UUID, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """IDs of the (not deleted) deals of each account."""
    result: dict[uuid.UUID, list[uuid.UUID]] = {a: [] for a in account_ids}
    if account_ids:
        rows = session.execute(
            select(Opportunity.id, Opportunity.account_id).where(
                Opportunity.tenant_id == tenant_id,
                Opportunity.account_id.in_(account_ids),
                Opportunity.deleted_at.is_(None),
            )
        )
        for opp_id, account_id in rows:
            result[account_id].append(opp_id)
    return result


def won_deals_by_account(
    session: Session, tenant_id: uuid.UUID, account_ids: list[uuid.UUID], since: datetime
) -> dict[uuid.UUID, int]:
    """Number of deals won since ``since``, per account."""
    if not account_ids:
        return {}
    rows = session.execute(
        select(Opportunity.account_id, func.count())
        .where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.account_id.in_(account_ids),
            Opportunity.stage == "closed_won",
            Opportunity.closed_at >= since,
        )
        .group_by(Opportunity.account_id)
    ).all()
    return {account: count for account, count in rows}


def transfer_open_opportunities(
    session: Session,
    principal: Principal,
    account_id: uuid.UUID,
    from_owner: uuid.UUID | None,
    to_owner: uuid.UUID,
) -> list[uuid.UUID]:
    """Give the account's OPEN deals of the previous owner to the new owner. Closed deals keep
    the person who won or lost them. Each change is audited."""
    owned_by_previous = (
        Opportunity.owner_id.is_(None) if from_owner is None else Opportunity.owner_id == from_owner
    )
    deals = session.scalars(
        select(Opportunity)
        .where(
            Opportunity.tenant_id == principal.tenant_id,
            Opportunity.account_id == account_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.stage.in_(OPEN_STAGES),
            owned_by_previous,
        )
        .with_for_update()
    ).all()
    for deal in deals:
        deal.owner_id = to_owner
        record_audit(
            session,
            principal,
            action="opportunity.updated",
            entity_type="opportunity",
            entity_id=deal.id,
            changes={
                "owner_id": {"old": from_owner, "new": to_owner},
                "reason": "Account transfer",
            },
        )
    session.flush()
    return [d.id for d in deals]


def opportunity_account_id(
    session: Session, principal: Principal, opp_id: uuid.UUID
) -> tuple[bool, uuid.UUID | None]:
    """(visible?, account of the deal). Deals the user may not see give (False, None)."""
    opp = repository.get_readable(session, principal, opp_id)
    return (False, None) if opp is None else (True, opp.account_id)


# Report builder (Phase 18): the columns that may be exported - never internal notes - and the
# statuses to filter by. Rows always pass through this module's own record-level policy.
EXPORT = ExportSpec(
    columns=(
        Column("created_at", "Created", "datetime"),
        Column("name", "Name", "text"),
        Column("account_id", "Account", "account"),
        Column("stage", "Stage", "text"),
        Column("amount", "Amount", "money"),
        Column("currency", "Currency", "text"),
        Column("expected_close_date", "Expected close", "date"),
        Column("closed_at", "Closed", "datetime"),
        Column("lost_reason", "Lost reason", "text"),
        Column("owner_id", "Owner", "user"),
    ),
    statuses=OPPORTUNITY_STAGES,
)


def export_table(
    session: Session, principal: Principal, filters: ExportFilters, wanted: list[str]
) -> list[dict[str, Cell]]:
    allowed = {c.key for c in EXPORT.columns}
    if not wanted or not set(wanted) <= allowed:
        raise ValueError("unknown export column")
    return export_rows(
        session,
        entity=Opportunity,
        columns={key: getattr(Opportunity, key) for key in allowed},
        wanted=wanted,
        condition=readable_opportunities(principal),
        created=Opportunity.created_at,
        owner=Opportunity.owner_id,
        status=Opportunity.stage,
        filters=filters,
    )
