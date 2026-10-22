"""Weekly gaps aggregation (R6.1)."""

from typing import Any

from app.modules.knowledge.gaps import build_gaps_report


def test_report_counts_negative_and_unanswered():
    queries: list[dict[str, Any]] = [
        {
            "id": "q1",
            "question": "returns?",
            "answer": "14 days",
            "sources": [{"document": "x"}],
            "surface": "portal_answer",
        },
        {
            "id": "q2",
            "question": "widgets?",
            "answer": "I couldn't find that",
            "sources": [],
            "surface": "staff_answer",
        },
        {
            "id": "q3",
            "question": "delivery?",
            "answer": "3-5 days",
            "sources": [],
            "surface": "staff_answer",
        },
    ]
    feedback: list[dict[str, Any]] = [
        {"query_id": "q1", "helpful": False},
        {"query_id": "q3", "helpful": True},
    ]
    report = build_gaps_report(queries, feedback)
    assert report["queries"] == 3
    assert report["feedback"]["not_helpful"] == 1
    assert report["feedback"]["negative_rate"] == 0.5
    assert report["unanswered"] == 2
    assert report["refused"] == 1
    assert report["top_negative_questions"][0]["question"] == "returns?"
    assert len(report["top_unanswered_questions"]) == 2


def test_empty_report_is_safe():
    queries: list[dict[str, Any]] = []
    feedback: list[dict[str, Any]] = []
    report = build_gaps_report(queries, feedback)
    assert report["queries"] == 0
    assert report["feedback"]["negative_rate"] == 0.0
