# R6 — Operations gap report (Phase 1)

- **Date:** 2026-10-21
- **Scope:** existing crm-lead repository; RAG add-on and the base CRM it runs inside.
- **Phase:** 1 (inspection and gap analysis) only. **No application code was changed.**
- **Method:** static inspection of the backend, frontend, Docker/infrastructure, CI, tests and
  deployment documentation. No metrics/tracing infrastructure exists to interrogate; nothing below
  is invented. Every current-state statement cites a file (and line where useful).
- **Related:** [ADR 0007](adr/0007-online-deployment.md) (deployment prepared, not deployed),
  [rag-runbook.md](rag-runbook.md), [deployment.md](deployment.md),
  [rag-eval.md](rag-eval.md), [PROGRESS.md](PROGRESS.md) R6 checklist.

---

## 1. Executive summary

**Three findings dominate:**

1. **The AI runtime in the code is Anthropic Claude, not DeepSeek.** There are **zero** references
   to DeepSeek anywhere in the repository; the dependency is `anthropic==1.15.0` and the settings
   are `CRM_ANTHROPIC_API_KEY` / `CRM_ASSISTANT_MODEL`. Phase 2's "DeepSeek failures, timeouts,
   tokens and cost" cannot be implemented honestly until the owner decides: keep Anthropic, or add
   a DeepSeek provider adapter (a feature change, with a key and its own data-processing decision).
2. **There is no runtime observability stack.** No Prometheus client, no `/metrics` endpoint, no
   OpenTelemetry SDK/exporter, no Grafana, no alert rules, no Alertmanager, no log shipper. The
   only operational signals today are JSON logs on stdout and two health endpoints.
3. **Several high-impact failures are silent:** worker death/stuck outbox, pgvector/index
   degradation, AI provider outage, retrieval/answer latency and token cost, and RAG not-found
   spikes have no metric or alert.

**What already exists and should be reused, not replaced:** structured JSON logging with a
validated `request_id`; a request access log with method/path/status/duration; liveness and
readiness endpoints (readiness really checks the DB); a container image with a liveness
HEALTHCHECK; PostgreSQL/Keycloak healthchecks in Docker; tenant-aware JSON logs; PII-aware error
responses (validation input is omitted); correct 503 behaviour when the AI is unconfigured.

---

## 2. Files inspected (evidence base)

Backend core/runtime:

- `backend/app/core/logging.py`, `request_context.py`, `errors.py`, `db.py`, `config.py`
- `backend/app/main.py`, `backend/app/api/v1/router.py`, `backend/app/api/v1/health.py`
- `backend/app/worker.py`, `backend/app/core/outbox.py`
- `backend/app/modules/assistant/llm.py`, `assistant/service.py`, `assistant/models.py`
- `backend/app/modules/knowledge/retrieval.py`, `answers.py`, `evaluation.py`,
  `service.py`, `api.py`, `router.py`
- `backend/requirements.txt`, `backend/Dockerfile`, `backend/.dockerignore`
- `backend/.env.example`

Tests and docs:

- `backend/tests/test_health.py`, `tests/test_cors.py`, `tests/db/test_connection.py`,
  `tests/db/test_knowledge_api.py`, `tests/test_knowledge_evaluation.py`
- `docs/deployment.md`, `docs/adr/0007-online-deployment.md`, `docs/rag-runbook.md`,
  `docs/rag-knowledge-base.md`, `docs/rag-eval.md`, `docs/PROGRESS.md` (R6), `CLAUDE.md`

Infrastructure/CI/frontend:

- `infrastructure/docker-compose.yml`, `infrastructure/postgres/Dockerfile`,
  `infrastructure/postgres/init/03-enable-pgvector.sh`, `infrastructure/.env.example`
- `.github/workflows/ci.yml`
- `frontend/package.json`, `frontend/src/lib/server/api.ts`, auth route handlers (console logs)

