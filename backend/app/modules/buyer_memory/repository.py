"""Queries of buyer memory. Every query names the tenant (and RLS checks it again)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.buyer_memory.models import BuyerMemoryItem


def rows_of_lead(
    session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID
) -> list[BuyerMemoryItem]:
    return list(
        session.scalars(
            select(BuyerMemoryItem)
            .where(BuyerMemoryItem.tenant_id == tenant_id, BuyerMemoryItem.lead_id == lead_id)
            .order_by(BuyerMemoryItem.seq)
        )
    )


def count_of_lead(session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(BuyerMemoryItem)
            .where(BuyerMemoryItem.tenant_id == tenant_id, BuyerMemoryItem.lead_id == lead_id)
        )
        or 0
    )


def get_of_lead(
    session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID, item_id: uuid.UUID
) -> BuyerMemoryItem | None:
    return session.scalar(
        select(BuyerMemoryItem).where(
            BuyerMemoryItem.tenant_id == tenant_id,
            BuyerMemoryItem.lead_id == lead_id,
            BuyerMemoryItem.id == item_id,
        )
    )


def add(session: Session, item: BuyerMemoryItem) -> BuyerMemoryItem:
    session.add(item)
    session.flush()
    return item
