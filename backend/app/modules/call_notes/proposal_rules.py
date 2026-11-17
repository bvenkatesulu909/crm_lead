"""What a call-notes draft may turn into proposals (ADR 0035, CN4): pure, no database.

Only two kinds of suggestion ever leave a draft: buyer-memory ASSUMPTIONS (a stated or assumed line
of a field that has a reviewed buyer-memory key) and one follow-up task for the unknown lines. The
texts are built here from checked lines and fixed words - the server never takes a key, an id or a
status from the model or the client.
"""

from dataclasses import dataclass

from app.modules.call_notes import rules

TASK_DUE_DAYS = 2
NOTE_MAX = 300
REASON_MAX = 500
SUBJECT_MAX = 200
MAX_POSITIONS = 20


class PlanRefused(ValueError):
    """The request cannot be turned into proposals. ``code`` is stable; the message is safe."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StoredLine:
    """A stored draft line (only what the plan needs)."""

    position: int
    field: str
    state: str
    value: str | None
    quote: str | None
    start_ms: int | None
    reason: str | None


@dataclass(frozen=True)
class MemoryItem:
    position: int
    field: str
    label: str
    key: str
    value: str
    note: str
    reason: str
    at_ms: int


@dataclass(frozen=True)
class TaskItem:
    subject: str
    reason: str
    labels: list[str]
    due_in_days: int


@dataclass(frozen=True)
class Plan:
    memory: list[MemoryItem]
    task: TaskItem | None


def stamp(milliseconds: int) -> str:
    seconds = max(0, milliseconds) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def _cut(text: str, longest: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= longest else text[: longest - 1].rstrip() + "…"


def _as_line(line: StoredLine) -> rules.Line:
    return rules.Line(
        line.field, line.state, line.value, line.quote, line.start_ms, None, line.reason, None
    )


def _memory_item(framework: str, line: StoredLine, version_no: int) -> MemoryItem | None:
    key = rules.proposal_key(framework, _as_line(line))
    if key is None or line.value is None or line.start_ms is None:
        return None
    when = stamp(line.start_ms)
    if line.state == "stated":
        note = f'Said on the call at {when}: "{line.quote or ""}"'
    else:
        note = f"{line.reason or 'Hinted on the call'} (call, {when})"
    label = rules.LABELS[line.field]
    note = _cut(note, NOTE_MAX)
    return MemoryItem(
        position=line.position,
        field=line.field,
        label=label,
        key=key,
        value=line.value,
        note=note,
        reason=_cut(f"Call notes v{version_no}, {label} at {when}: {note}", REASON_MAX),
        at_ms=line.start_ms,
    )


def eligible(framework: str, lines: list[StoredLine], version_no: int) -> list[MemoryItem]:
    """The lines that could become a buyer-memory assumption, in the draft's order."""
    items = (_memory_item(framework, line, version_no) for line in lines)
    return [item for item in items if item is not None]


def _task(framework: str, lines: list[StoredLine], version_no: int) -> TaskItem | None:
    labels = [
        rules.LABELS[line.field]
        for line in lines
        if line.state == "unknown" and line.field != rules.NOTE and line.field in rules.LABELS
    ]
    if not labels:
        return None
    named = ", ".join(labels[:-1]) + (" and " if len(labels) > 1 else "") + labels[-1]
    return TaskItem(
        subject=_cut(f"Ask the buyer about {named.lower()}", SUBJECT_MAX),
        reason=_cut(
            f"The call did not answer: {named.lower()} (call notes v{version_no}).", REASON_MAX
        ),
        labels=labels,
        due_in_days=TASK_DUE_DAYS,
    )


def plan(
    framework: str,
    lines: list[StoredLine],
    *,
    version_no: int,
    positions: list[int] | None,
    follow_up_task: bool,
) -> Plan:
    """Turn a draft into the proposals to make. ``positions`` chooses lines (None = every eligible
    one); anything that cannot be proposed is refused rather than skipped."""
    if framework not in rules.FRAMEWORKS:
        raise PlanRefused("bad_framework", "The checklist frame does not exist.")
    everything = eligible(framework, lines, version_no)
    if positions is None:
        chosen = everything
    else:
        if len(positions) != len(set(positions)):
            raise PlanRefused("duplicate_position", "A line was chosen twice.")
        by_position = {item.position: item for item in everything}
        missing = [p for p in positions if p not in by_position]
        if missing:
            raise PlanRefused(
                "not_proposable",
                "Only a stated or assumed line of a field that has a buyer-memory home can be "
                "proposed.",
            )
        chosen = [by_position[p] for p in positions]
    if len(chosen) > rules.MAX_PROPOSALS:
        raise PlanRefused(
            "too_many", f"At most {rules.MAX_PROPOSALS} buyer-memory suggestions per request."
        )
    return Plan(chosen, _task(framework, lines, version_no) if follow_up_task else None)
