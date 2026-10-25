"""Argument matchers: what a tool call's arguments must look like (BP-10, step EV1).

In a case file an expected argument is either

* a plain JSON value - the argument must be equal to it (same type: ``1`` is not ``true``), or
* a one-key object, a matcher:

    {"any": true}                 anything, but the argument must be sent
    {"any_uuid": true}            a UUID in text form
    {"one_of": ["a", "b"]}        one of these plain values
    {"matches": "regex"}          the whole text matches the regular expression
    {"contains": "text"}          the text contains this, ignoring case
    {"absent": true}              the argument must NOT be sent

Mistakes in a matcher are found when the case file is loaded (``MatcherError``).
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class MatcherError(ValueError):
    """A matcher in a case file is not valid."""


_KNOWN = ("any", "any_uuid", "one_of", "matches", "contains", "absent")
_MISSING = "argument is missing"


def _same(expected: Any, actual: Any) -> bool:
    """Equal and of the same type (so 1 is not True, 3 is not "3")."""
    if isinstance(expected, list) or isinstance(actual, list):
        return (
            isinstance(expected, list)
            and isinstance(actual, list)
            and len(expected) == len(actual)
            and all(_same(e, a) for e, a in zip(expected, actual, strict=True))
        )
    return type(expected) is type(actual) and bool(expected == actual)


def _plain(value: Any) -> bool:
    if isinstance(value, list):
        return all(_plain(v) for v in value)
    return value is None or isinstance(value, str | int | float | bool)


@dataclass(frozen=True)
class Matcher:
    kind: str
    arg: Any = None
    pattern: re.Pattern[str] | None = None

    def check(self, *, present: bool, value: Any) -> str | None:
        """None if the argument is fine, otherwise a short reason."""
        if self.kind == "absent":
            return None if not present else "must not be sent"
        if not present:
            return _MISSING
        if self.kind == "equals":
            return None if _same(self.arg, value) else f"expected {self.arg!r}, got {value!r}"
        if self.kind == "any":
            return None
        if self.kind == "any_uuid":
            if isinstance(value, str):
                try:
                    uuid.UUID(value)
                    return None
                except ValueError:
                    pass
            return f"expected a UUID, got {value!r}"
        if self.kind == "one_of":
            if any(_same(option, value) for option in self.arg):
                return None
            return f"expected one of {self.arg!r}, got {value!r}"
        if self.kind == "matches":
            if isinstance(value, str) and self.pattern and self.pattern.fullmatch(value):
                return None
            return f"expected text matching /{self.arg}/, got {value!r}"
        if self.kind == "contains":
            if isinstance(value, str) and str(self.arg).casefold() in value.casefold():
                return None
            return f"expected text containing {self.arg!r}, got {value!r}"
        raise MatcherError(f"unknown matcher kind {self.kind!r}")  # unreachable: compile checks


def compile_matcher(spec: Any) -> Matcher:
    """Turn the JSON of a case file into a Matcher, refusing anything that isn't valid."""
    if not isinstance(spec, dict):
        if not _plain(spec):
            raise MatcherError(
                f"a plain expected value must be text, number, true/false, null or a list: {spec!r}"
            )
        return Matcher("equals", spec)
    if len(spec) != 1:
        raise MatcherError(f"a matcher has exactly one key (one of {', '.join(_KNOWN)}): {spec!r}")
    ((key, arg),) = spec.items()
    if key not in _KNOWN:
        raise MatcherError(f"unknown matcher {key!r} (use one of {', '.join(_KNOWN)})")
    if key in ("any", "any_uuid", "absent"):
        if arg is not True:
            raise MatcherError(f'{key} must be written {{"{key}": true}}')
        return Matcher(key)
    if key == "one_of":
        if not isinstance(arg, list) or not arg or not _plain(arg):
            raise MatcherError("one_of needs a non-empty list of plain values")
        return Matcher(key, arg)
    if not isinstance(arg, str) or not arg:
        raise MatcherError(f"{key} needs non-empty text")
    if key == "matches":
        try:
            return Matcher(key, arg, re.compile(arg))
        except re.error as exc:
            raise MatcherError(f"matches: not a valid regular expression ({exc})") from exc
    return Matcher(key, arg)


def check_arguments(
    expected: Mapping[str, Any], actual: Mapping[str, Any], *, strict: bool = False
) -> list[str]:
    """Problems (empty = fine), each starting with the argument's name.

    Every expected argument must match. Arguments nobody expected are allowed - unless
    ``strict``, which is how a case says "no extra argument such as tenant_id may be sent".
    """
    problems: list[str] = []
    for name, spec in expected.items():
        reason = compile_matcher(spec).check(present=name in actual, value=actual.get(name))
        if reason:
            problems.append(f"{name}: {reason}")
    if strict:
        problems.extend(f"{name}: not expected" for name in actual if name not in expected)
    return problems