Commands used: targeted `grep` for `prometheus|opentelemetry|grafana|metrics|sentry`,
`deepseek|anthropic`, `health|ready`, `logger`; direct reads of the files above.

---

## 3. Current state by domain

| Domain | What exists (evidence) | What is absent |
|---|---|---|
| **Structured logging** | JSON formatter with timestamp/level/logger/message/request_id and `extra` fields (`core/logging.py:24-40`); uvicorn routed through it | No trace_id/span_id, no tenant/user/resource context, no redaction filter, no log levels policy per environment, no shipper/retention |
| **Correlation IDs** | `request_id` ContextVar, validated incoming `X-Request-ID`, response echo, access log with path/status/duration (`core/request_context.py:16-79`) | No W3C `traceparent` propagation; no worker/job correlation; frontend does not send/record the ID; query strings deliberately dropped (good, but no replacement context) |
| **Health** | `GET /api/v1/health` liveness; `GET /api/v1/health/ready` checks DB only (`api/v1/health.py:33-57`; `core/db.py:45-47`); Docker HEALTHCHECK uses liveness (`backend/Dockerfile:33-34`) | No pgvector extension/index check, no migration-version check, no S3/AI/embedder/reranker checks, no worker heartbeat, no queue health; readiness test only DB-down (`tests/test_health.py:48`) |
| **Metrics** | None. Business `metrics.py` modules are dashboard calculations, not telemetry. No `prometheus_client` in `requirements.txt`; no `/metrics` route | RED/USE metrics, RAG latency, AI failures/tokens/cost, DB pool/pgvector, worker/outbox, ingestion, budget, dashboards, alerts |
| **Tracing** | Log-only `request_id` | No OpenTelemetry API/SDK/exporter, no spans (HTTP → auth → DB → S3 → embeddings/reranker → AI), no sampling, no trace-log correlation |
| **AI runtime** | Anthropic Claude via SDK (`assistant/llm.py:56-103`); timeout 60 s + 2 retries (`llm.py:65-70`, `config.py:87`); APIError → 503 (`llm.py:90-95`); unconfigured → `UnconfiguredChatModel` (`llm.py:106-112`) | **DeepSeek is not present at all** (repo-wide grep: 0 matches); no token usage capture (`ModelReply` has text/tools/stop_reason only, `llm.py:30-45`); no cost, no per-call latency, no failure classification, no provider failover |
| **RAG runtime** | Retrieval/answer code paths exist (`retrieval.py`, `answers.py`); request-level duration in middleware (`request_context.py:71-78`) | No retrieval/rerank/generation latency metrics, candidate counts, score/refusal/not-found counters, reranker fallback counter, citation validation failures, context size |
| **Worker/outbox** | Claim/retry/dead logic and JSON logs `job done`/`job failed` with kind/attempt/dead/error type (`core/outbox.py:219-257`); worker loop catches/logs exceptions (`worker.py:148-164`) | No queue depth/oldest-job/retry/dead counters, no worker heartbeat, no stuck-processing detection, no schedule-failure metric, no alerting |
| **PostgreSQL/pgvector** | pgvector 0.8.7 image, extension enabled, HNSW/GIN indexes (migration 0021/0022); DB readiness ping; statement timeout in engine (`core/db.py:18-31`) | No extension/version/index/vector-dimension health probe, no connection-pool metrics, no slow-query capture, no replication/backup monitoring, no index bloat checks |
| **Dashboards/alerts** | None | Prometheus scrape configs, Grafana dashboards, alert rules, Alertmanager routes/receivers, escalation |
| **Deployment** | Container image prepared (`backend/Dockerfile`), Netlify web app, managed DB/S3/mail per ADR 0007; not deployed (D1 only) | No log drain, metrics scrape, alert destination, SLO/runbooks, on-call; deployment checklist leaves logs/backups manual (`deployment.md:155-159`) |
| **Secrets/PII** | Key never sent to browser; error responses omit rejected input (`errors.py:122-129`); access log excludes query string (`request_context.py:70`); docs state no PII in logs | No automated redaction filter for arbitrary `extra`/exception text; no allowlist for metric labels/trace attributes; no test that secrets/PII never appear; no policy for prompts sent to a provider (Anthropic today, DeepSeek proposed) |
| **Frontend** | `console.error` in a few server paths (`frontend/src/lib/server/api.ts:49`, auth callbacks) | No error reporting/RUM, no request-id capture/display, no client latency/error metrics |
| **CI** | Backend/frontend test jobs; health tests; no secrets | No observability tests, no metric-scrape test, no dashboard/alert validation, no load/latency budgets |

