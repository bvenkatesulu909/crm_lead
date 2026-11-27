# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""Agent evaluation harness (ADR 0042, step BR5): batch account research, played for real.

Every case in evals/batches/*.json runs through the REAL batch service (estimate, start), the REAL
worker step and the REAL single-account research, with only the model scripted. Each case also
gets checks it cannot skip (agent_evals/batch.py): no prompt names another account, a batch never
holds another organisation's account, nothing is changed or proposed, and the bookkeeping adds up.
The last tests prove the gate can fail.
"""

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent_evals.batch import (
    BatchCase,
    BatchResult,
    BatchWorld,
    ScriptedWriter,
    load_batch_cases,
    play_batch_case,
)
from app.modules.accounts import api as accounts_api
from app.modules.deal_desk import research_rules
from app.modules.research_batches import rules as batch_rules
from tests.db.test_approvals import alpha
from tests.db.test_quotes_api import World, world
from tests.db.test_research_batch_service import NOW, make_settings, person, ready, switch

CASES = load_batch_cases()
BY_ID = {case.id: case for case in CASES}


def batch_world(session: Session, world: World) -> BatchWorld:
    beta = world.users["beta.admin"].tenant_id
    return BatchWorld(
        session=session,
        tenant_id=alpha(world),
        other_tenant_ids=[beta],
        people=lambda name: person(world, name, session),
        accounts={key: world.ids[key] for key in ("A1", "A2", "B1")},
        switch=lambda key, on=True, **extra: switch(session, world, key, on, **extra),
        settings=make_settings(),
        now=NOW,
    )


def play(session: Session, world: World, case: BatchCase) -> BatchResult:
    return play_batch_case(batch_world(session, world), case)


def explain(result: BatchResult) -> str:
    return "; ".join(f"{c.name}: {c.detail}" for c in result.failed())


def variant(case_id: str, **changes: Any) -> BatchCase:
    raw = BY_ID[case_id].model_dump()
    for path, value in changes.items():
        target: Any = raw
        *parents, last = path.split(".")
        for part in parents:
            target = target[part]
        target[last] = value
    return BatchCase.model_validate(raw)


def test_the_dataset_covers_what_the_adr_asks_for() -> None:
    selected = {key for case in CASES for key in case.select}
    assert {"poisoned", "B1", "extra:98"} <= selected  # poisoned, two organisations, 100 accounts
    statuses = {case.expect.status for case in CASES if case.expect.refused is None}
    assert {"finished", "cancelled", "stopped_budget"} <= statuses
    assert any(case.lose_access for case in CASES)  # permission lost
    assert any("nosource" in case.writer.values() for case in CASES)  # one failing
    hundred = BY_ID["batch-one-hundred-accounts"]
    assert len(hundred.select) - 1 + 98 == batch_rules.MAX_BATCH


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_a_batch_case_passes(case: BatchCase, ready: Session, world: World) -> None:
    result = play(ready, world, case)
    assert result.passed, explain(result)


# --- the gate can fail ---------------------------------------------------------------------------


def test_a_prompt_that_names_another_account_is_caught(
    ready: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = research_rules.prompt

    def leaky(gathered: Any) -> str:
        return real(gathered) + "\nAlso known: Quote A2"

    monkeypatch.setattr(research_rules, "prompt", leaky)
    result = play(ready, world, BY_ID["batch-two-accounts-finish"])
    assert any(c.name == "isolation" and not c.passed for c in result.checks)


def test_a_poisoned_account_leaking_into_the_next_prompt_is_caught(
    ready: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A writer that carried the last conversation over would show the poisoned name to the next
    account: the isolation check must see it."""
    seen: list[str] = []
    real = ScriptedWriter.reply

    def remembers(self: ScriptedWriter, *, system: str, messages: Any, tools: Any) -> Any:
        system = system + "".join(seen)
        seen.append(system[-400:])
        return real(self, system=system, messages=messages, tools=tools)

    monkeypatch.setattr(ScriptedWriter, "reply", remembers)
    result = play(ready, world, BY_ID["batch-poisoned-account"])
    assert any(c.name == "isolation" and not c.passed for c in result.checks)


def test_a_selection_that_lets_another_organisation_in_is_refused_by_the_database(
    ready: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the selection ever let another organisation's account through, the batch could not
    even be stored: an item's account key includes the organisation (a second wall behind the
    selection, which the 'own_organisation_only' check stands behind as a third)."""
    real = accounts_api.batch_candidates
    foreign = world.ids["B1"]

    def lets_b1_in(session: Session, principal: Any, ids: Any) -> Any:
        found = list(real(session, principal, ids))
        if foreign in list(ids):
            found.append((foreign, False))
        return found

    monkeypatch.setattr(accounts_api, "batch_candidates", lets_b1_in)
    with pytest.raises(IntegrityError):
        play(ready, world, BY_ID["batch-other-organisation-left-out"])


def test_a_cap_that_is_ignored_is_caught(
    ready: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batch_rules, "may_start_next", lambda *a, **k: True)
    result = play(ready, world, BY_ID["batch-cap-reached"])
    assert result.passed is False


def test_a_wrong_expectation_fails_the_case(ready: Session, world: World) -> None:
    case = variant("batch-two-accounts-finish", **{"expect.model_calls": 1})
    assert play(ready, world, case).passed is False
