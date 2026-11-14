"""An approved "why this proposal" text for a quote's deck (ADR 0032 Amendment A, PD7).

One row per approval: the quote, the text, who approved it and which proposal in the approval queue
it came from. Insert-only: the database refuses to change a row and to delete one younger than 365
days (migration 0066). The newest row of a quote is the one the next deck shows.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Identity,
    Index,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TenantOwnedMixin, UUIDPrimaryKeyMixin

BODY_MAX = 1000


class DeckSummary(UUIDPrimaryKeyMixin, TenantOwnedMixin, Base):
    __tablename__ = "deck_summaries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"], ["quotes.tenant_id", "quotes.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "approved_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["agent_actions.tenant_id", "agent_actions.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"char_length(body) BETWEEN 1 AND {BODY_MAX}", name="body_length"),
        Index("ix_deck_summaries_tenant_id_quote_id", "tenant_id", "quote_id", "seq"),
    )

    # Newest first: rows written in one transaction share created_at.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    quote_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    approved_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    body: Mapped[str] = mapped_column(Text)
