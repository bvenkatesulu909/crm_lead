# R6 operations runbook

Operational actions for the crm-lead API, worker and RAG pipeline. Alerts link here by anchor.

## Metrics and dashboards

- Metrics: `GET /api/v1/internal/metrics` with `Authorization: Bearer <CRM_METRICS_TOKEN>`.
  Without a configured token the route is 404; with a wrong token it is 401.
- Local stack: `cd infrastructure/monitoring`, copy `metrics_token.example` to `metrics_token`
  and put the same value in `backend/.env` as `CRM_METRICS_TOKEN`; set
  `GRAFANA_ADMIN_PASSWORD`; then `docker compose -f docker-compose.monitoring.yml up -d`.
- Prometheus: http://127.0.0.1:9090 · Grafana: http://127.0.0.1:3000 · Alertmanager: 127.0.0.1:9093
  (all bound to localhost; do not expose them publicly).
- Prometheus needs a **reachable API** at host.docker.internal:8000; run the API locally.

## Alerts

| Alert | What it means | First check |
|---|---|---|
| CrmApiHighErrorRate | >5% 5xx | API logs by `request_id`; readiness 503? DB? |
| CrmApiSlowRequests | p95 >2 s | DB latency, pgvector HNSW, reranker cold load |
| CrmAiFailureSpike | AI error/timeout rate | provider status, `crm_ai_requests_total`, API key/quota |
| CrmAiCostBudget | estimated spend >$5/h | usage by model; check budget/prompt size |
| CrmWorkerHeartbeatStale | no heartbeat >120 s | worker process running? logs? DB reachable? |
| CrmOutboxBacklog | >100 pending jobs | worker alive? slow handlers? DB locks? |
| CrmJobsDead | job gave up | `outbox_jobs.last_error`/kind; fix cause then requeue |
| CrmPgvectorUnavailable | extension/HNSW missing | run migration 0021; `CREATE EXTENSION vector` |
| CrmChunksMissingEmbeddings | chunks without vector | worker ingestion failure; re-ingest documents |
| CrmAnswerUngroundedSpike | answers rejected for citations | prompt/model change; check eval suite |

## API errors {#api-errors}
1. Find the response `request_id`; search JSON logs: `grep <request_id>`.
2. Check `GET /api/v1/health/ready` (DB + pgvector) and the database dashboard.
3. 5xx from one route → release regression; from all routes → dependency (DB/S3/IdP).

## Latency {#latency}
1. `crm_rag_stage_duration_seconds` separates retrieval vs answer.
2. First search after deploy loads the cross-encoder; later searches should be faster.
3. HNSW growth: check index size/tenant volume before tuning `ef_search`.

## AI provider {#ai-provider}
1. `crm_ai_requests_total{outcome!="ok"}` by model; 503 responses mean unconfigured/timeout.
2. Confirm `CRM_ANTHROPIC_API_KEY` is set in the host's secret store (never in logs/repo).
3. DeepSeek is **not implemented**; see the gap report decision G-01. Do not point these
   metrics at a provider that is not deployed.

## AI cost {#ai-cost}
1. `crm_ai_estimated_cost_usd_total` is an **estimate** from env prices, not a bill.
2. Check token counts per model and the assistant rate limit; set the budget alert threshold.

## Worker {#worker}
1. `crm_worker_heartbeat_age_seconds`; if stale, restart the worker service.
2. Inspect `outbox_jobs` by status; dead jobs keep `last_error` (safe error text only).
3. Requeue a dead job only after fixing the cause (update status/locked_at deliberately).

## pgvector {#pgvector}
1. `SELECT extversion FROM pg_extension WHERE extname='vector';`
2. Index: `SELECT indexname FROM pg_indexes WHERE indexname='ix_kb_chunks_embedding_hnsw';`
3. If missing, run `alembic upgrade head`; never create the extension in a migration.

## Ingestion {#ingestion}
1. `crm_knowledge_documents{status="processing"}` stuck → worker; `failed` → file format.
2. `crm_knowledge_chunks_missing_embedding` >0 → embedding model failure; re-run ingestion.

## RAG quality {#rag-quality}
1. Ungrounded answers mean citations failed validation; inspect recent prompt/model change.
2. Run `python -m scripts.eval_rag_answers` (paid, opt-in) and the free metric tests.
3. Never log questions or document text; use evaluation fixtures.

## Secret / PII incident
1. Rotate the affected key (Anthropic/Keycloak/S3/SMTP) in the host secret store.
2. Search logs for the pattern only in a secure environment; delete affected log retention.
3. Do not paste documents/prompts into tickets or chat.
