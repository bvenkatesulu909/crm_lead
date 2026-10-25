"""Agent evaluation harness (BP-10, step EV5): the scorecard report and the baseline comparison.

A scorecard is a file; a baseline is an older scorecard kept in git. The comparison says what got
worse (a case that used to pass, more forbidden-tool violations, more "done" claims, a drop in
tool or argument accuracy) so a real-model run can be judged against its first run. All pure
Python: no database, no model.
"""

import json
from typing import Any

import pytest

from agent_evals.report import (
    Baseline,
    compare,
    load_baseline,
    merge_scorecards,
    render_markdown,
    render_summary,
)
from agent_evals.scoring import CaseResult, Check, Scorecard, build_scorecard

HASH = "a" * 64


def result(
    case_id: str,
    agent: str = "staff_assistant",
    *,
    passed: bool = True,
    expected: list[str] | None = None,
    observed: list[str] | None = None,
    args: tuple[int, int] = (0, 0),
    violations: int = 0,
    claimed: bool = False,
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        agent=agent,
        checks=[Check("outcome", passed, "" if passed else "wrong")],
        forbidden_violations=violations,
        claimed_done=claimed,
        expected_tools=expected or [],
        observed_tools=observed if observed is not None else expected or [],
        expected_args=args[0],
        matched_args=args[1],
    )


def card(*results: CaseResult, provider: str = "fake") -> Scorecard:
    return build_scorecard(list(results), provider=provider, dataset_sha256=HASH)


GOOD = [
    result("staff-one", expected=["search_leads"], args=(1, 1)),
    result("portal-one", "portal_assistant", expected=["list_my_accounts"]),
    result("public-one", "public_chat", expected=["save_lead"], args=(2, 2)),
    result("rag-one", "rag_answers"),
]


# --- the scorecard as a file -------------------------------------------------------------------


def test_a_scorecard_file_round_trips_into_a_baseline() -> None:
    baseline = load_baseline(card(*GOOD, result("staff-two", passed=False)).to_json())
    assert baseline.provider == "fake" and baseline.dataset_sha256 == HASH
    assert baseline.cases["staff-one"] is True and baseline.cases["staff-two"] is False
    assert baseline.forbidden_violations == 0 and baseline.claimed_done == 0
    assert baseline.tool_precision == 1.0 and baseline.argument_accuracy == 1.0


@pytest.mark.parametrize(
    "text", ["not json", "{}", '{"results": 3}', json.dumps({"provider": "x"})]
)
def test_a_file_that_is_not_a_scorecard_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="scorecard"):
        load_baseline(text)


def test_scorecards_of_several_agents_merge_into_one() -> None:
    staff = card(GOOD[0], provider="deepseek")
    chat = card(GOOD[2], provider="deepseek")
    merged = merge_scorecards([staff, chat])
    assert merged.total == 2 and merged.provider == "deepseek"
    assert [r.case_id for r in merged.results] == ["public-one", "staff-one"]  # sorted by id
    assert merged.dataset_sha256 not in (staff.dataset_sha256, "")  # a hash of the parts


def test_merging_scorecards_of_different_providers_is_refused() -> None:
    with pytest.raises(ValueError, match="provider"):
        merge_scorecards([card(GOOD[0], provider="fake"), card(GOOD[1], provider="deepseek")])


# --- the comparison ----------------------------------------------------------------------------


def test_the_same_scorecard_has_nothing_to_report() -> None:
    now = card(*GOOD)
    verdict = compare(now, load_baseline(now.to_json()))
    assert verdict.ok is True
    assert not (
        verdict.regressions or verdict.improvements or verdict.new_cases or verdict.removed_cases
    )
    assert verdict.metric_drops == [] and verdict.dataset_changed is False


def test_a_case_that_used_to_pass_and_now_fails_is_a_regression() -> None:
    before = load_baseline(card(*GOOD).to_json())
    now = card(*GOOD[:-1], result("rag-one", "rag_answers", passed=False))
    verdict = compare(now, before)
    assert verdict.ok is False and verdict.regressions == ["rag-one"]


