"""What other modules may use from the video brief (ADR 0041): the approval queue checks a drafted
script and stores it once a different person approves.

Only this file is imported from outside the module (import-linter)."""

import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.modules.video_brief import repository, rules
from app.modules.video_brief.models import VideoScript

__all__ = ["add_approved_script", "latest_script_lines", "script_problem"]


def script_problem(lines: Sequence[str], length_seconds: int) -> str | None:
    """Why these lines may not be saved as a script, or None. The same checks as a hand-written
    script (cleaning, card numbers and instructions, contact details, banned statements, the
    length) - run again at approval, because what waits in the queue must still pass."""
    try:
        rules.check_script(lines, length_seconds=length_seconds)
    except rules.ScriptError as exc:
        return str(exc)
    return None


def latest_script_lines(
    session: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID
) -> list[str] | None:
    """The lines of the newest saved script of a lead, or None."""
    rows = repository.scripts_of(session, tenant_id, lead_id)
    return list(rows[0].lines) if rows else None


def add_approved_script(
    session: Session,
    approver: Principal,
    lead_id: uuid.UUID,
    *,
    language: str,
    tone: str,
    goal: str,
    length_seconds: int,
    lines: Sequence[str],
    proposal_id: uuid.UUID,
) -> uuid.UUID:
    """Store an approved AI draft as the next version of the lead's script. The approver is the
    person recorded; the proposal it came from is kept. Does not commit."""
    if approver.tenant_id is None or approver.user_id is None:
        raise LookupError("only a person can approve")
    checked = rules.check_script(lines, length_seconds=length_seconds)
    script = VideoScript(
        tenant_id=approver.tenant_id,
        lead_id=lead_id,
        created_by_user_id=approver.user_id,
        version=repository.next_version(session, approver.tenant_id, lead_id),
        language=language,
        tone=tone,
        goal=goal,
        length_seconds=length_seconds,
        lines=checked.lines,
        words=checked.words,
        source="ai_draft",
        proposal_id=proposal_id,
    )
    session.add(script)
    session.flush()
    return script.id