---

## 4. Gap register

Severity: **Critical** = production-blocking or silent data/AI failure; **High** = operating blind on
a core path; **Medium** = degraded diagnosis or compliance risk; **Low** = improvement.

### G-01 — AI provider mismatch (DeepSeek vs Anthropic)
| Field | Detail |
|---|---|
| Component | AI runtime / generation |
| Current state + evidence | Anthropic SDK and settings only (`requirements.txt:25-27`, `config.py:75-87`, `assistant/llm.py:56-103`); repository-wide search for "deepseek" returns **0 matches**; `.env.example` documents `CRM_ANTHROPIC_API_KEY` |
| Missing | DeepSeek client/adapter, key handling, provider selection, usage/cost model for DeepSeek |
| Severity | **Critical (scope decision)** |
| Recommended action | Owner decision: (a) keep Anthropic and monitor it, or (b) add a provider-neutral `ChatModel` adapter with `DeepSeekChatModel` (OpenAI-compatible endpoint) behind `CRM_AI_PROVIDER`, keep Anthropic working, no key in repo. Only then instrument usage/failures per provider |
| Acceptance criteria | A documented decision; if (b), fake-client tests for DeepSeek success/timeout/API error and usage capture; no secret in logs; Anthropic path unaffected |
| Status | **Blocked on decision** |

### G-02 — No Prometheus metrics endpoint or instrumentation
| Field | Detail |
|---|---|
| Component | API/worker |
| Current state + evidence | No `prometheus_client` in `requirements.txt`; grep finds no metrics/tracing library; `api/v1/router.py` includes health + business routers only |
| Missing | Private `/metrics` endpoint, registry, HTTP/DB/job/RAG/AI instruments |
| Severity | **Critical** |
| Recommended action | Add `prometheus-client`; create `app/core/observability/metrics.py`; expose metrics only on a private listener or a token-guarded internal route; instrument middleware and key services |
| Acceptance criteria | Scrape returns 200 with expected metric families; endpoint is not public/anonymous; metric tests pass; no high-cardinality labels |
| Status | Missing |

### G-03 — Retrieval and generation latency not measured
| Field | Detail |
|---|---|
| Component | RAG (search / answer) |
| Current state + evidence | Only whole-request `duration_ms` is logged (`core/request_context.py:71-78`); `retrieval.py`/`answers.py` have no timers or counters |
| Missing | Stage latency histograms: embed query, vector SQL, keyword SQL, RRF, rerank, prompt build, model call, total; candidate/result counts |
| Severity | **High** |
| Recommended action | Wrap retrieval stages and answer generation with Prometheus histograms (seconds) and counters by outcome; add OTel spans |
| Acceptance criteria | Dashboard shows p50/p95/p99 per stage; tests assert observations; no question text/labels |
| Status | Missing |

### G-04 — AI token consumption, cost and failure telemetry absent
| Field | Detail |
|---|---|
| Component | AI generation |
| Current state + evidence | `ModelReply` has no usage (`assistant/llm.py:30-45`); Anthropic response usage is not read (`llm.py:96-103`); only one generic warning on APIError (`llm.py:90-95`); no price table; no DeepSeek path |
| Missing | Counters for calls/failures/timeouts/rate limits by provider/model; input/output token counters; estimated-cost counter; budget alert |
| Severity | **High** |
| Recommended action | Extend the reply type with usage, read provider usage, add counters/histogram (labels: provider, model, outcome; never prompt/model output), configurable price per 1K tokens, budget alert rule |
| Acceptance criteria | Fake-client tests for success/timeout/API error produce expected counters; estimated cost computed and exported; no key/prompt in metrics or logs |
| Status | Missing |

