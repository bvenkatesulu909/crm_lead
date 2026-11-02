# LLM usage and cost metrics per agent (CRM-111)

**Status:** design accepted 2026-11-02 (all three answers in section 5 as recommended). LM1 and LM2 built 2026-11-02 (sections 7 and 8); LM3 not started.
**Kind:** a small design, not an ADR: it adds a label and one read-only field. It changes none of
ADR 0016 (agent registry), 0017 or 0018.

## 1. What exists today

- At the model call (`app/modules/assistant/llm.py`, Claude and DeepSeek) every call is counted:
  `crm_ai_requests_total{provider,model,outcome}`, `crm_ai_request_duration_seconds{provider,model}`,
  `crm_ai_tokens_total{provider,model,direction}` and `crm_ai_estimated_cost_usd_total{provider,model}`
  (cost = tokens x the two prices in `CRM_AI_INPUT_PRICE_PER_MILLION` / `..._OUTPUT_...`; an estimate,
  not a bill).
- Per organisation and agent, `agent_usage` (ADR 0016) keeps the month's input and output tokens;
  the AI agents page shows them against the budget.
- Grafana has two panels ("AI calls by outcome", "AI tokens / cost") and Prometheus two alerts (AI
  failure spike, cost over 5 USD in an hour).

## 2. The gap

1. **Nobody can say which agent spent it.** There are five agents that call a model (staff assistant, portal
   assistant, website chat, knowledge answers, Qualifier) but the counters only
   know provider and model. "The Qualifier is expensive" or "the website chat is being abused" cannot
   be seen.
2. **Failures and slowness per agent are invisible**, for the same reason.
3. **The AI agents page shows tokens but no money**, although an administrator sets a token budget
   precisely to control cost.
4. The cost alert is per series; once there are more series it must add them up.

## 3. The change (small, no new table, no migration)

1. **An `agent` label on the four existing counters/histogram.** The agent registry's wrapper
   (`governed()`) already sits in front of every model call and knows the agent's key. It notes the key
   in a context variable for the length of the call; `observe_ai_call` reads it (`unknown` for a
   caller that is not governed, so nothing is lost). Five agents, so the label is bounded. No tenant
   label, no person, no text - the rule of ADR 0016 stays.
2. **Estimated cost on the AI agents API and page:** `GET /api/v1/agents` and `/{key}` get
   `estimated_cost_usd_this_month`, computed when read from the month's stored input and output tokens
   and the two prices (nothing new is stored). The page shows "about $0.42 this month (estimate)"
   next to the token bar. If no price is set the field is `null` and the page says nothing about money.
3. **Grafana:** the two panels get "by agent"; new panels for p95 latency and failures by agent.
4. **Alerts:** the cost alert sums over agents (same threshold); a new warning when one agent's
   failure share is high for 15 minutes.
5. **Docs:** `docs/agents.md` and the operations runbook explain the labels and what the cost
   estimate is not.

## 4. What stays out (on purpose)

- A real bill, per-organisation invoicing or a cost cap in money (the token budget stays the control).
- A tenant label on any metric (organisations must not be visible to each other or in a shared
  dashboard).
- Metering the local embedder (it has no price) and the scripted/fake models (they cost nothing).
- Different prices per model: one price pair in the environment, as today.

## 5. Questions for the owner (recommended answers first)

1. **Add an `agent` label to the existing AI metrics** (one source of truth), rather than a second
   set of per-agent counters? *Recommended: yes.*
2. **Show the estimated cost on the AI agents page** (tenant admins and sales managers who can read
   agents)? *Recommended: yes, marked as an estimate.*
3. **Keep one price pair for all models** (environment), and say so on the page? *Recommended: yes.*

## 6. Steps (each stops for review, tests first)

| Step | Content |
|---|---|
| LM1 (done) | Context variable in `governed()`, `agent` label in `observe_ai_call`, tests (each agent shows up under its own label; ungoverned = `unknown`; a failed call counts for its agent; no tenant or text in any label) |
| LM2 (done) | `estimated_cost_usd_this_month` in the agents API + the page, tests |
| LM3 | Grafana panels, alerts, docs, full runs |

## 7. What LM1 built (2026-11-02)

- `app/core/observability/metrics.py`: `ai_agent(name)` (a context variable, restored afterwards even
  after an error, different per thread; a name that is not short snake_case becomes `unknown`) and an
  `agent` label on `crm_ai_requests_total`, `crm_ai_request_duration_seconds`, `crm_ai_tokens_total`
  and `crm_ai_estimated_cost_usd_total`.
- `app/modules/agents/governed.py`: the wrapper sets the agent around the model call, so the five
  model-using agents (staff assistant, portal assistant, website chat, knowledge answers, Qualifier)
  show up under their own names, a failed provider call included. A call nobody wrapped is `unknown`.
- `infrastructure/monitoring/alerts.yml`: the hourly cost alert now sums over the agents (it would
  have fired per agent otherwise). Grafana panels are still LM3.
- Tests: `tests/test_llm_metrics.py` (pure, 17), `tests/db/test_llm_metrics_governed.py` (10).
  Five protections broken on purpose (no label set by the wrapper, label always `unknown`, name not
  validated, agent not restored, cost under the wrong agent) are all caught.

## 8. What LM2 built (2026-11-02)

- `app/modules/agents/cost.py`: `estimate_cost_usd(input_tokens, output_tokens, prices..., uses_model)`.
  A `Decimal`, rounded half up to four places; `None` for an agent without a model or when no price is
  set (so "$0" is never shown by mistake); negative token counts are refused.
- `GET /api/v1/agents` and `/{key}` have `estimated_cost_usd`, sent as text (`"0.4200"`) so no JSON
  float can change it. It is worked out when read from the month's stored tokens and the two prices
  of the server's settings: nothing new is stored, the client can send neither a price nor a cost
  (an update body that does is refused), and another organisation's usage never counts. Same
  permissions as the rest of the agents API (tenant admins and sales managers read).
- The AI agents page shows "Estimated cost this month: about $0.42 (an estimate from one price for all
  models, not a bill)" under the token bar; "less than $0.01" for tiny amounts, "$0.00" for none, and
  nothing at all without a price or for the web check. The cents are rounded on the digits of the text,
  not with floating point.
- Tests: 11 pure + 8 database tests (backend), 9 component tests (frontend, Vitest 507 in all). Ten
  protections broken on purpose (6 backend, 4 frontend) were all caught; one more break - building the
  decimal from the float instead of its text - cannot be seen at four places of money and is left out
  on purpose.
