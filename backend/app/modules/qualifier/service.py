"""The qualification procedure: the organisation's written steps (docs/qualifier.md, QA1).

An administrator writes the steps; every save is a NEW version and retires the previous active
one (history is kept). The steps are untrusted text that will later sit in a model's prompt, so
they are cleaned like any such text (``app.core.screening``): hidden characters, markup, links
and addresses come out; a step that reads like an instruction to an AI is refused. The text is
data, never code: it cannot add tools or widen anything. Services never commit; the caller does.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.screening import (
    ADDRESS_PLACEHOLDER,
    IMAGE_PLACEHOLDER,
    LINK_PLACEHOLDER,
    REPEAT_PLACEHOLDER,
    screen,
)
from app.modules.qualifier import repository
from app.modules.qualifier.models import (
    MAX_NAME_CHARS,
    MAX_STEP_CHARS,
    MAX_STEPS,
    MAX_TOTAL_CHARS,
    MIN_STEP_CHARS,
    QualificationProcedure,
)

_MARKERS = (LINK_PLACEHOLDER, IMAGE_PLACEHOLDER, ADDRESS_PLACEHOLDER, REPEAT_PLACEHOLDER)


def _meaningful(text: str) -> str:
    """The step without the markers that cleaning leaves behind: a step that was only a link or
    an address says nothing and must not pass as a rule."""
    for marker in _MARKERS:
        text = text.replace(marker, "")
    return " ".join(text.split())


class InvalidProcedureError(DomainError):
    status_code = 422
    code = "invalid_qualification_procedure"


class NoActiveProcedureError(NotFoundError):
    code = "no_active_qualification_procedure"

    def __init__(self) -> None:
        super().__init__("No qualification procedure has been written yet.")


class ProcedureVersionConflictError(ConflictError):
    code = "qualification_procedure_changed"

    def __init__(self) -> None:
        super().__init__(
            "The procedure was changed by someone else. Reload it and try again.",
        )


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.tenant_id is None:
        raise ValueError("a tenant is required")
    return principal.tenant_id


def _clean_name(name: str) -> str:
    cleaned = " ".join(screen(name).clean.split())
    if not _meaningful(cleaned) or len(cleaned) > MAX_NAME_CHARS:
        raise InvalidProcedureError(f"The name must be 1-{MAX_NAME_CHARS} characters.")
    return cleaned


def clean_steps(steps: list[str]) -> tuple[list[str], list[str]]:
    """The cleaned steps and the codes of what was taken out; raises for text that cannot be used.

    Findings never repeat the text they found. Links, addresses, markup and hidden characters are
    removed; a step that reads like an instruction to an AI is refused outright, because the
    procedure is read by a model.
    """
    if not 1 <= len(steps) <= MAX_STEPS:
        raise InvalidProcedureError(f"A procedure has 1-{MAX_STEPS} steps.")
    cleaned_steps: list[str] = []
    kinds: set[str] = set()
    for number, raw in enumerate(steps, start=1):
        result = screen(raw)
        codes = {finding.code for finding in result.findings}
        if "instruction_phrase" in codes:
            raise InvalidProcedureError(
                f"Step {number} contains words that read like instructions to an AI. "
                "Describe the condition instead."
            )
        kinds |= codes
        text = " ".join(result.clean.split())
        if len(_meaningful(text)) < MIN_STEP_CHARS or len(text) > MAX_STEP_CHARS:
            raise InvalidProcedureError(
                f"Step {number} must be {MIN_STEP_CHARS}-{MAX_STEP_CHARS} characters "
                "(after unusable text is removed)."
            )
        cleaned_steps.append(text)
    if sum(len(step) for step in cleaned_steps) > MAX_TOTAL_CHARS:
        raise InvalidProcedureError(
            f"The steps together may have at most {MAX_TOTAL_CHARS} characters."
        )
    return cleaned_steps, sorted(kinds)


def get_active(session: Session, principal: Principal) -> QualificationProcedure:
    procedure = repository.get_active(session, _tenant(principal))
    if procedure is None:
        raise NoActiveProcedureError
    return procedure


def find_active(session: Session, principal: Principal) -> QualificationProcedure | None:
    return repository.get_active(session, _tenant(principal))


def list_versions(
    session: Session, principal: Principal, *, limit: int, offset: int
) -> tuple[list[QualificationProcedure], int]:
    return repository.list_versions(session, _tenant(principal), limit=limit, offset=offset)


def save_procedure(
    session: Session,
    principal: Principal,
    *,
    name: str,
    steps: list[str],
    replaces_version: int | None,
    now: datetime | None = None,
) -> QualificationProcedure:
    """A new version; the active one (if any) is retired. ``replaces_version`` is the version
    the person was looking at: when someone else saved in the meantime, the answer is 409."""
    tenant_id = _tenant(principal)
    clean_name = _clean_name(name)
    cleaned_steps, kinds = clean_steps(steps)
    repository.lock_tenant(session, tenant_id)  # two admins saving at once take turns
    current = repository.get_active(session, tenant_id)
    seen = current.version if current else None
    if replaces_version != seen:
        raise ProcedureVersionConflictError
    latest = repository.latest_version(session, tenant_id)
    when = now or datetime.now(UTC)
    if current is not None:
        current.active = False
        current.retired_at = when
        session.flush()  # the "one active" index needs the old row retired first
    procedure = QualificationProcedure(
        tenant_id=tenant_id,
        version=latest + 1,
        name=clean_name,
        steps=cleaned_steps,
        cleaned=kinds,
        active=True,
        created_by_user_id=principal.user_id,
    )
    session.add(procedure)
    session.flush()
    record_audit(
        session,
        principal,
        action="qualifier.procedure_saved",
        entity_type="qualification_procedure",
        entity_id=procedure.id,
        changes={"version": procedure.version, "steps": len(cleaned_steps), "cleaned": kinds},
    )
    return procedure


def deactivate(
    session: Session, principal: Principal, *, version: int, now: datetime | None = None
) -> QualificationProcedure:
    """Switch the procedure off (no active one = the Qualifier does nothing). Kept in history."""
    tenant_id = _tenant(principal)
    repository.lock_tenant(session, tenant_id)
    current = repository.get_active(session, tenant_id)
    if current is None:
        raise NoActiveProcedureError
    if current.version != version:
        raise ProcedureVersionConflictError
    current.active = False
    current.retired_at = now or datetime.now(UTC)
    session.flush()
    record_audit(
        session,
        principal,
        action="qualifier.procedure_deactivated",
        entity_type="qualification_procedure",
        entity_id=current.id,
        changes={"version": current.version},
    )
    return current


__all__ = [
    "InvalidProcedureError",
    "NoActiveProcedureError",
    "ProcedureVersionConflictError",
    "clean_steps",
    "deactivate",
    "find_active",
    "get_active",
    "list_versions",
    "save_procedure",
]
