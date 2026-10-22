"""Free retrieval evaluation and threshold calibration (RAG R5) - no paid model calls.

    python -m scripts.eval_retrieval --tenant alpha-demo
    python -m scripts.eval_retrieval --calibrate

It runs the real local embedder and cross-encoder against the seeded demo tenant, computes
hit@5 and MRR with reranking on/off, and (with --calibrate) prints the best similarity per case
so a knowledge_min_similarity threshold can be chosen from evidence instead of a guess.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import model_registry as _model_registry  # noqa: F401 - resolves cross-model FKs
from app.core.ai.embeddings import Embedder, build_embedder
from app.core.auth.principal import Principal
from app.core.config import get_settings
from app.core.db import bind_tenant, create_db_engine, create_session_factory
from app.modules.identity.models import Tenant
from app.modules.knowledge import retrieval

CASES_PATH = Path(__file__).resolve().parents[1] / "evals" / "rag" / "retrieval_cases.json"


def load_cases() -> list[dict[str, Any]]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("the retrieval dataset is empty")
    return cases


def run(
    session: Session,
    principal: Principal,
    embedder: Embedder,
    cases: list[dict[str, Any]],
    *,
    reranker: retrieval.Reranker | None,
    top_k: int = 5,
) -> tuple[float, float, list[dict[str, Any]]]:
    hits = 0
    reciprocal_rank = 0.0
    rows: list[dict[str, Any]] = []
    for case in cases:
        outcome = retrieval.search(
            session,
            principal,
            embedder,
            query=case["question"],
            candidates=40,
            rrf_k=60,
            top_k=top_k,
            min_similarity=None,
            reranker=reranker,
            rerank_candidates=10,
        )
        titles = [hit.document_title for hit in outcome.results]
        expected = case.get("expected_documents", [])
        rank = next(
            (index for index, title in enumerate(titles, start=1) if title in expected),
            None,
        )
        if rank is not None:
            hits += 1
            reciprocal_rank += 1 / rank
        rows.append(
            {
                "id": case["id"],
                "expected": expected,
                "retrieved": titles,
                "rank": rank,
                "best_similarity": (
                    max((hit.similarity or 0.0) for hit in outcome.results)
                    if outcome.results
                    else None
                ),
                "unanswerable": bool(case.get("unanswerable")),
            }
        )
    answerable = [row for row in rows if not row["unanswerable"]]
    return hits / len(answerable), reciprocal_rank / len(answerable), rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="alpha-demo")
    parser.add_argument("--calibrate", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    cases = load_cases()
    embedder = build_embedder(settings)
    # Measure the reranker explicitly even when the runtime default is off; otherwise the
    # ON/OFF comparison would trivially compare two identical runs.
    reranker = retrieval.CrossEncoderReranker(
        settings.knowledge_reranker_model, settings.embeddings_cache_dir
    )
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.slug == args.tenant))
            if tenant is None:
                print(f"tenant {args.tenant!r} not found; seed it first")
                return 2
            bind_tenant(session, tenant.id)
            principal = Principal(
                subject="eval",
                issuer="eval",
                user_type="staff",
                roles=frozenset(),
                permissions=frozenset(),
                tenant_id=tenant.id,
            )
            hit, mrr, rows = run(session, principal, embedder, cases, reranker=reranker)
            hit_plain, mrr_plain, _ = run(session, principal, embedder, cases, reranker=None)
            answerable_count = sum(1 for case in cases if not case.get("unanswerable"))
            print(f"cases: {len(cases)} (answerable: {answerable_count})")
            print(f"rerank ON : hit@5={hit:.3f}  MRR={mrr:.3f}")
            print(f"rerank OFF: hit@5={hit_plain:.3f}  MRR={mrr_plain:.3f}")
            print(f"reranker gain: hit {hit - hit_plain:+.3f}, MRR {mrr - mrr_plain:+.3f}")
            if args.calibrate:
                print("\nid                         best_sim  unanswerable  rank")
                for row in rows:
                    similarity = row["best_similarity"]
                    shown = f"{similarity:8.3f}" if similarity is not None else "     nan"
                    print(
                        f"{row['id']:26} {shown}"
                        f"  {str(row['unanswerable']):>12}  {str(row['rank']):>4}"
                    )
                answerable = [
                    row["best_similarity"]
                    for row in rows
                    if not row["unanswerable"] and row["best_similarity"] is not None
                ]
                negative = [
                    row["best_similarity"]
                    for row in rows
                    if row["unanswerable"] and row["best_similarity"] is not None
                ]
                if answerable and negative:
                    low = max(negative)
                    high = min(answerable)
                    if high > low:
                        threshold = (low + high) / 2
                        retained = sum(1 for value in answerable if value >= threshold) / len(
                            answerable
                        )
                        not_found = sum(1 for value in negative if value < threshold) / len(
                            negative
                        )
                        print(
                            f"\nseparable: unanswerable max={low:.3f}, answerable min={high:.3f}; "
                            f"threshold={threshold:.2f}"
                        )
                        print(
                            f"at threshold: answerable retained={retained:.3f}, "
                            f"not-found rate on negatives={not_found:.3f}"
                        )
                    else:
                        print(
                            f"\nNOT separable on this demo set (unanswerable max={low:.3f}, "
                            f"answerable min={high:.3f}); do not set the threshold yet."
                        )
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
