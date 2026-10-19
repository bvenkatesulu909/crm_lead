"""Lead status rules ("state machine").

    new ──► contacted ──► qualified ──► converted   (only through the convert endpoint)
     │          │  ▲          │
     │          ▼  │          ▼
     └──────► unqualified ◄───┘     unqualified can be reopened to "contacted"

- ``converted`` is final: nothing can change a converted lead's status.
- ``converted`` can only be reached from ``qualified``, and only by conversion.
- Staying in the same status is not a transition (rejected, so history stays meaningful).
"""

from app.core.errors import ConflictError

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"contacted", "qualified", "unqualified"}),
    "contacted": frozenset({"qualified", "unqualified"}),
    "qualified": frozenset({"contacted", "unqualified", "converted"}),
    "unqualified": frozenset({"contacted"}),
    "converted": frozenset(),
}


class InvalidTransitionError(ConflictError):
    code = "invalid_status_transition"


def check_transition(current: str, target: str, *, via_conversion: bool = False) -> None:
    """Raise InvalidTransitionError unless current -> target is allowed."""
    if target == "converted" and not via_conversion:
        raise InvalidTransitionError("Use the convert endpoint to convert a lead.")
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransitionError(f"A lead cannot go from '{current}' to '{target}'.")
