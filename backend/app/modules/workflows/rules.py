"""Pure rule logic: validate a rule against the catalogue and evaluate its conditions.

No database here, so every rule can be unit-tested. A saved rule is always in the normalised
shape returned by ``validate`` - the engine never has to second-guess stored JSON.
"""

import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.errors import DomainError
from app.modules.workflows.catalogue import (
    ACTION_TYPES,
    FIELD_UPDATES,
    MAX_ACTIONS,
    MAX_CONDITIONS,
    OPERATORS,
    RECORD_FIELDS,
    ROLES,
    TRIGGERS,
    FieldSpec,
)

RECORD_PLACEHOLDER = "{record}"


class InvalidRuleError(DomainError):
    status_code = 422
    code = "invalid_rule"


def _fail(message: str) -> InvalidRuleError:
    return InvalidRuleError(message)


def _text(value: Any, what: str, max_len: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(f"{what} is required.")
    one_line = " ".join(value.split())  # also keeps line breaks out of e-mail subjects
    if len(one_line) > max_len:
        raise _fail(f"{what} can be at most {max_len} characters.")
    return one_line


def _person(value: Any, what: str, *, roles: bool) -> str:
    """'owner', 'user:<uuid>' or (when allowed) 'role:<role>'."""
    if value == "owner":
        return "owner"
    if isinstance(value, str) and value.startswith("user:"):
        try:
            return f"user:{uuid.UUID(value[5:])}"
        except ValueError:
            pass
    if roles and isinstance(value, str) and value.startswith("role:") and value[5:] in ROLES:
        return str(value)
    allowed = "the owner, a colleague" + (" or a role" if roles else "")
    raise _fail(f"{what} must be {allowed}.")


def _number(value: Any, what: str) -> str:
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise _fail(f"{what} must be a number.") from None
    if not number.is_finite():
        raise _fail(f"{what} must be a number.")
    return str(number)


def _condition(raw: Any, fields: Mapping[str, FieldSpec]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise _fail("Each condition needs a field, a comparison and a value.")
    spec = fields.get(str(raw.get("field")))
    if spec is None:
        raise _fail(f"Unknown field {raw.get('field')!r} for this trigger.")
    op = raw.get("op")
    if op not in OPERATORS[spec.type]:
        raise _fail(f"'{op}' can't be used with {spec.label}.")
    value = raw.get("value")
    if op == "in":
        if not isinstance(value, list) or not value or any(v not in spec.options for v in value):
            raise _fail(f"Choose one or more values for {spec.label}.")
        return {"field": spec.key, "op": op, "value": sorted(set(value))}
    if spec.type == "choice":
        if value not in spec.options:
            raise _fail(f"Choose a value for {spec.label}.")
        return {"field": spec.key, "op": op, "value": value}
    if spec.type == "number":
        return {"field": spec.key, "op": op, "value": _number(value, spec.label)}
    return {"field": spec.key, "op": op, "value": _text(value, spec.label, 100)}


def _action(raw: Any, record_type: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or raw.get("type") not in ACTION_TYPES:
        raise _fail("Each action needs a type: create a task, notify, or update a field.")
    kind = raw["type"]
    if kind == "create_task":
        days = raw.get("due_in_days", 0)
        if not isinstance(days, int) or isinstance(days, bool) or not 0 <= days <= 365:
            raise _fail("A task's due date must be 0 to 365 days later.")
        return {
            "type": kind,
            "subject": _text(raw.get("subject"), "The task subject", 200),
            "due_in_days": days,
            "assignee": _person(raw.get("assignee"), "The task's assignee", roles=False),
        }
    if kind == "notify":
        return {
            "type": kind,
            "message": _text(raw.get("message"), "The message", 200),
            "to": _person(raw.get("to"), "The recipient", roles=True),
        }
    update = FIELD_UPDATES.get(str(raw.get("field")))
    if update is None or record_type not in update.record_types:
        raise _fail("This field can't be changed by rules for this trigger.")
    if raw.get("value") not in update.options:
        raise _fail(f"Choose a value for '{update.label}'.")
    return {"type": kind, "field": update.key, "value": raw["value"]}


def validate(
    trigger: str, days: int | None, conditions: Any, actions: Any
) -> tuple[int | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalised (days, conditions, actions) or InvalidRuleError with a readable message."""
    spec = TRIGGERS.get(trigger)
    if spec is None:
        raise _fail("Choose a trigger.")
    if spec.kind == "schedule":
        if not isinstance(days, int) or isinstance(days, bool) or not 0 <= days <= 365:
            raise _fail(f"{spec.days_label}: enter 0 to 365.")
    else:
        days = None
    if not isinstance(conditions, list) or len(conditions) > MAX_CONDITIONS:
        raise _fail(f"At most {MAX_CONDITIONS} conditions.")
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        raise _fail(f"Add 1 to {MAX_ACTIONS} actions.")
    fields = {f.key: f for f in RECORD_FIELDS[spec.record_type]}
    return (
        days,
        [_condition(c, fields) for c in conditions],
        [_action(a, spec.record_type) for a in actions],
    )


def _compare(actual: str | Decimal, op: str, expected: Any) -> bool:
    if op == "in":
        return actual in expected
    if isinstance(actual, Decimal):
        target = Decimal(str(expected))
        return {
            "eq": actual == target,
            "neq": actual != target,
            "gt": actual > target,
            "gte": actual >= target,
            "lt": actual < target,
            "lte": actual <= target,
        }[op]
    text, wanted = str(actual).casefold(), str(expected).casefold()
    return text == wanted if op == "eq" else text != wanted


def matches(conditions: Sequence[Mapping[str, Any]], values: Mapping[str, str | Decimal]) -> bool:
    """All conditions must hold (AND). A field the record doesn't have never matches."""
    for c in conditions:
        if c["field"] not in values or not _compare(values[c["field"]], c["op"], c["value"]):
            return False
    return True


def render(template: str, record_label: str) -> str:
    """Fills in "{record}" only - plain replacement, no format language."""
    return template.replace(RECORD_PLACEHOLDER, record_label)
