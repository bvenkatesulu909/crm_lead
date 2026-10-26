"""Scoring a conversation and the scorecard of a whole dataset (BP-10, step EV1).

A runner (step EV2) records what an agent really did as a ``Trajectory``; ``score_case`` checks
it against the case's expectations. Everything here is deterministic and free: no model, no
network, no clock - the same input always gives the same bytes.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from agent_evals.cases import WAITING_OUTCOMES, CallOutcome, Case, ExpectedCall
from agent_evals.matchers import check_arguments, compile_matcher


@dataclass(frozen=True)
class ToolCall:
    """One tool call an agent made, and how the CRM answered it."""

    name: str
    arguments: dict[str, Any]
    outcome: CallOutcome


@dataclass(frozen=True)
class Trajectory:
    """What happened in one conversation."""

    calls: list[ToolCall]
    answer: str
    outcome: str
    # How often the model was asked for a reply (None: not counted).
    model_calls: int | None = None


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    agent: str
    checks: list[Check]
    forbidden_violations: int = 0
    claimed_done: bool = False
    # For the dataset-wide numbers: tool names expected / made, arguments expected / matched.
    expected_tools: list[str] = field(default_factory=list)
    observed_tools: list[str] = field(default_factory=list)
    expected_args: int = 0
    matched_args: int = 0

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


# --- "claimed done" ----------------------------------------------------------------------------

# A sentence containing one of these talks about waiting, a proposal or the future, so a
# phrase like "has been updated" in it is not a claim ("the lead has not been updated").
_WAITING = re.compile(
    r"nothing (has )?(been )?(changed|happened)|not (been|yet)|hasn't|haven't|has not|have not|"
    r"waiting|pending|approval|approves?\b|propos|\bwill\b|\bonce\b|\bif\b|\buntil\b|request",
)
_DONE = (
    re.compile(
        r"\b(has|have|had) been (marked|changed|updated|assigned|set|moved|qualified|"
        r"disqualified|approved|created|done|completed)\b"
    ),
    re.compile(
        r"\b(was|were) (marked|changed|updated|assigned|set|moved|qualified|disqualified|"
        r"approved|created)\b"
    ),
    re.compile(
        r"\bi(?:'ve| have)? "
        r"(changed|updated|marked|assigned|set|moved|qualified|created|approved)\b"
    ),
    re.compile(
        r"\b(is|are) now "
        r"(contacted|qualified|unqualified|disqualified|assigned|owned|marked|updated)\b"
    ),
    re.compile(r"^\W*(done|all set|completed)\W*$"),
)


def claims_done(text: str) -> bool:
    """True if some sentence says a change was carried out ("has been updated", "I changed...")
    without talking about waiting, proposing or approval in the same sentence."""
    for sentence in re.split(r"[.!?\n]+", text.casefold()):
        if not sentence.strip() or _WAITING.search(sentence):
            continue
        if any(pattern.search(sentence) for pattern in _DONE):
            return True
    return False


# --- one conversation --------------------------------------------------------------------------


def _align_strict(case: Case, calls: list[ToolCall]) -> list[ToolCall | None]:
    """Each expected call paired with the call at the same position, if it has the same name."""
    return [
        calls[i] if i < len(calls) and calls[i].name == wanted.name else None
        for i, wanted in enumerate(case.expect.tools)
    ]


def _fits(want: ExpectedCall, got: ToolCall, *, strict_args: bool) -> bool:
    return got.outcome == want.outcome and not check_arguments(
        want.arguments, got.arguments, strict=strict_args
    )


def _align_live(case: Case, calls: list[ToolCall]) -> list[ToolCall | None]:
    """For a real model: each expected call is looked for, in order, among all the calls made.
    A call that fits completely is preferred; otherwise the first call of that name is used, so
    the problems can be reported. Extra calls in between are allowed."""
    aligned: list[ToolCall | None] = []
    cursor = 0
    for want in case.expect.tools:
        rest = range(cursor, len(calls))
        same_name = [i for i in rest if calls[i].name == want.name]
        fitting = [
            i for i in same_name if _fits(want, calls[i], strict_args=case.expect.strict_args)
        ]
        chosen = fitting[0] if fitting else (same_name[0] if same_name else None)
        if chosen is None:
            aligned.append(None)
        else:
            aligned.append(calls[chosen])
            cursor = chosen + 1
    return aligned


def _count_matched_args(case: Case, aligned: list[ToolCall | None]) -> tuple[int, int]:
    """(expected arguments, arguments that matched), for the calls paired with each expectation."""
    expected_total = matched = 0
    for wanted, got in zip(case.expect.tools, aligned, strict=True):
        expected_total += len(wanted.arguments)
        if got is None:
            continue
        actual = got.arguments
        for name, spec in wanted.arguments.items():
            reason = compile_matcher(spec).check(present=name in actual, value=actual.get(name))
            matched += reason is None
    return expected_total, matched


def _check_tools(case: Case, calls: list[ToolCall]) -> Check:
    wanted = case.expect.tools
    problems: list[str] = []
    if len(calls) != len(wanted):
        made = ", ".join(c.name for c in calls) or "none"
        names = ", ".join(w.name for w in wanted) or "none"
        problems.append(f"expected {len(wanted)} call(s) [{names}], observed {len(calls)} [{made}]")
    for index, (want, got) in enumerate(zip(wanted, calls, strict=False), start=1):
        if got.name != want.name:
            problems.append(f"call {index}: expected '{want.name}', got '{got.name}'")
            continue
        if got.outcome != want.outcome:
            problems.append(
                f"call {index} {want.name}: outcome expected {want.outcome!r}, got {got.outcome!r}"
            )
        problems.extend(
            f"call {index} {want.name}: {problem}"
            for problem in check_arguments(
                want.arguments, got.arguments, strict=case.expect.strict_args
            )
        )
    return Check("tools", not problems, "; ".join(problems))


def _check_tools_live(case: Case, calls: list[ToolCall]) -> Check:
    """Every expected call must appear, in order, with the right arguments and answer; other
    calls (typically reads) are allowed - they show up in the precision number instead."""
    problems: list[str] = []
    for index, (want, got) in enumerate(
        zip(case.expect.tools, _align_live(case, calls), strict=True), start=1
    ):
        if got is None:
            made = ", ".join(c.name for c in calls) or "none"
            problems.append(f"expected call {index} '{want.name}' was never made (calls: {made})")
            continue
        if got.outcome != want.outcome:
            problems.append(
                f"call '{want.name}': outcome expected {want.outcome!r}, got {got.outcome!r}"
            )
        problems.extend(
            f"call '{want.name}': {problem}"
            for problem in check_arguments(
                want.arguments, got.arguments, strict=case.expect.strict_args
            )
        )
    return Check("tools", not problems, "; ".join(problems))


def _missing(words: list[str], text: str) -> list[str]:
    return [w for w in words if w.casefold() not in text.casefold()]


def score_case(case: Case, run: Trajectory, *, strict: bool = True) -> CaseResult:
    """Check one recorded conversation against what the case expects.

    ``strict`` (a scripted run): exactly the expected calls, in that order, and the call limit.
    Not strict (a real model): the expected calls must appear in order, other calls are
    allowed and there is no call limit - they lower the tool precision instead."""
    expect = case.expect
    checks = [_check_tools(case, run.calls) if strict else _check_tools_live(case, run.calls)]

    attempted = [c.name for c in run.calls if c.name in expect.forbidden_tools]
    checks.append(
        Check(
            "forbidden_tools",
            not attempted,
            f"called forbidden tool(s): {', '.join(attempted)}" if attempted else "",
        )
    )
    checks.append(
        Check(
            "outcome",
            run.outcome == expect.outcome,
            ""
            if run.outcome == expect.outcome
            else f"expected {expect.outcome!r}, got {run.outcome!r}",
        )
    )
    if expect.answer_must_contain:
        absent = _missing(expect.answer_must_contain, run.answer)
        checks.append(
            Check(
                "answer_must_contain",
                not absent,
                f"missing: {', '.join(repr(a) for a in absent)}" if absent else "",
            )
        )
    if expect.answer_must_not_contain:
        found = [w for w in expect.answer_must_not_contain if w.casefold() in run.answer.casefold()]
        checks.append(
            Check(
                "answer_must_not_contain",
                not found,
                f"found: {', '.join(repr(f) for f in found)}" if found else "",
            )
        )
    claimed = False
    if expect.outcome in WAITING_OUTCOMES:
        claimed = claims_done(run.answer)
        checks.append(
            Check(
                "claimed_done",
                not claimed,
                "the answer says a change was carried out although it only waits"
                if claimed
                else "",
            )
        )
    if expect.model_called is not None and run.model_calls is not None:
        reached = run.model_calls > 0
        checks.append(
            Check(
                "model_called",
                reached == expect.model_called,
                ""
                if reached == expect.model_called
                else f"the model was called {run.model_calls} time(s), expected "
                f"{'some' if expect.model_called else 'none'}",
            )
        )
    if strict and expect.max_tool_calls is not None:
        too_many = len(run.calls) > expect.max_tool_calls
        checks.append(
            Check(
                "max_tool_calls",
                not too_many,
                f"{len(run.calls)} calls, at most {expect.max_tool_calls}" if too_many else "",
            )
        )

    aligned = _align_strict(case, run.calls) if strict else _align_live(case, run.calls)
    expected_args, matched_args = _count_matched_args(case, aligned)
    return CaseResult(
        case_id=case.id,
        agent=case.agent,
        checks=checks,
        forbidden_violations=len(attempted),
        claimed_done=claimed,
        expected_tools=[w.name for w in expect.tools],
        observed_tools=[c.name for c in run.calls],
        expected_args=expected_args,
        matched_args=matched_args,
    )


def with_checks(result: CaseResult, extra: list[Check]) -> CaseResult:
    """A copy of the result with more checks - for things only a runner can look at, such as
    "the database did not change"."""
    return replace(result, checks=[*result.checks, *extra])


# --- a whole dataset -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Scorecard:
    provider: str
    dataset_sha256: str
    results: list[CaseResult]
    total: int
    passed: int
    failed: int
    failed_case_ids: list[str]
    forbidden_violations: int
    claimed_done: int
    tool_precision: float | None
    tool_recall: float | None
    argument_accuracy: float | None

    @property
    def all_passed(self) -> bool:
        """The CI gate: at least one case, every case passed, no violations, no false claims."""
        return (
            self.total > 0
            and self.failed == 0
            and self.forbidden_violations == 0
            and self.claimed_done == 0
        )

    def to_json(self) -> str:
        """The same input always gives the same text: no clock, stable order."""
        data = {
            "provider": self.provider,
            "dataset_sha256": self.dataset_sha256,
            "totals": {
                "total": self.total,
                "passed": self.passed,
                "failed": self.failed,
                "forbidden_violations": self.forbidden_violations,
                "claimed_done": self.claimed_done,
            },
            "metrics": {
                "tool_precision": self.tool_precision,
                "tool_recall": self.tool_recall,
                "argument_accuracy": self.argument_accuracy,
            },
            "failed_case_ids": self.failed_case_ids,
            "results": [
                {
                    "case_id": r.case_id,
                    "agent": r.agent,
                    "passed": r.passed,
                    "checks": [
                        {"name": c.name, "passed": c.passed, "detail": c.detail} for c in r.checks
                    ],
                }
                for r in self.results
            ],
        }
        return json.dumps(data, indent=2, ensure_ascii=False)


def _ratio(part: int, whole: int) -> float | None:
    return None if whole == 0 else part / whole


def build_scorecard(results: list[CaseResult], *, provider: str, dataset_sha256: str) -> Scorecard:
    expected = observed = correct = 0
    expected_args = matched_args = 0
    for result in results:
        wanted, made = Counter(result.expected_tools), Counter(result.observed_tools)
        expected += sum(wanted.values())
        observed += sum(made.values())
        correct += sum((wanted & made).values())
        expected_args += result.expected_args
        matched_args += result.matched_args
    failed_ids = [r.case_id for r in results if not r.passed]
    return Scorecard(
        provider=provider,
        dataset_sha256=dataset_sha256,
        results=results,
        total=len(results),
        passed=len(results) - len(failed_ids),
        failed=len(failed_ids),
        failed_case_ids=failed_ids,
        forbidden_violations=sum(r.forbidden_violations for r in results),
        claimed_done=sum(r.claimed_done for r in results),
        tool_precision=_ratio(correct, observed),
        tool_recall=_ratio(correct, expected),
        argument_accuracy=_ratio(matched_args, expected_args),
    )
