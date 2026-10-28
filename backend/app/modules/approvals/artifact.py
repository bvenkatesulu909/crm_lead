"""The verification artifact of an AI proposal (ADR 0018, step VA1).

A proposal stores its PLAN: for every field it will change, the value before and the value
after (ids and codes, never names), and the BASIS: the record as it was when the proposal was
made. When the proposal is approved and has run, the artifact gets an OUTCOME: what was seen
afterwards, and whether that matches the plan. All of it is plain data, so a difference between
what was announced and what happened is a fact someone can read, not an impression.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.modules.approvals.sentinel import Verdict

STORED_VERSION = 2


def _norm(value: Any) -> Any:
    """Compare ids as text, and structures by content (key order does not matter)."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _norm(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    return value


@dataclass(frozen=True)
class Change:
    """One field of one record: what it is now (``before``) and what it will be (``after``)."""

    field: str
    before: Any
    after: Any

    def to_json(self) -> dict[str, Any]:
        return {"field": self.field, "before": _norm(self.before), "after": _norm(self.after)}


@dataclass(frozen=True)
class Plan:
    """What a kind of action will change, and the record it was judged against."""

    changes: list[Change]
    # The record as it was (its version, status, owner): empty when the record has no such state.
    basis: dict[str, Any] = field(default_factory=dict)


def build_artifact(
    verdict: Verdict, changes: list[Change], basis: dict[str, Any]
) -> dict[str, Any]:
    """What is stored with a new proposal: the Sentinel's findings plus the plan."""
    stored = verdict.to_json()
    stored["version"] = STORED_VERSION
    stored["spec"] = {"changes": [c.to_json() for c in changes], "basis": _norm(basis)}
    return stored


def mismatches(plan: list[Change], seen: list[Change]) -> list[str]:
    """The fields whose value afterwards is not the planned one, including a planned field that
    was not seen and a field that changed without being announced. Only ``after`` is compared:
    the record has moved on, so its old value says nothing about whether the action worked."""
    wanted = {c.field: _norm(c.after) for c in plan}
    got = {c.field: _norm(c.after) for c in seen}
    names = [name for name in wanted if got.get(name, _MISSING) != wanted[name]]
    names += [name for name in got if name not in wanted]
    return names


_MISSING = object()


def outcome_json(
    approver_id: uuid.UUID, plan: list[Change] | None, seen: list[Change] | None
) -> dict[str, Any]:
    """The outcome of a decision to approve. ``seen`` is None when the action did not run;
    ``plan`` is None for a proposal made before artifacts existed (nothing is judged then)."""
    ran = seen is not None
    differs = mismatches(plan, seen) if plan is not None and seen is not None else []
    return {
        "ran": ran,
        "ran_as": str(approver_id),
        "seen": [{"field": c.field, "after": _norm(c.after)} for c in seen or []],
        "matches_spec": (not differs) if plan is not None and ran else None,
        "differs": differs,
    }