### G-05 — No distributed tracing
| Field | Detail |
|---|---|
| Component | API → DB/S3 → embeddings/reranker → AI; worker jobs |
| Current state + evidence | No OpenTelemetry dependency; no traceparent handling; `request_id` only (`request_context.py`); worker logs carry no correlation ID |
| Missing | OTel SDK/instrumentation, trace context propagation (HTTP + outbox jobs), spans, exporter, sampling, log-trace correlation |
| Severity | **High** |
| Recommended action | Add OTel FastAPI/SQLAlchemy/httpx instrumentation, a provider-agnostic OTLP exporter (env-driven, disabled by default), trace IDs in logs, propagate traceparent into outbox payload or job context |
| Acceptance criteria | One request produces an end-to-end trace across DB and AI spans; logs include trace_id; sampling configurable; no PII attributes |
| Status | Missing |

### G-06 — Logging is structured but not operationally complete
| Field | Detail |
|---|---|
| Component | Logging |
| Current state + evidence | JSON + request_id exists (`logging.py:24-40`, `request_context.py:32-45`); path-only access logs (`request_context.py:70`); no redaction filter |
| Missing | trace/span IDs; tenant/user/resource IDs; worker/job correlation; redaction allowlist; log retention/shipping; frontend correlation |
| Severity | **High** |
| Recommended action | Extend formatter with trace/span and safe context; add a redaction filter for secret-ish keys and token patterns; document retention; do not log query text/document text/prompts |
| Acceptance criteria | Tests prove password/API key/PII patterns are redacted; logs remain JSON; no cardinality explosion |
| Status | Partial |

### G-07 — Health/readiness is shallow
| Field | Detail |
|---|---|
| Component | API health; worker health |
| Current state + evidence | Liveness + DB-only readiness (`health.py:33-57`); Docker HEALTHCHECK liveness (`Dockerfile:33-34`); worker has no health endpoint |
| Missing | pgvector extension/version/index check, migration version, S3 optional check, embedder/reranker availability, worker heartbeat, outbox depth, dependency timeouts/caching |
| Severity | **High** |
| Recommended action | Keep `/health` minimal; extend readiness with DB + pgvector + schema version (bounded timeout); add an internal authenticated dependency endpoint for S3/AI; add worker heartbeat (DB row) and a private health port |
| Acceptance criteria | Controlled failures produce 503 on the right probe and do not flap; tests for DB down, extension missing, stale worker; probes bounded and non-public beyond minimal info |
| Status | Partial |

### G-08 — Worker/outbox observability missing
| Field | Detail |
|---|---|
| Component | Worker / outbox |
| Current state + evidence | Job done/failure logs only (`outbox.py:230-257`); no metrics; no heartbeat; loop exceptions logged (`worker.py:148-164`) |
| Missing | Queue depth, oldest pending age, retries/dead counters, claims, schedule failures, worker heartbeat/age, stuck `processing` documents |
| Severity | **High** |
| Recommended action | SQL gauges scraped by worker/API; counters for jobs by kind/outcome; heartbeat row with timestamp; alerts on dead jobs/queue age/heartbeat |
| Acceptance criteria | Killing the worker raises an alert within threshold; dead jobs visible; tests with controlled failures |
| Status | Missing |

