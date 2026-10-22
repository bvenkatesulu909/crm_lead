"""Weekly knowledge-gaps aggregation (R6.1): negative feedback + unanswered questions."""

from collections.abc import Iterable
from typing import Any

REFUSAL_MARKERS = ("couldn't find", "could not find", "fully supported")


def build_gaps_report(
    queries: Iterable[dict[str, Any]], feedback: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    queries = list(queries)
    votes = list(feedback)
    by_id = {q["id"]: q for q in queries}
    negative = [v for v in votes if not v["helpful"]]
    unanswered = [q for q in queries if not q.get("sources")]
    refused = [
        q
        for q in queries
        if any(marker in str(q.get("answer") or "").lower() for marker in REFUSAL_MARKERS)
    ]
    return {
        "queries": len(queries),
        "by_surface": {
            surface: sum(1 for q in queries if q.get("surface") == surface)
            for surface in ("staff_answer", "portal_answer", "staff_search")
        },
        "feedback": {
            "helpful": sum(1 for v in votes if v["helpful"]),
            "not_helpful": len(negative),
            "negative_rate": round(len(negative) / len(votes), 3) if votes else 0.0,
        },
        "unanswered": len(unanswered),
        "refused": len(refused),
        "top_negative_questions": [
            {
                "question": str(by_id[v["query_id"]]["question"])[:200],
                "surface": by_id[v["query_id"]].get("surface"),
            }
            for v in negative[:10]
            if v["query_id"] in by_id
        ],
        "top_unanswered_questions": [
            {"question": str(q["question"])[:200], "surface": q.get("surface")}
            for q in unanswered[:10]
        ],
    }
