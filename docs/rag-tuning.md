# RAG tuning log (R5)

One setting at a time, measured on the versioned datasets. Do not change prompt + model +
threshold together. Free retrieval runs use real local models; paid answer runs require the
`rag-live-eval` environment approval.

## Baseline — 2026-10-21

Datasets: `backend/evals/rag/retrieval_cases.json` (100 cases: 80 answerable, 20 unanswerable)
and `answer_cases.json` (4 paid answer cases, executed).

| Measurement | Value | Source |
|---|---|---|
| Retrieval hit@5 | **1.000** | `scripts/eval_retrieval.py` (100 cases) |
| Retrieval MRR | **1.000** | same (reranker off) |
| Reranker ON vs OFF | hit +0.000, MRR **−0.021** | same (100 cases) |
| Reranker decision | **disabled by default**; re-evaluate at 100 cases | ADR 0011: no measured gain |
| Unanswerable max similarity | 0.570 | `--calibrate` |
| Answerable min similarity | 0.704 | same |
| `knowledge_min_similarity` | **0.64 enforced** | separation 0.620/0.658; 100% retention + 100% not-found |
| Paid answer eval (DeepSeek `deepseek-chat`, 4 cases, reranker OFF) | groundedness 0.917, faithfulness 1.000, correctness 1.000, injection safe, doc-hit 1.000 (**4/4**) | `live-20261021T071621Z.json` |
| Faithfulness/groundedness/correctness | not measured live | paid suite |

## Decisions

- **Reranker:** keep enabled for now; no measured gain on 8 documents. Re-measure on 100 cases before
  deciding to drop it (ADR 0011 says the decision is measurement-driven).
- **Threshold:** do not enforce 0.64 yet. Two unanswerable cases are not enough evidence; the
  current `None` default keeps behaviour unchanged.
- **Model/chunking:** unchanged.

## How to update this log

1. Run `python -m scripts.eval_retrieval --tenant alpha-demo --calibrate` (free) and record the
   retrieval numbers.
2. For an approved paid run: `CRM_RUN_LIVE_EVALS=1 python -m scripts.eval_rag_answers --tenant ...`
   and record groundedness / faithfulness / correctness / injection / document hit from the JSON
   result. Use `--baseline <previous.json>` for the regression gate.
3. Change **one** setting, rerun both suites, record before/after here, then update the code default
   (or revert).
