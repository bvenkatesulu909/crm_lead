# R6 operations validation

- **Date:** 2026-10-21
- **Scope:** metrics, tracing configuration, health probes, AI usage/cost instrumentation,
  worker heartbeat, dashboards/alerts files.
- **Honesty rule:** items not executed are marked **not verified**, not "passed".

## Executed (commands + results)

| Check | Command | Result |
|---|---|---|
| Observability unit tests | `pytest tests/test_observability.py` | **7 passed** (metrics 404/401/200, no PII labels, AI token/cost metric, log redaction, health unaffected) |
| DB/metrics integration | included in the 7 | metrics endpoint with real DB: `crm_database_up 1`, pgvector extension+HNSW 1, heartbeat gauge, outbox/knowledge gauges |
| Health/readiness | `pytest tests/test_health.py tests/db/test_connection.py` | **17 passed** earlier; readiness now includes `vector: ok` |
| Full backend suite | `pytest -q` | **1056 passed, 4 skipped** (after R6; OpenAPI regenerated) |
| Metrics endpoint exposure | unit test | 404 without token, 401 wrong token, 200 with token; Grafana/Prometheus bind localhost only |
| Redaction | unit test | secret values `[REDACTED]`; no token patterns in logs |
| Worker heartbeat | DB test | heartbeat written and age gauge exposed |
| OpenTelemetry | configuration only | no collector run; tracing **not verified** end-to-end |
| Prometheus scrape | files provided | **not verified** against a running Prometheus |
| Alert delivery | rules + Alertmanager config provided | **not verified** with a controlled failure |
| Grafana dashboard | JSON provisioned and parsed (**9 panels**) | **not rendered/queried** in a live Grafana |
| Alert/Prometheus configs | YAML parsed: **10 rules / 4 groups**, 2 Alertmanager receivers, 1 scrape job | syntax validated; **not loaded into a live Prometheus** |
| DeepSeek failures/tokens/cost | **not implemented** | see gap G-01; metrics currently label `provider="anthropic"` |

## Controlled-failure tests still required (Phase 3 target)

1. Stop the worker → `CrmWorkerHeartbeatStale` fires (Prometheus → Alertmanager → test webhook).
2. Point the DB at an unreachable host → readiness 503 and `crm_database_up 0`.
3. Drop/rename the HNSW index in a scratch DB → `CrmPgvectorUnavailable`.
4. Fake AI timeout in a test double → failure counter, no PII in logs/traces.
5. Run a Grafana query for each dashboard panel and confirm data.
6. Verify alert recovery notifications.

## Residual risks

- Alert rules/dashboards are configuration, not yet proven on a live stack.
- Metrics are exposed by the API only; a dead API also hides worker/queue metrics (the scrape fails;
  add an external "API down" synthetic alert in the monitoring host).
- DeepSeek metrics cannot be honest until the provider decision is made.
- Estimated cost uses env prices; it is not an invoice.