def test_a_case_that_now_passes_is_an_improvement_not_a_problem() -> None:
    before = load_baseline(
        card(*GOOD[:-1], result("rag-one", "rag_answers", passed=False)).to_json()
    )
    verdict = compare(card(*GOOD), before)
    assert verdict.ok is True and verdict.improvements == ["rag-one"]


def test_new_and_removed_cases_are_listed_but_do_not_fail_the_comparison() -> None:
    before = load_baseline(card(*GOOD).to_json())
    now = card(*GOOD[1:], result("brand-new", passed=False))
    verdict = compare(now, before)
    assert verdict.new_cases == ["brand-new"] and verdict.removed_cases == ["staff-one"]
    assert verdict.regressions == [] and verdict.ok is True


def test_more_violations_or_false_claims_than_before_fail_the_comparison() -> None:
    before = load_baseline(card(*GOOD).to_json())
    worse = card(
        *GOOD[1:],
        result("staff-one", violations=1, claimed=True, expected=["search_leads"], args=(1, 1)),
    )
    verdict = compare(worse, before)
    assert verdict.ok is False
    assert any("forbidden" in drop for drop in verdict.metric_drops)
    assert any("done" in drop for drop in verdict.metric_drops)


def test_a_drop_in_accuracy_of_more_than_five_points_fails_but_a_small_one_does_not() -> None:
    before = load_baseline(card(*GOOD).to_json())
    small = card(
        result("staff-one", expected=["search_leads"], args=(100, 97)),
        *GOOD[1:],
    )
    assert compare(small, before).ok is True  # 100 % -> about 99 % overall: within 5 points
    big = card(
        result("staff-one", expected=["search_leads"], args=(10, 1)),
        *GOOD[1:],
    )
    verdict = compare(big, before)
    assert verdict.ok is False and any("argument" in drop for drop in verdict.metric_drops)


def test_a_changed_dataset_is_noted() -> None:
    before = load_baseline(card(*GOOD).to_json())
    other = build_scorecard(list(GOOD), provider="fake", dataset_sha256="b" * 64)
    assert compare(other, before).dataset_changed is True


# --- what a person reads -----------------------------------------------------------------------


def test_the_report_counts_per_agent_and_lists_failures() -> None:
    now = card(*GOOD, result("staff-bad", passed=False))
    text = render_markdown(now)
    assert "fake" in text and HASH[:12] in text
    assert "staff_assistant" in text and "public_chat" in text and "rag_answers" in text
    assert "staff-bad" in text  # a failing case is named
    assert "5 cases" in text or "| 5 |" in text


def test_a_clean_scorecard_says_so_and_never_hides_a_violation() -> None:
    assert "all cases passed" in render_markdown(card(*GOOD)).lower()
    dirty = render_markdown(card(*GOOD[1:], result("x-case", violations=2)))
    assert "2" in dirty and "forbidden" in dirty.lower()


def test_an_empty_scorecard_is_not_reported_as_a_pass() -> None:
    assert "all cases passed" not in render_markdown(card()).lower()
    assert "no cases" in render_markdown(card()).lower()


def test_the_comparison_is_part_of_the_report_when_given() -> None:
    before = load_baseline(card(*GOOD).to_json())
    now = card(*GOOD[:-1], result("rag-one", "rag_answers", passed=False))
    text = render_markdown(now, compare(now, before))
    assert "regression" in text.lower() and "rag-one" in text


def test_the_summary_joins_several_scorecards_for_a_ci_job() -> None:
    summary = render_summary({"staff_assistant": card(GOOD[0]), "public_chat": card(GOOD[2])})
    assert summary.startswith("## ")
    assert summary.count("### ") >= 2 or summary.count("| ") > 6
    assert "staff_assistant" in summary and "public_chat" in summary


def test_the_baseline_type_is_plain_data() -> None:
    base: Any = Baseline(
        provider="fake",
        dataset_sha256=HASH,
        cases={"a": True},
        forbidden_violations=0,
        claimed_done=0,
        tool_precision=None,
        tool_recall=None,
        argument_accuracy=None,
    )
    assert base.cases == {"a": True}
