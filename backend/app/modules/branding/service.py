"""Branding service (ADR 0032): read and change an organisation's branding. Tenant administrators
only. Never commits; the router does. The deck renderer (a later step) reads through ``api.py``."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.modules.branding import rules
from app.modules.branding.models import OrganisationBranding
from app.modules.branding.schemas import BrandingRead, BrandingUpdate

ENTITY = "organisation_branding"
TEXT_FIELDS = ("about_text", "terms_text", "contact_line", "footer_line")


class VersionConflictError(ConflictError):
    code = "version_conflict"


class BrandingInvalidError(DomainError):
    status_code = 422
    code = "branding_invalid"

    def __init__(self, rule: rules.BrandingRuleError) -> None:
        super().__init__(str(rule))
        self.code = rule.code


class LogoTooLargeError(DomainError):
    status_code = 413
    code = "logo_too_large"


class LogoNotFoundError(NotFoundError):
    code = "logo_not_found"

    def __init__(self) -> None:
        super().__init__("This organisation has no logo.")


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None:
        raise ForbiddenError("Only members of an organisation can use branding.")
    if not principal.has_permission(Permission.BRANDING_MANAGE):
        raise ForbiddenError("Only administrators can change the branding.")
    return principal.tenant_id


def _row(
    session: Session, tenant_id: uuid.UUID, *, lock: bool = False
) -> OrganisationBranding | None:
    statement = select(OrganisationBranding).where(OrganisationBranding.tenant_id == tenant_id)
    if lock:
        statement = statement.with_for_update()
    return session.scalars(statement).one_or_none()


def _read(row: OrganisationBranding | None, cleaned: list[str] | None = None) -> BrandingRead:
    if row is None:
        return BrandingRead(
            primary_color=rules.DEFAULT_COLOR,
            about_text="",
            terms_text="",
            contact_line="",
            footer_line="",
            has_logo=False,
            logo_width=None,
            logo_height=None,
            version=0,
            updated_at=None,
        )
    return BrandingRead(
        primary_color=row.primary_color,
        about_text=row.about_text,
        terms_text=row.terms_text,
        contact_line=row.contact_line,
        footer_line=row.footer_line,
        has_logo=row.logo_png is not None,
        logo_width=row.logo_width,
        logo_height=row.logo_height,
        version=row.version,
        updated_at=row.updated_at,
        cleaned_fields=cleaned or [],
    )


def get_branding(session: Session, principal: Principal) -> BrandingRead:
    return _read(_row(session, _tenant(principal)))


def update_branding(session: Session, principal: Principal, data: BrandingUpdate) -> BrandingRead:
    tenant_id = _tenant(principal)
    try:
        color = rules.check_color(data.primary_color)
        texts = {field: rules.clean_text(field, getattr(data, field)) for field in TEXT_FIELDS}
    except rules.BrandingRuleError as rule:
        raise BrandingInvalidError(rule) from None
    row = _row(session, tenant_id, lock=True)
    if data.version != (row.version if row else 0):
        raise VersionConflictError("The branding was changed by someone else. Reload it.")
    if row is None:
        row = OrganisationBranding(tenant_id=tenant_id)
        session.add(row)
        old = {"primary_color": rules.DEFAULT_COLOR, **dict.fromkeys(TEXT_FIELDS, "")}
    else:
        old = {"primary_color": row.primary_color, **{f: getattr(row, f) for f in TEXT_FIELDS}}
    new = {"primary_color": color, **{f: texts[f].text for f in TEXT_FIELDS}}
    changed = sorted(name for name in new if new[name] != old[name])
    row.primary_color = color
    for field in TEXT_FIELDS:
        setattr(row, field, texts[field].text)
    row.updated_by_user_id = principal.user_id
    # Field NAMES only: the texts are the organisation's own words, but the audit trail keeps ids.
    record_audit(
        session,
        principal,
        action="branding.updated",
        entity_type=ENTITY,
        entity_id=tenant_id,
        changes={"fields": changed},
    )
    try:
        session.flush()
    except StaleDataError:
        raise VersionConflictError("The branding was changed by someone else. Reload it.") from None
    session.refresh(row)
    return _read(row, sorted(f for f in TEXT_FIELDS if texts[f].cleaned))


def set_logo(session: Session, principal: Principal, data: bytes) -> BrandingRead:
    tenant_id = _tenant(principal)
    if len(data) > rules.MAX_UPLOAD_BYTES:
        raise LogoTooLargeError("The logo can be at most 1 MB.")
    try:
        logo = rules.reencode_logo(data)
    except rules.BrandingRuleError as rule:
        raise BrandingInvalidError(rule) from None
    row = _row(session, tenant_id, lock=True)
    if row is None:
        row = OrganisationBranding(tenant_id=tenant_id)
        session.add(row)
    row.logo_png, row.logo_width, row.logo_height = logo.png, logo.width, logo.height
    row.updated_by_user_id = principal.user_id
    record_audit(
        session,
        principal,
        action="branding.logo_set",
        entity_type=ENTITY,
        entity_id=tenant_id,
        changes={"width": logo.width, "height": logo.height, "bytes": len(logo.png)},
    )
    session.flush()
    session.refresh(row)
    return _read(row)


def remove_logo(session: Session, principal: Principal) -> BrandingRead:
    tenant_id = _tenant(principal)
    row = _row(session, tenant_id, lock=True)
    if row is None or row.logo_png is None:
        raise LogoNotFoundError()
    row.logo_png = row.logo_width = row.logo_height = None
    row.updated_by_user_id = principal.user_id
    record_audit(
        session,
        principal,
        action="branding.logo_removed",
        entity_type=ENTITY,
        entity_id=tenant_id,
        changes={},
    )
    session.flush()
    session.refresh(row)
    return _read(row)


def logo_png(session: Session, principal: Principal) -> bytes:
    row = _row(session, _tenant(principal))
    if row is None or row.logo_png is None:
        raise LogoNotFoundError()
    return row.logo_png
