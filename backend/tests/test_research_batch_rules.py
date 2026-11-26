"""Pure rules of batch account research (ADR 0042, BR1): selection, estimate, hard stop, state."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.research_batches import rules
from app.modules.research_batches.rules import Candidate, WorstCase

NOW = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
WORST = WorstCase(input_tokens=6000, output_tokens=4000)


def ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


def readable(items: list[uuid.UUID], archived: set[uuid.UUID] | None = None) -> list[Candidate]:
    return [Candidate(i, i in (archived or set())) for i in items]


# --- ticked rows -------------------------------------------------------------------------------


def test_ticked_rows_keep_their_order_and_drop_duplicates() -> None:
    a, b, c = ids(3)
    selection = rules.resolve_rows([c, a, c, b, a], readable([a, b, c]))
    assert selection.accounts == (c, a, b)
    assert selection.not_available == 0 and selection.archived == 0


def test_an_id_the_person_cannot_read_is_only_counted_never_named() -> None:
    mine, theirs, made_up = ids(3)
    selection = rules.resolve_rows([mine, theirs, made_up], readable([mine]))
    assert selection.accounts == (mine,)
    assert selection.not_available == 2
    assert not hasattr(selection, "reasons")  # nothing says which one or why


def test_archived_accounts_are_skipped_with_their_own_count() -> None:
    live, old = ids(2)
    selection = rules.resolve_rows([live, old], readable([live, old], {old}))
    assert (
        selection.accounts == (live,) and selection.archived == 1 and selection.not_available == 0
    )


def test_more_than_the_cap_is_refused_not_cut() -> None:
    many = ids(101)
    with pytest.raises(rules.BatchRuleError) as error:
        rules.resolve_rows(many, readable(many))
    assert error.value.code == "batch_too_large"


def test_exactly_the_cap_is_allowed() -> None:
    many = ids(100)
    assert len(rules.resolve_rows(many, readable(many)).accounts) == 100


def test_duplicates_do_not_count_towards_the_cap() -> None:
    many = ids(100)
    assert len(rules.resolve_rows(many + many[:10], readable(many)).accounts) == 100


def test_a_lower_cap_is_honoured_and_a_higher_one_is_refused() -> None:
    few = ids(5)
    with pytest.raises(rules.BatchRuleError):
        rules.resolve_rows(few, readable(few), cap=4)
    with pytest.raises(ValueError):
        rules.resolve_rows(few, readable(few), cap=101)
    with pytest.raises(ValueError):
        rules.resolve_rows(few, readable(few), cap=0)


def test_nothing_chosen_or_nothing_usable_is_refused() -> None:
    a, b = ids(2)
    with pytest.raises(rules.BatchRuleError) as none:
        rules.resolve_rows([], [])
    assert none.value.code == "empty_selection"
    with pytest.raises(rules.BatchRuleError) as unusable:
        rules.resolve_rows([a, b], readable([b], {b}))
    assert unusable.value.code == "empty_selection"


# --- a saved filter ----------------------------------------------------------------------------


def test_a_filter_is_taken_as_the_persons_own_search_returned_it() -> None:
    a, b, old = ids(3)
    selection = rules.resolve_filter(readable([a, b, old], {old}), total_matching=3)
    assert selection.accounts == (a, b) and selection.archived == 1


def test_a_filter_that_finds_too_many_is_refused_with_the_number() -> None:
    a = ids(1)
    with pytest.raises(rules.BatchRuleError) as error:
        rules.resolve_filter(readable(a), total_matching=140)
    assert error.value.code == "batch_too_large" and "140" in str(error.value)


def test_a_filter_with_no_matches_is_refused() -> None:
    with pytest.raises(rules.BatchRuleError):
        rules.resolve_filter([], total_matching=0)


# --- reuse -------------------------------------------------------------------------------------


def test_a_brief_under_a_day_old_is_reused() -> None:
    assert rules.is_reusable(NOW - timedelta(hours=23, minutes=59), NOW)
    assert not rules.is_reusable(NOW - timedelta(hours=24), NOW)
    assert not rules.is_reusable(None, NOW)


def test_research_again_anyway_never_reuses() -> None:
    assert not rules.is_reusable(NOW - timedelta(minutes=5), NOW, again=True)


# --- the estimate and the cap --------------------------------------------------------------------


def test_the_upper_bound_is_accounts_times_the_worst_case() -> None:
    estimate = rules.estimate_tokens(40, WORST, typical_per_account=3000)
    assert estimate.upper_bound_tokens == 400_000
    assert estimate.typical_tokens == 120_000
    assert estimate.accounts_calling_model == 40


def test_the_typical_figure_never_exceeds_the_worst_case() -> None:
    estimate = rules.estimate_tokens(2, WORST, typical_per_account=50_000)
    assert estimate.typical_tokens == estimate.upper_bound_tokens == 20_000


def test_no_accounts_calling_the_model_costs_nothing() -> None:
    estimate = rules.estimate_tokens(0, WORST, 3000)
    assert estimate.upper_bound_tokens == 0 and estimate.typical_tokens == 0


def test_negative_counts_are_refused() -> None:
    with pytest.raises(ValueError):
        rules.estimate_tokens(-1, WORST, 0)
    with pytest.raises(ValueError):
        rules.estimate_tokens(1, WORST, -1)


@pytest.mark.parametrize(
    ("shown", "now", "ok"),
    [
        (1000, 1000, True),
        (1000, 1200, True),  # exactly 20 % up
        (1000, 800, True),  # exactly 20 % down
        (1000, 1201, False),
        (1000, 799, False),
        (0, 0, True),
        (0, 1, False),
    ],
)
def test_the_confirmed_figure_must_still_be_true(shown: int, now: int, ok: bool) -> None:
    assert rules.estimate_still_matches(shown, now) is ok


def test_the_cap_is_the_confirmed_figure_unless_the_month_has_less_left() -> None:
    assert rules.token_cap(400_000, None) == 400_000
    assert rules.token_cap(400_000, 1_000_000) == 400_000
    assert rules.token_cap(400_000, 150_000) == 150_000
    assert rules.token_cap(400_000, 0) == 0
    assert rules.token_cap(400_000, -5) == 0  # never negative


def test_the_next_item_starts_only_if_its_worst_case_fits() -> None:
    assert rules.may_start_next(0, WORST, 10_000)
    assert rules.may_start_next(5_000, WORST, 15_000)  # exactly fits
    assert not rules.may_start_next(5_001, WORST, 15_000)  # one token too many
    assert not rules.may_start_next(0, WORST, 9_999)
    assert not rules.may_start_next(0, WORST, 0)


def test_the_cap_holds_for_a_whole_run_of_worst_case_items() -> None:
    cap = rules.token_cap(10 * WORST.total, None)
    used = 0
    started = 0
    while rules.may_start_next(used, WORST, cap):
        used += WORST.total  # every call uses its worst case
        started += 1
    assert started == 10 and used <= cap


# --- state -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after", "ok"),
    [
        ("queued", "running", True),
        ("queued", "reused", True),
        ("queued", "skipped", True),
        ("queued", "not_run", True),
        ("queued", "done", False),  # nothing is done without running
        ("running", "done", True),
        ("running", "failed", True),
        ("running", "queued", True),  # a temporary error is retried
        ("running", "not_run", False),
        ("done", "queued", False),
        ("failed", "running", False),
        ("not_run", "running", False),
        ("reused", "done", False),
    ],
)
def test_items_move_only_along_allowed_paths(before: str, after: str, ok: bool) -> None:
    assert rules.can_move(before, after) is ok


def test_unknown_states_are_errors() -> None:
    with pytest.raises(ValueError):
        rules.can_move("queued", "finished")
    with pytest.raises(ValueError):
        rules.can_move("weird", "done")


def test_only_a_failed_item_has_a_known_reason() -> None:
    rules.check_failure("failed", "over_budget")
    rules.check_failure("done", None)
    for status, code in (("failed", None), ("failed", "because"), ("done", "error")):
        with pytest.raises(rules.BatchRuleError):
            rules.check_failure(status, code)


def test_a_batch_runs_while_any_item_can_still_move() -> None:
    assert (
        rules.batch_outcome(["done", "queued"], cancel_requested=False, budget_stopped=False)
        == "running"
    )
    assert (
        rules.batch_outcome(["done", "running"], cancel_requested=True, budget_stopped=False)
        == "running"
    )


def test_the_end_state_names_why_it_ended() -> None:
    end = ["done", "failed", "reused", "skipped"]
    assert rules.batch_outcome(end, cancel_requested=False, budget_stopped=False) == "finished"
    assert (
        rules.batch_outcome(end + ["not_run"], cancel_requested=True, budget_stopped=False)
        == "cancelled"
    )
    assert (
        rules.batch_outcome(end + ["not_run"], cancel_requested=False, budget_stopped=True)
        == "stopped_budget"
    )
    # A budget stop wins over a cancel that arrived at the same time.
    assert (
        rules.batch_outcome(end + ["not_run"], cancel_requested=True, budget_stopped=True)
        == "stopped_budget"
    )


def test_counts_include_every_state() -> None:
    result = rules.counts(["done", "done", "failed"])
    assert result["done"] == 2 and result["failed"] == 1 and result["queued"] == 0
    assert set(result) == set(rules.ITEM_STATUSES)
    with pytest.raises(ValueError):
        rules.counts(["nope"])


def test_stopping_turns_only_queued_items_into_not_run() -> None:
    assert rules.conclude_unstarted(["done", "running", "queued", "queued", "failed"]) == [
        "done",
        "running",
        "not_run",
        "not_run",
        "failed",
    ]


def test_the_statuses_match_the_documented_lists() -> None:
    assert rules.MAX_BATCH == 100
    assert "stopped_budget" in rules.BATCH_STATUSES
    assert set(rules.FINISHED_ITEMS) == set(rules.ITEM_STATUSES) - {"queued", "running"}
