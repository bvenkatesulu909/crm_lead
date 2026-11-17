"""Drafting call notes and a deal checklist from a call transcript (ADR 0035, CN2).

    permission ─► the transcript (only of a lead the asker may read) ─► size ─► limits ─►
    governed model (switch, budget) ─► strict shape of its ONE tool call ─► every quote checked
    against the transcript ─► one insert-only draft + audit

The model sees the cleaned transcript, the language and the checklist fields - not the lead's name
or contact details - and can call one tool that only reports. The service stores the checked
result as a DRAFT in this module's own tables; it changes nothing else in the CRM (proposals for
the approval queue come in CN4). The model is always wrapped by the agent registry (ADR 0016).
Services never commit.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.errors import DomainError, ForbiddenError
from app.modules.agents import api as agents_api
from app.modules.assistant.api import ChatModel
from app.modules.call_notes import answer, repository, rules
from app.modules.call_notes.models import CallNote, CallNoteLine
from app.modules.calls import api as calls_api

AGENT_KEY = "call_notes"


class NotesRefusedError(DomainError):
    """The transcript or the model's answer cannot be used. ``code`` is ``call_notes_<reason>``."""

    status_code = 422

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = f"call_notes_{code}"


class RateLimitedError(DomainError):
    status_code = 429
    code = "call_notes_rate_limited"


@dataclass(frozen=True)
class Limits:
    """How often drafts may be made (settings ``CRM_CALL_NOTES_PER_*``). The platform sets them."""

    per_recording_day: int
    per_user_hour: int
    per_tenant_day: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "Limits":
        return cls(
            settings.call_notes_per_recording_day,
            settings.call_notes_per_user_hour,
            settings.call_notes_per_tenant_day,
        )

    @classmethod
    def default(cls) -> "Limits":
        fields = Settings.model_fields
        return cls(
            int(fields["call_notes_per_recording_day"].default),
            int(fields["call_notes_per_user_hour"].default),
            int(fields["call_notes_per_tenant_day"].default),
        )


@dataclass(frozen=True)
class NotesResult:
    note: CallNote
    lines: list[CallNoteLine]


def framework_for(session: Session, tenant_id: uuid.UUID) -> str:
    """The organisation's checklist frame (BANT until an administrator chooses otherwise)."""
    return repository.framework_of(session, tenant_id) or rules.DEFAULT_FRAMEWORK


def _tenant_and_user(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if (
        principal.tenant_id is None
        or principal.user_id is None
        or principal.user_type != "staff"
        or not principal.has_permission(Permission.CALL_NOTES_RUN)
        or not principal.has_permission(Permission.CALL_READ)
    ):
        raise ForbiddenError("You may not do this.")
    return principal.tenant_id, principal.user_id


def _check_limits(
    session: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    recording_id: uuid.UUID,
    limits: Limits,
    now: datetime,
) -> None:
    hour, day = now - timedelta(hours=1), now - timedelta(days=1)
    if (
        repository.count_notes(session, tenant_id, since=day, recording_id=recording_id)
        >= limits.per_recording_day
    ):
        raise RateLimitedError("Notes for this call were made a few times today already.")
    if (
        repository.count_notes(session, tenant_id, since=hour, user_id=user_id)
        >= limits.per_user_hour
    ):
        raise RateLimitedError("You have asked for many call notes. Try again later.")
    if repository.count_notes(session, tenant_id, since=day) >= limits.per_tenant_day:
        raise RateLimitedError("Your organisation reached its daily limit for call notes.")


def _governed(
    session: Session,
    model: ChatModel,
    tenant_id: uuid.UUID,
    ai_limits: agents_api.Limits | None,
) -> ChatModel:
    """The registry gate (ADR 0016): off, over budget or the tool taken away stops it here."""
    governed: ChatModel = agents_api.governed(
        model, session, tenant_id, AGENT_KEY, ai_limits or agents_api.Limits.default()
    )
    if not governed.available:
        governed.reply(system="", messages=[], tools=[])  # raises "not configured"
    return governed


def _refused(refusal: rules.AnswerRefused) -> NotesRefusedError:
    return NotesRefusedError(refusal.code, str(refusal))


def run_notes(
    session: Session,
    principal: Principal,
    model: ChatModel,
    lead_id: uuid.UUID,
    call_id: uuid.UUID,
    *,
    model_name: str,
    limits: Limits | None = None,
    ai_limits: agents_api.Limits | None = None,
    now: datetime | None = None,
) -> NotesResult:
    """Draft call notes for one recording as the person asking. The result is one stored draft;
    nothing else in the CRM changes."""
    tenant_id, user_id = _tenant_and_user(principal)
    when = now or datetime.now(UTC)
    transcript = calls_api.transcript_of(session, principal, lead_id, call_id)
    try:
        rules.check_transcript(transcript.text)
    except rules.AnswerRefused as refusal:
        raise _refused(refusal) from None
    seen = answer.clean_segments(transcript.segments)
    if not seen.segments:
        raise NotesRefusedError("no_transcript", "The recording has no transcript to read.")
    _check_limits(session, tenant_id, user_id, call_id, limits or Limits.default(), when)

    framework = framework_for(session, tenant_id)
    governed = _governed(session, model, tenant_id, ai_limits)
    reply = governed.reply(
        system=answer.system_prompt(
            framework, transcript.language, suspicious="instruction_phrase" in seen.codes
        ),
        messages=[{"role": "user", "content": answer.transcript_message(seen.segments)}],
        tools=[answer.tool(framework)],
    )
    uses = reply.tool_uses
    if len(uses) != 1 or uses[0].name != answer.TOOL_NAME:
        raise NotesRefusedError("bad_answer", "The model did not return exactly one set of notes.")
    try:
        claims, notes = answer.parse_answer(uses[0].input, framework)
        verified = rules.verify(framework, claims, notes, seen.segments)
    except rules.AnswerRefused as refusal:
        raise _refused(refusal) from None

    codes = sorted({*seen.codes, *verified.cleaned_codes})
    version_no = repository.next_version(session, tenant_id, call_id)
    tokens = sum(
        value for key, value in reply.usage.items() if key in ("input_tokens", "output_tokens")
    )
    note = repository.add(
        session,
        CallNote(
            tenant_id=tenant_id,
            recording_id=call_id,
            lead_id=transcript.lead_id,
            requested_by_user_id=user_id,
            framework=framework,
            version_no=version_no,
            model_name=model_name[:60] or "model",
            tokens=tokens,
            downgraded=verified.downgraded,
            dropped_notes=verified.dropped_notes,
            cleaned_codes=codes,
        ),
        [
            CallNoteLine(
                tenant_id=tenant_id,
                position=position,
                field=line.field,
                state=line.state,
                value=line.value,
                quote=line.quote,
                start_ms=line.start_ms,
                end_ms=line.end_ms,
                reason=line.reason,
                note_code=line.note_code,
            )
            for position, line in enumerate(verified.lines, start=1)
        ],
    )
    stored = repository.lines_of(session, tenant_id, note.id)
    counts = {state: sum(1 for ln in stored if ln.state == state) for state in rules.STATES}
    # Ids, counts and codes only - never a quote, a value or a reason.
    record_audit(
        session,
        principal,
        action="call_notes.created",
        entity_type="call_note",
        entity_id=note.id,
        changes={
            "recording_id": str(call_id),
            "lead_id": str(transcript.lead_id),
            "framework": framework,
            "version_no": version_no,
            "lines": counts,
            "downgraded": verified.downgraded,
            "dropped_notes": verified.dropped_notes,
            "cleaned_codes": codes,
        },
    )
    return NotesResult(note, stored)