### G-09 — PostgreSQL/pgvector operational monitoring missing
| Field | Detail |
|---|---|
| Component | Database / pgvector |
| Current state + evidence | Connectivity ping only (`db.py:45-47`, `health.py:49-56`); engine statement timeout configured (`db.py:18-31`); no extension/index health |
| Missing | pgvector version, HNSW/GIN index presence, vector dimensions/model drift, missing chunks/stale processing, pool metrics, slow queries, backup/replication status |
| Severity | **High** |
| Recommended action | Bounded SQL probes for extension/version/index; chunk consistency gauges; pool instrumentation; slow-query log setting documented; rely on managed DB metrics for backups/replication; alert on probe failure |
| Acceptance criteria | Removing/misconfiguring pgvector is detected by a probe and alert; dashboard shows index/extension status; no expensive query on every request |
| Status | Missing |

### G-10 — No dashboards, alert rules or Alertmanager
| Field | Detail |
|---|---|
| Component | Monitoring |
| Current state + evidence | No Prometheus/Grafana/Alertmanager in `infrastructure/docker-compose.yml` (only postgres/keycloak/mailpit/files); no rules/dashboards files |
| Missing | Scrape configs, dashboards, alert rules, routing/receivers, runbook links |
| Severity | **Critical** |
| Recommended action | Add provisioning files; local/staging profile with Prometheus + Grafana + Alertmanager (or managed equivalent); alerts: API 5xx/latency, AI failure/cost, worker heartbeat/queue, DB/pgvector, ingestion failures, not-found spike |
| Acceptance criteria | Dashboard queries render real data; controlled failures fire alerts to a test receiver; no public Grafana anonymous access |
| Status | Missing |

### G-11 — No alert delivery, escalation or ops runbooks
| Field | Detail |
|---|---|
| Component | Operations process |
| Current state + evidence | `deployment.md:155-159` lists backups/log checks as manual go-live TODOs; no on-call/escalation documents |
| Missing | Receivers, severity routing, escalation, runbooks per alert, ownership |
| Severity | **High** |
| Recommended action | Define Alertmanager receivers (email/chat), severity routing, runbooks; test with controlled failures |
| Acceptance criteria | Each alert has a runbook link; test alert delivered end-to-end; ownership recorded |
| Status | Missing |

### G-12 — Metrics/label cardinality and PII policy not enforced
| Field | Detail |
|---|---|
| Component | Observability data |
| Current state + evidence | No metric labels yet; existing logs deliberately omit query string (`request_context.py:70`); no automated redaction |
| Missing | Allowlist for labels/trace attributes; tests forbidding question/document/tenant values; redaction filter |
| Severity | **High** |
| Recommended action | Code-level label constants (route template, method, status class, job kind, provider, outcome); security tests that scrape/inspect metrics and assert no PII/secrets; document the policy |
| Acceptance criteria | Automated test fails if a prohibited label is added; metrics cardinality bounded; no tenant/user/query labels |
| Status | Missing |

### G-13 — Monitoring endpoints exposure policy missing
| Field | Detail |
|---|---|
| Component | Security |
| Current state + evidence | Health endpoints are deliberately public (`health.py:5-7`); no metrics endpoint; deployment uses public HTTPS hosts |
| Missing | Private scrape path/auth, network policy, docs |
| Severity | **High** |
| Recommended action | Metrics on a private port or token-protected route; never expose Grafana/Prometheus publicly; minimal public health payload |
| Acceptance criteria | Unauthenticated public request cannot read metrics; scrape from monitoring network succeeds; test asserts 401/404 publicly |
| Status | Missing |

### G-14 — Frontend/client observability missing
| Field | Detail |
|---|---|
| Component | Next.js frontend |
| Current state + evidence | Only `console.error` in server helpers (`frontend/src/lib/server/api.ts:49`, auth routes); no RUM/error reporting |
| Missing | Server error reporting, client error capture, request-id correlation/display |
| Severity | **Medium** |
| Recommended action | Structured frontend logs with request id; forward/echo `X-Request-ID`; optional error reporting behind env; no PII |
| Acceptance criteria | A failed page/API call is traceable to backend request id; no tokens in browser logs |
| Status | Missing |

