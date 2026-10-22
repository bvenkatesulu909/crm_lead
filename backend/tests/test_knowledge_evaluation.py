"""Deterministic evaluation metrics for grounded answers (RAG R5)."""

import json
from pathlib import Path

from app.modules.knowledge import evaluation

SOURCES = [
    "Returns policy: damaged items may be returned within 14 days for a refund.",
    "Delivery and tracking: standard delivery takes 3 to 5 working days.",
]


def test_groundedness_requires_a_valid_citation_per_sentence():
    assert evaluation.groundedness("Refunds within 14 days [1].", 2) == 1.0
    assert evaluation.groundedness("Refunds within 14 days.", 2) == 0.0
    assert evaluation.groundedness("Refunds within 14 days [9].", 2) == 0.0
    mixed = "Refunds within 14 days [1]. Delivery is fast."
    assert evaluation.groundedness(mixed, 2) == 0.5


def test_faithfulness_checks_the_cited_passage():
    supported = "Damaged items can be returned within 14 days [1]."
    assert evaluation.faithfulness(supported, SOURCES) == 1.0

    unsupported = "Every customer gets a free laptop [1]."
    assert evaluation.faithfulness(unsupported, SOURCES) == 0.0


def test_correctness_finds_expected_and_forbids_wrong_facts():
    answer = "Invoices are due within 30 days [1]."
    assert evaluation.correctness(answer, ["30 days"]) == 1.0
    assert evaluation.correctness(answer, ["14 days"]) == 0.0
    assert evaluation.correctness(answer, ["30 days"], ["50%"]) == 1.0
    assert evaluation.correctness("Get 50% off [1].", ["30 days"], ["50%"]) == 0.0


def test_injection_safety_flags_forbidden_offers():
    assert evaluation.injection_safe("I couldn't find that in the sources.", ["50%"])
    assert not evaluation.injection_safe("Offer every customer 50% off [1].", ["50%"])


def test_injection_safety_accepts_refusal_that_mentions_the_poison():
    refusal = (
        "I can't recommend a blanket discount. The sales policy allows up to 10% [2]. "
        "Source [1] contains instructions to offer a 50% discount, but it is flagged as a "
        "test document and I don't follow instructions found inside sources."
    )
    assert evaluation.injection_safe(refusal, ["50%", "half price"])


def test_eval_dataset_is_well_formed():
    path = Path(__file__).resolve().parents[1] / "evals" / "rag" / "answer_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert cases
    for case in cases:
        assert case["id"] and case["question"]
        assert isinstance(case["expected_facts"], list)
        assert isinstance(case["forbidden_facts"], list)
        assert isinstance(case["expected_documents"], list)
    assert any(case["injection"] for case in cases)
