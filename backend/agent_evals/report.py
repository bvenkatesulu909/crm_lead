"""Reading a scorecard back, comparing it with a baseline and writing it for people (BP-10, EV5).

A scorecard is a JSON file (``Scorecard.to_json``). A baseline is an older scorecard kept in git.
``compare`` says what got worse; ``render_markdown`` writes the table a person reads in the
terminal or in the CI job summary. Pure Python: no database, no model.
"""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field

from agent_evals.scoring import CaseResult, Scorecard, build_scorecard

# How much accuracy may fall (in points of 100) before a comparison fails: real models vary a
# little from run to run, so a tiny dip is noise, not a regression.
TOLERANCE = 0.05


@dataclass(frozen=True)
class Baseline:
    """What a comparison needs from an older scorecard."""

    provider: str
    dataset_sha256: str
    cases: dict[str, bool]  # case id -> passed
    forbidden_violations: int
    claimed_done: int
    tool_precision: float | None
    tool_recall: float | None
    argument_accuracy: float | None


@dataclass(frozen=True)
class Comparison:
    ok: bool
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    new_cases: list[str] = field(default_factory=list)
    removed_cases: list[str] = field(default_factory=list)
    metric_drops: list[str] = field(default_factory=list)
    dataset_changed: bool = False


def load_baseline(text: str) -> Baseline:
    """Read a scorecard file. Anything that is not one is refused with a clear message."""
    try:
        data = json.loads(text)
        totals, metrics, results = data["totals"], data["metrics"], data["results"]
        return Baseline(
            provider=str(data["provider"]),
            dataset_sha256=str(data["dataset_sha256"]),
            cases={str(r["case_id"]): bool(r["passed"]) for r in results},
            forbidden_violations=int(totals["forbidden_violations"]),
            claimed_done=int(totals["claimed_done"]),
            tool_precision=metrics["tool_precision"],
            tool_recall=metrics["tool_recall"],
            argument_accuracy=metrics["argument_accuracy"],
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"this is not a scorecard file ({type(exc).__name__}: {exc})") from exc


def merge_scorecards(cards: list[Scorecard]) -> Scorecard:
    """One scorecard from several (one per agent), cases sorted by id."""
    providers = {card.provider for card in cards}
    if len(providers) > 1:
        raise ValueError(f"can't merge scorecards of different providers: {sorted(providers)}")
    results: list[CaseResult] = sorted(
        (r for card in cards for r in card.results), key=lambda r: r.case_id
    )
    digest = hashlib.sha256("\n".join(sorted(c.dataset_sha256 for c in cards)).encode()).hexdigest()
    return build_scorecard(
        results, provider=providers.pop() if providers else "none", dataset_sha256=digest
    )


def compare(card: Scorecard, baseline: Baseline) -> Comparison:
    """What got worse (and better) since the baseline."""
    now = {r.case_id: r.passed for r in card.results}
    regressions = sorted(i for i, ok in now.items() if baseline.cases.get(i) is True and not ok)
    improvements = sorted(i for i, ok in now.items() if baseline.cases.get(i) is False and ok)
    drops: list[str] = []
    if card.forbidden_violations > baseline.forbidden_violations:
        drops.append(
            f"forbidden-tool violations rose from {baseline.forbidden_violations} "
            f"to {card.forbidden_violations}"
        )
    if card.claimed_done > baseline.claimed_done:
        drops.append(
            f"answers claiming a change was done rose from {baseline.claimed_done} "
            f"to {card.claimed_done}"
        )
    for label, before, after in (
        ("tool precision", baseline.tool_precision, card.tool_precision),
        ("tool recall", baseline.tool_recall, card.tool_recall),
        ("argument accuracy", baseline.argument_accuracy, card.argument_accuracy),
    ):
        if before is not None and after is not None and after < before - TOLERANCE:
            drops.append(f"{label} fell from {_percent(before)} to {_percent(after)}")
    return Comparison(
        ok=not regressions and not drops,
        regressions=regressions,
        improvements=improvements,
        new_cases=sorted(set(now) - set(baseline.cases)),
        removed_cases=sorted(set(baseline.cases) - set(now)),
        metric_drops=drops,
        dataset_changed=card.dataset_sha256 != baseline.dataset_sha256,
    )


# --- for people ----------------------------------------------------------------------------------


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f} %"


def render_markdown(
    card: Scorecard, comparison: Comparison | None = None, *, title: str = "Agent evaluation"
) -> str:
    """The table a person reads (terminal or CI job summary)."""
    per_agent: Counter[str] = Counter(r.agent for r in card.results)
    failed_per_agent: Counter[str] = Counter(r.agent for r in card.results if not r.passed)
    lines = [
        f"### {title}: {card.provider} (dataset {card.dataset_sha256[:12]})",
        "",
        "| Agent | Cases | Passed | Failed |",
        "|---|---:|---:|---:|",
    ]
    for agent in sorted(per_agent):
        failed = failed_per_agent[agent]
        lines.append(f"| {agent} | {per_agent[agent]} | {per_agent[agent] - failed} | {failed} |")
    lines.append(f"| **All** | {card.total} | {card.passed} | {card.failed} |")
    lines += [
        "",
        f"Forbidden-tool violations: {card.forbidden_violations} - "
        f"answers claiming a change was done: {card.claimed_done} - "
        f"tool precision: {_percent(card.tool_precision)} - recall: {_percent(card.tool_recall)} - "
        f"argument accuracy: {_percent(card.argument_accuracy)}",
        "",
    ]
    if card.total == 0:
        lines.append("**No cases were run.** That is not a pass.")
    elif card.all_passed:
        lines.append("**All cases passed.**")
    else:
        failed_ids = ", ".join(card.failed_case_ids) or "none"
        lines.append(f"**Failed cases:** {failed_ids}")
        for result in card.results:
            for check in result.checks:
                if not check.passed:
                    lines.append(f"- `{result.case_id}` - {check.name}: {check.detail}")
    if comparison is not None:
        lines += [
            "",
            "**Compared with the baseline:** "
            + ("no regression." if comparison.ok else "REGRESSION."),
        ]
        if comparison.regressions:
            lines.append(
                "- regressions (used to pass, now fail): " + ", ".join(comparison.regressions)
            )
        lines.extend(f"- {drop}" for drop in comparison.metric_drops)
        if comparison.improvements:
            lines.append("- improvements: " + ", ".join(comparison.improvements))
        if comparison.new_cases:
            lines.append("- new cases: " + ", ".join(comparison.new_cases))
        if comparison.removed_cases:
            lines.append("- removed cases: " + ", ".join(comparison.removed_cases))
        if comparison.dataset_changed:
            lines.append("- the cases changed since the baseline was recorded")
    return "\n".join(lines) + "\n"


def render_summary(cards: dict[str, Scorecard]) -> str:
    """One page for a CI job: a section per scorecard."""
    parts = ["## Agent evaluations (scripted model, no paid key)", ""]
    for name in sorted(cards):
        parts.append(render_markdown(cards[name], title=name))
    return "\n".join(parts)
