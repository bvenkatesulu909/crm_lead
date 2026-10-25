# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Agent evaluation harness (BP-10, step EV4): cited-answer cases, played for real.

Every case in evals/rag/ci_cases.json goes through the REAL grounded-answer pipeline - the real
chunks in the real test database, the real vector and keyword search, the visibility rules, the
numbered sources, the citation check and the refusals - with two stand-ins: a small deterministic
embedder (no model download) and a scripted answer (no paid key). Answers are scored with the
project's existing deterministic metrics. A failing case fails the pull request.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from agent_evals.rag import HashingEmbedder
from agent_evals.rag_cases import RagCase, load_rag_cases, rag_dataset_hash
from agent_evals.scoring import CaseResult, build_scorecard
from app.modules.knowledge import answers, retrieval
from tests.db.agent_eval_support import (
    RAG_MIN_SIMILARITY,
    best_similarity,
    explain,
    ingest_corpus,
    play_rag,
)
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name

CASES_FILE = Path(__file__).resolve().parents[2] / "evals" / "rag" / "ci_cases.json"
RAG = load_rag_cases(CASES_FILE)
BY_ID = {case.id: case for case in RAG}


def variant(case_id: str, **changes: Any) -> RagCase:
    """A changed copy of a real case, to see the gate notice the change."""
    raw = BY_ID[case_id].model_dump(by_alias=True)
    for path, value in changes.items():
        target: Any = raw
        *parents, last = path.split(".")
        for part in parents:
            target = target[part]
        target[last] = value
    return RagCase.model_validate(raw)


def test_there_are_cited_answer_cases() -> None:
    assert len(RAG) >= 12


@pytest.mark.parametrize("case", RAG, ids=lambda case: case.id)
def test_a_cited_answer_case_passes(case: RagCase, db_session: Session, world: World) -> None:
    result, _ = play_rag(db_session, world, case)
    assert result.passed, explain(result)


def test_the_whole_cited_answer_dataset_scores_clean(db_session: Session, world: World) -> None:
    embedder = HashingEmbedder()
    ingest_corpus(db_session, world, embedder)
    results: list[CaseResult] = [
        play_rag(db_session, world, case, embedder=embedder, ingest=False)[0] for case in RAG
    ]
    card = build_scorecard(results, provider="fake", dataset_sha256=rag_dataset_hash(CASES_FILE))
    assert card.total == len(RAG)
    assert card.all_passed, card.to_json()


def test_the_threshold_sits_between_answerable_and_unanswerable_questions(
    db_session: Session, world: World
) -> None:
    # The "close enough" threshold was chosen from these numbers. If a new case or a changed
    # document moves them, this test says so before the cases start failing for a muddy reason.
    embedder = HashingEmbedder()
    ingest_corpus(db_session, world, embedder)
    scores = {case.id: best_similarity(db_session, world, case, embedder) for case in RAG}
    answerable = [s for c in RAG if c.expect.outcome != "not_found" and (s := scores[c.id])]
    unanswerable = [scores[c.id] for c in RAG if c.expect.outcome == "not_found"]
    assert min(answerable) >= RAG_MIN_SIMILARITY + 0.05, scores
    assert max(unanswerable) <= RAG_MIN_SIMILARITY - 0.05, scores


# --- the gate can fail ----------------------------------------------------------------------------


def test_a_changed_expectation_fails_the_case(db_session: Session, world: World) -> None:
    case = variant("rag-returns-window", **{"expect.cited_documents": ["Payment terms"]})
    result, _ = play_rag(db_session, world, case)
    assert result.passed is False
    assert "Payment terms" in explain(result)


def test_a_missing_citation_check_would_be_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the pipeline stopped checking citations, an uncited answer would be shown.
    monkeypatch.setattr(answers, "validate_citations", lambda text, count: (True, [1]))
    result, _ = play_rag(db_session, world, BY_ID["rag-uncited-answer-refused"])
    assert result.passed is False


def test_a_threshold_that_lets_everything_through_would_be_caught(
    db_session: Session, world: World
) -> None:
    # With no "close enough" rule the model would be called (and paid for) on every question.
    result, _ = play_rag(db_session, world, BY_ID["rag-not-found-weather"], min_similarity=0.0)
    assert result.passed is False
    assert "model_called" in explain(result)


def test_internal_documents_reaching_a_customer_would_be_caught(
    db_session: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        retrieval, "_allowed_visibilities", lambda principal: ("internal", "customer_visible")
    )
    result, _ = play_rag(db_session, world, BY_ID["rag-customer-sees-customer-visible-only"])
    assert result.passed is False
    assert "forbidden_documents" in explain(result)


def test_an_answer_that_names_the_wrong_document_is_caught(
    db_session: Session, world: World
) -> None:
    case = variant(
        "rag-returns-window",
        answer="A damaged item may be returned within 14 days {cite:Payment terms}.",
    )
    result, _ = play_rag(db_session, world, case)
    assert result.passed is False
