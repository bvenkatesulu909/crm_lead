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
| CrmAiAgentFailing | one AI agent fails >30 % of its calls for 15 min (at least 5 calls) | which `agent` label; provider status; is the agent switched off or over budget? |
| CrmAiCostBudget | estimated spend >$5/h (all agents added up) | cost by agent panel; then budget/prompt size |
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
1. `crm_ai_requests_total{outcome!="ok"}` by model and by agent; 503 responses mean
   unconfigured/timeout.
2. Confirm `CRM_ANTHROPIC_API_KEY` (or `CRM_DEEPSEEK_API_KEY` for DeepSeek) is set in the host's
   secret store (never in logs/repo).
3. If only one agent fails, see [AI agent](#ai-agent) below.

## AI agent {#ai-agent}
Every AI metric (`crm_ai_requests_total`, `crm_ai_request_duration_seconds`, `crm_ai_tokens_total`,
`crm_ai_estimated_cost_usd_total`) has an `agent` label: `staff_assistant`, `portal_assistant`,
`public_chat`, `knowledge_answers`, `qualifier` (`unknown` = a call that was not made through the agent
registry - that should not happen; look at the code that made it).
1. Open the dashboard row "by agent": cost, tokens, p95 latency, failed calls, refused calls.
2. Failed calls for one agent only: provider outage for that model, a wrong key for that agent's
   provider, or a prompt that now exceeds the model's limit. The refusals panel
   (`crm_ai_refusals_total{agent,reason}`) shows calls that never reached the model (agent switched off,
   platform switch, budget reached) - those are decisions, not failures.
3. An administrator sees the same agent on the AI agents page (switch, monthly token budget, tools,
   tokens used and an estimated cost). There is no tenant label on any metric on purpose: to find out
   WHICH organisation used the tokens, an administrator looks at that page for their own organisation.

## AI cost {#ai-cost}
1. `crm_ai_estimated_cost_usd_total` is an **estimate** from env prices, not a bill. One price pair
   (`CRM_AI_INPUT_PRICE_PER_MILLION`, `CRM_AI_OUTPUT_PRICE_PER_MILLION`) applies to every model.
2. The panel "AI cost by agent" says which agent spent it. Check that agent's token counts, its
   rate limits and, for the assistants, the length of the prompt and of the tool results.
3. To stop the spending without a deployment: switch the agent off (AI agents page) or lower its
   monthly token budget; the platform switch `CRM_AI_DISABLED` stops all of them.

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