### G-15 — Log aggregation and retention absent
| Field | Detail |
|---|---|
| Component | Logging platform |
| Current state + evidence | stdout JSON only; no log shipper; deployment leaves logs to host |
| Missing | Central retention/search, PII-safe retention policy, alerting on log patterns |
| Severity | **Medium** |
| Recommended action | Use host log drain or Loki-compatible shipper; retention documented; avoid raw document/prompt logs |
| Acceptance criteria | Logs searchable across API and worker with retention; policy documented |
| Status | Missing |

### G-16 — Backup/RPO/RTO and data-integrity monitoring not automated
| Field | Detail |
|---|---|
| Component | Database/files |
| Current state + evidence | Local backup commands exist in `rag-runbook.md`; deployment checklist says "backups on, restore tested" manually (`deployment.md:155`); no scheduled verification |
| Missing | Backup success/freshness metric, restore drill schedule, RPO/RTO targets |
| Severity | **High** |
| Recommended action | Use managed DB backup metrics; add freshness probe; document restore drill; alert on stale backup |
| Acceptance criteria | Backup age visible; stale backup alerts; restore drill record |
| Status | Missing |

### G-17 — CI does not gate observability
| Field | Detail |
|---|---|
| Component | CI |
| Current state + evidence | `.github/workflows/ci.yml` runs lint/mypy/pytest/frontend; no observability tests |
| Missing | Metric scrape tests, redaction tests, alert-rule tests (promtool), dashboard JSON validation, cold-start health |
| Severity | **Medium** |
| Recommended action | Add monitoring test suite to CI; keep it fast and dependency-light |
| Acceptance criteria | A regression in metrics/redaction/alert rules fails CI |
| Status | Missing |

### G-18 — No cost budget/quota alerting
| Field | Detail |
|---|---|
| Component | AI cost |
| Current state + evidence | No token/cost capture; no budget config; assistant rate limit exists (30/hour) but is not a metric (`assistant/service.py:204`) |
| Missing | Cost metric, budget threshold, quota/rate-limit counters, alert |
| Severity | **High** |
| Recommended action | Price table via env; estimated cost counter; budget alert; expose rate-limit rejections |
| Acceptance criteria | Cost per answer visible; crossing test threshold fires alert; rate-limit metric tested |
| Status | Missing |

### G-19 — RAG quality/not-found operational monitoring missing
| Field | Detail |
|---|---|
| Component | RAG quality |
| Current state + evidence | Evaluation is offline (`evaluation.py`, `scripts/eval_rag_answers.py`); no runtime not-found/refusal/citation-rejection metrics; no knowledge-gaps report |
| Missing | Counters for searches, empty results, refusals, ungrounded rejections, citations per answer; weekly gap report |
| Severity | **High** |
| Recommended action | Instrument outcomes (no query text); schedule a gap report from aggregate counters/audit-safe data |
| Acceptance criteria | Dashboard shows not-found/refusal rates; alert on spike; no question text stored in metrics |
| Status | Missing |

### G-20 — Ingestion/freshness monitoring missing
| Field | Detail |
|---|---|
| Component | Knowledge ingestion |
| Current state + evidence | Ingestion sets statuses and job logs (`knowledge/service.py`, `worker.py`); no metrics; R6 freshness checks absent |
| Missing | Processing age/stuck, failure-rate, documents without chunks, old embedding model, ingestion latency |
| Severity | **High** |
| Recommended action | SQL gauges + job counters; alert on stuck processing and failures; nightly consistency check |
| Acceptance criteria | A stuck/failed ingestion is visible and alerts; consistency check reports green |
| Status | Missing |

