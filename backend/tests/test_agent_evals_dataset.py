"""Agent evaluation harness (BP-10, step EV1): the real case files in ``evals/agents``.

Every pull request loads them, so a typo in a tool name or a broken matcher is caught here,
long before a runner plays the conversations (step EV2).
"""

from pathlib import Path

from agent_evals.cases import dataset_hash, known_tools, load_cases

CASES = Path(__file__).resolve().parents[1] / "evals" / "agents"


def test_the_case_files_load_and_ids_are_unique() -> None:
    cases = load_cases(CASES)
    assert len(cases) >= 4
    assert len({c.id for c in cases}) == len(cases)
    assert [c.id for c in cases] == sorted(c.id for c in cases)


def test_every_scripted_call_is_a_real_tool_or_asserted_as_refused() -> None:
    for case in load_cases(CASES):
        real = known_tools(case.agent)
        refused = {c.name for c in case.expect.tools if c.outcome == "refused"}
        for step in case.script:
            for call in step.calls:
                assert call.name in real | refused, (case.id, call.name)


def test_cases_that_call_a_made_up_tool_are_marked_scripted_only() -> None:
    # A real model is not asked to call a tool that doesn't exist; the scripted run forces it.
    # (Other forced bad calls - "converted", an extra argument - are marked by the author.)
    for case in load_cases(CASES):
        real = known_tools(case.agent)
        if any(call.name not in real for step in case.script for call in step.calls):
            assert case.live is False, case.id


def test_a_waiting_proposal_is_never_described_as_done() -> None:
    for case in load_cases(CASES):
        if case.expect.outcome == "proposal_pending":
            assert case.expect.answer_must_not_contain, case.id
            assert case.expect.forbidden_tools, case.id


def test_the_dataset_has_a_fingerprint() -> None:
    first = dataset_hash(CASES)
    assert len(first) == 64 and first == dataset_hash(CASES)
