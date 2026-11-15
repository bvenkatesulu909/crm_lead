"""An organisation's branding (ADR 0032, migration 0063): one row per organisation, or none (then
the defaults of ``rules.py`` apply). The logo is stored as a small clean PNG in the row itself, so
it follows the organisation's row-level security and needs no file store."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, VersionedMixin
from app.modules.branding import rules


class OrganisationBranding(VersionedMixin, Base):
    __tablename__ = "organisation_branding"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "updated_by_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("primary_color ~ '^[0-9a-f]{6}$'", name="color_format"),
        CheckConstraint(
            f"char_length(about_text) <= {rules.LIMITS['about_text']}", name="about_length"
        ),
        CheckConstraint(
            f"char_length(terms_text) <= {rules.LIMITS['terms_text']}", name="terms_length"
        ),
        CheckConstraint(
            f"char_length(contact_line) <= {rules.LIMITS['contact_line']}", name="contact_length"
        ),
        CheckConstraint(
            f"char_length(footer_line) <= {rules.LIMITS['footer_line']}", name="footer_length"
        ),
        CheckConstraint(
            "(logo_png IS NULL) = (logo_width IS NULL) "
            "AND (logo_png IS NULL) = (logo_height IS NULL)",
            name="logo_consistent",
        ),
        CheckConstraint(
            f"logo_png IS NULL OR octet_length(logo_png) <= {rules.MAX_STORED_BYTES}",
            name="logo_size",
        ),
        CheckConstraint(
            f"logo_width IS NULL OR (logo_width BETWEEN 1 AND {rules.OUTPUT_SIDE} "
            f"AND logo_height BETWEEN 1 AND {rules.OUTPUT_SIDE})",
            name="logo_dimensions",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    primary_color: Mapped[str] = mapped_column(
        String(6), server_default=text(f"'{rules.DEFAULT_COLOR}'")
    )
    about_text: Mapped[str] = mapped_column(Text, server_default=text("''"))
    terms_text: Mapped[str] = mapped_column(Text, server_default=text("''"))
    contact_line: Mapped[str] = mapped_column(
        String(rules.LIMITS["contact_line"]), server_default=text("''")
    )
    footer_line: Mapped[str] = mapped_column(
        String(rules.LIMITS["footer_line"]), server_default=text("''")
    )
    logo_png: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    logo_width: Mapped[int | None] = mapped_column(Integer, default=None)
    logo_height: Mapped[int | None] = mapped_column(Integer, default=None)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