### G-21 — RLS coverage is incomplete (security/operations risk)
| Field | Detail |
|---|---|
| Component | Data isolation |
| Current state + evidence | RLS enforced on knowledge tables only (migration 0022); other tenant tables pending (ADR 0009 staged) |
| Missing | Full RLS rollout, worker BYPASSRLS role, monitoring for unexpected cross-tenant access |
| Severity | **High (security), out of R6 core** |
| Recommended action | Complete staged RLS before real customer data; add audit alerts for 403/404 anomalies |
| Acceptance criteria | RLS on every tenant table; worker role; isolation tests |
| Status | Partial (outside this R6 phase) |

---

## 5. Operational risk summary

| Risk | Impact | Likelihood today | Detection today |
|---|---|---|---|
| Worker stops / outbox stuck | Documents stay "processing", e-mails/notifications never sent | Medium | None (manual DB inspection) |
| AI provider outage/timeout | Answers return 503; users see failures | Medium | Generic 503 + one warning log |
| Runaway AI spend | Unexpected bill | Medium | None |
| pgvector extension/HNSW missing after migration | Search degrades or errors | Low–Medium | Readiness still green (DB ping only) |
| DB connection pool exhaustion | 5xx/latency | Medium | Request logs only |
| PII/secret in logs/traces/metrics | Compliance breach | Low if discipline holds; no automation | None |
| Provider mismatch (DeepSeek assumed) | Phase 2 instruments a provider that is not deployed | High until decided | Not applicable |
| Log/backup loss | No postmortem data / data loss | Medium | Manual |

---

## 6. Decisions required before Phase 2 (owner)

1. **AI provider:** keep Anthropic Claude (current code), or add DeepSeek as a second provider
   behind the existing `ChatModel` interface (recommended if DeepSeek is a hard requirement). This
   decides which token/cost/failure metrics are meaningful. No key will be committed in either case.
2. **Monitoring topology:** self-hosted Prometheus + Grafana + Alertmanager (compose profile for
   local/staging) **or** managed Grafana Cloud/Prometheus. Default proposal: self-hosted compose
   profile, with environment variables for hosted endpoints.
3. **Metrics exposure:** private port vs token-protected internal route. Default proposal: private
   port on the API/worker services, never public.
4. **Tracing backend:** OTLP endpoint (Tempo/Jaeger/hosted) or tracing disabled by default. Default:
   disabled unless `CRM_OTEL_EXPORTER_OTLP_ENDPOINT` is set.
5. **Retention/alerts:** log retention days, cost budget, on-call destination.
6. **AI cost approval:** any live Claude/DeepSeek eval or dashboard test that calls the model is
   paid; requires explicit approval (same rule as R5 live evals).

---

## 7. Proposed Phase 2 implementation plan (after review)

**Principle:** reuse the existing modular monolith and container image; add libraries and small
modules, not new services. Monitoring infrastructure gets its own compose profile and can be
omitted in environments that use a managed equivalent.

### P2.1 Foundation
- Settings (env-only): `observability_enabled`, `metrics_port`/token, `otel_endpoint`,
  `otel_sample_ratio`, `ai_provider`, token prices, budget, alert receiver.
- New `app/core/observability/`:
  - `metrics.py`: private `CollectorRegistry`, metric definitions with fixed low-cardinality labels;
  - `tracing.py`: OTel setup (no-op when disabled), resource service.name/version;
  - `redaction.py`: log/attribute redaction allowlist;
  - `instrumentation.py`: FastAPI/httpx/SQLAlchemy hooks.
- Add dependencies: `prometheus-client`, OpenTelemetry API/SDK + FastAPI/SQLAlchemy/httpx
  instrumentation, OTLP exporter. Pin exactly; update `requirements.txt`.

### P2.2 Correlation and safe logging
- Extend request context with W3C `traceparent` (generate/accept valid), trace_id/span_id.
- JSON logs gain trace/span IDs and safe route template/user-type (never tenant name, query text,
  document text, prompts, tokens, secrets).
- Redaction filter tested for `authorization`, `api_key`, `password`, `token`, card/e-mail/phone
  patterns.
- Frontend: propagate/record `X-Request-ID`; optional server error reporting behind env.

