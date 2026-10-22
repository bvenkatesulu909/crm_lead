"""Run the real grounded-answer evaluation (RAG R5). OPT-IN: this calls Claude and costs money.

    set CRM_RUN_LIVE_EVALS=1
    python -m scripts.eval_rag_answers --tenant alpha-demo

It asks every question in evals/rag/answer_cases.json, scores the real answer with the
deterministic metrics (groundedness, faithfulness, correctness, injection safety), prints a table
and exits non-zero if any case fails. The demo tenant must already be seeded
(python -m scripts.seed_knowledge_demo).
"""

import argparse
import dataclasses
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app import model_registry as _model_registry  # noqa: F401 - resolves cross-model FKs
from app.core.ai.embeddings import build_embedder
from app.core.auth.principal import Principal
from app.core.config import get_settings
from app.core.db import bind_tenant, create_db_engine, create_session_factory
from app.modules.assistant.llm import build_chat_model
from app.modules.identity.models import Tenant
from app.modules.knowledge import answers, evaluation, retrieval

BACKEND_DIR = Path(__file__).resolve().parents[1]
CASES_PATH = BACKEND_DIR / "evals" / "rag" / "answer_cases.json"
DEFAULT_RESULTS_DIR = BACKEND_DIR / "evals" / "rag" / "results"


def load_cases() -> list[dict[str, Any]]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("the evaluation dataset is empty")
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="alpha-demo")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--max-cases", type=int, default=100)
    args = parser.parse_args(argv)

    if os.environ.get("CRM_RUN_LIVE_EVALS") != "1":
        print("Refusing to spend money: set CRM_RUN_LIVE_EVALS=1 to run real-model evals.")
        return 2

    settings = get_settings()
    chat_model = build_chat_model(settings)
    if not chat_model.available:
        print("CRM_ANTHROPIC_API_KEY is not configured; cannot run live answer evals.")
        return 2

    cases = load_cases()[: max(1, args.max_cases)]
    embedder = build_embedder(settings)
    reranker = retrieval.build_reranker(settings)
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    failures = 0
    case_results: list[dict[str, Any]] = []
    print(f"{'case':22} {'ground':>7} {'faith':>7} {'correct':>8} {'inject':>7} {'doc':>5}")
    try:
        with factory() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.slug == args.tenant))
            if tenant is None:
                print(f"tenant {args.tenant!r} not found")
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
            for case in cases:
                outcome = answers.answer_question(
                    session,
                    principal,
                    embedder,
                    chat_model,
                    question=case["question"],
                    settings=settings,
                    reranker=reranker,
                )
                texts = [source.text for source in outcome.sources]
                score = evaluation.score_answer(
                    outcome.answer,
                    texts,
                    expected_facts=case.get("expected_facts", []),
                    forbidden_facts=case.get("forbidden_facts", []),
                )
                expected_docs = case.get("expected_documents", [])
                doc_hit = (
                    any(
                        title in source.document_title
                        for title in expected_docs
                        for source in outcome.sources
                    )
                    if expected_docs
                    else True
                )
                if case.get("injection"):
                    # Safety cases are judged on behaviour, not on citation style: refusing while
                    # quoting the poisoned instruction is correct, offering it is not.
                    ok = score.injection_safe
                    score = dataclasses.replace(score, correctness=1.0 if ok else 0.0)
                else:
                    ok = score.passed and doc_hit
                failures += 0 if ok else 1
                case_results.append(
                    {
                        "id": case["id"],
                        "groundedness": score.groundedness,
                        "faithfulness": score.faithfulness,
                        "correctness": score.correctness,
                        "injection_safe": score.injection_safe,
                        "document_hit": doc_hit,
                        "passed": ok,
                        "answer": outcome.answer,
                        "sources": [source.document_title for source in outcome.sources],
                    }
                )
                print(
                    f"{case['id']:22} {score.groundedness:7.2f} {score.faithfulness:7.2f} "
                    f"{score.correctness:8.2f} {str(score.injection_safe):>7} {str(doc_hit):>5}"
                )
    finally:
        engine.dispose()

    def mean(key: str) -> float:
        return (
            sum(float(row[key]) for row in case_results) / len(case_results)
            if case_results
            else 0.0
        )

    summary = {
        "groundedness": mean("groundedness"),
        "faithfulness": mean("faithfulness"),
        "correctness": mean("correctness"),
        "injection_safe": all(bool(row["injection_safe"]) for row in case_results),
        "document_hit": mean("document_hit"),
        "cases": len(case_results),
        "failures": failures,
    }
    baseline_regressions: list[str] = []
    if args.baseline is not None:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        for key in ("groundedness", "faithfulness", "correctness", "document_hit"):
            if summary[key] < float(baseline["summary"][key]) - 0.05:
                baseline_regressions.append(key)
        if baseline_regressions:
            failures += 1

    record = {
        "generated_at": datetime.now(UTC).isoformat(),
        "tenant": args.tenant,
        "dataset": str(CASES_PATH),
        "dataset_sha256": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
        "provider": settings.ai_provider,
        "model": (
            settings.deepseek_model
            if settings.ai_provider == "deepseek"
            else settings.assistant_model
        ),
        "settings": {
            key: getattr(settings, key)
            for key in (
                "knowledge_candidates",
                "knowledge_rrf_k",
                "knowledge_top_k",
                "knowledge_reranker_enabled",
                "knowledge_reranker_model",
                "knowledge_rerank_candidates",
                "knowledge_min_similarity",
            )
        },
        "summary": summary,
        "baseline_regressions": baseline_regressions,
        "passed": failures == 0,
        "cases": case_results,
    }
    output = args.output or (DEFAULT_RESULTS_DIR / f"live-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"\n{failures} failing case(s) of {len(cases)}; result: {output}")
    if baseline_regressions:
        print(f"baseline regression in: {', '.join(baseline_regressions)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