### P2.3 HTTP + dependency instrumentation
- Middleware: request counter/histogram by route template, method, status class; exception counter.
- Health: keep liveness; readiness adds bounded DB + pgvector extension/version + schema revision;
  internal authenticated dependency probe for S3/AI with cached result; worker heartbeat.
- Private metrics server (API + worker) or token-guarded internal route.

### P2.4 AI, retrieval and answer instrumentation
- Extend `ModelReply` with usage; provider adapters expose usage consistently (Anthropic now,
  DeepSeek if chosen); call/timeout/failure counters; latency histogram; token counters; estimated
  cost counter (env price table); no prompts/outputs in labels or logs.
- Retrieval spans/metrics: embed, vector candidates, keyword candidates, RRF, rerank (duration +
  fallback), result counts, best similarity, threshold/refusal, ungrounded rejection, citations.
- Worker job metrics/gauges and heartbeat; ingestion status gauges; outbox queue age/depth; dead jobs.

### P2.5 DB/pgvector and consistency probes
- Bounded SQL probes: `pg_extension`, HNSW/GIN index presence, vector dimensions/model drift, chunks
  with missing embeddings, stuck processing, index bloat (read-only); expose gauges.
- Pool metrics via SQLAlchemy events; slow-query log setting documented (not a new service).
- Backup freshness from managed DB metrics or a documented backup-age probe.

### P2.6 Dashboards, alerts, runbooks
- Provisioned Grafana dashboard(s): API/RAG/AI/worker/DB, with links to runbooks.
- Prometheus alert rules + Alertmanager config (test receiver in local profile): API 5xx/p95,
  AI failure/timeout/cost budget, worker heartbeat/queue age/dead jobs, ingestion failures,
  DB/pgvector down or missing index, not-found spike, missing citations.
- Runbooks per alert; retention/escalation documented.

### P2.7 Safety and exposure
- No public metrics/Grafana; minimal public health payload; no secrets/PII in labels, logs, traces;
  tests enforce allowlists; metrics endpoint auth tested.

**Estimated file impact:** ~6 new backend modules/files, ~10 modified instrumentation touchpoints,
new `infrastructure/monitoring/` (compose profile + provisioning), docs (runbooks, validation),
tests. No database migration expected except possibly a worker heartbeat table (small migration);
no change to auth, permissions, or existing endpoints.

---

## 8. Phase 3 validation plan (to implement after Phase 2)

1. **Unit/integration tests** (pytest + `prometheus_client` test registry):
   - request counter/histogram values after TestClient calls; route templates (not IDs) in labels;
   - redaction tests for secrets/PII patterns;
   - AI fake client: success/timeout/API error/rate limit/usage/cost counters;
   - retrieval/answer metrics: empty results, refusal, ungrounded rejection, reranker fallback;
   - worker metrics with controlled job failures + heartbeat age;
   - health probes: DB down, pgvector missing, migration mismatch, stale worker; bounded time;
   - metrics endpoint: 401/404 publicly, 200 on private path; no PII/tenant labels.
2. **Dashboard/alert validation:** `promtool check rules`, dashboard JSON schema/query presence;
   controlled failure (stop worker, revoke DB, fake AI timeout) fires the expected alert to a local
   webhook receiver; verify recovery notification.
3. **Operational validation:** runbooks executed once (start stack, break worker/DB, observe alerts,
   recover); record evidence in `docs/r6-operations-validation.md`.
4. **Performance budget check:** one query's stage latencies under threshold; no metric cardinality
   explosion (assert label cardinality).
5. **CI:** add the fast monitoring test suite; keep live AI calls out of CI.

---

## 9. Phase 1 status

- Repository inspected; evidence recorded above.
- **No application code, dependency, configuration or infrastructure change was made.**
- This document is the only new file.
- Phase 2 must wait for the owner's answers to section 6 (especially **DeepSeek vs Anthropic** and
  the monitoring topology), plus review of this report.
