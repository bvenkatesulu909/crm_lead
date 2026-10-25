# ADR 0016 — Agent registry, monthly budgets and a kill switch (BP-14)

- **Status:** Proposed (2026-10-26) — waits for the owner's review; no code until approved
- **Date:** 2026-10-26
- **Deciders:** Project owner
- **Depends on:** ADR 0002 (tenant from the verified identity), ADR 0003 (AI assistant
  foundations), ADR 0009 (row-level security), ADR 0013 (public chat), ADR 0014 (approval queue)
- **Part of:** AI Track A2 (governance). BP-09 (usage and cost per tenant) builds on it.

## 1. The problem

Four places in the CRM call a language model, and nothing can stop or limit them centrally:

| Agent | Where the model is called | Who triggers it |
|---|---|---|
| `staff_assistant` | `assistant/staff_service.py` | a signed-in staff member |
| `portal_assistant` | `assistant/service.py` | a signed-in portal customer |
| `public_chat` | `public_chat/service.py` | an anonymous website visitor |
| `knowledge_answers` | `knowledge/answers.py` | a staff member or customer asking the knowledge base |

If a provider key leaks, a prompt loop runs, a bot floods the public chat or a feature misbehaves,
the only remedies today are changing environment variables and restarting the API. There is no
per-organisation limit, no list of which AI features exist and who is responsible for them, and no
way to narrow what tools an agent may use without a code change. The evaluation harness (BP-10)
proved the behaviour of the agents; it cannot switch one off.

## 2. Decisions

**D1 — A code-defined catalogue of agents, with per-organisation settings in the database.**
The list of agents (key, description, accountable owner role, the tools each may use) lives in
code (`app/modules/agents/catalogue.py`), so a new AI feature cannot exist without being listed.
The database stores only an organisation's **overrides**, in table `agent_settings` (one row per
tenant and agent key, created on first change): `enabled`, `monthly_token_budget`,
`allowed_tools` (a subset of the catalogue's tools), `updated_by`, `version`. A missing row means
the defaults (D6). Forced RLS and a tenant policy, like every tenant table.

**D2 — One choke point: a governed model, wrapped at the four call sites.**
`governed(model, session, tenant_id, agent_key)` returns an object with the same interface as
`ChatModel`. Before **every** `reply()` it checks, in this order: the platform switch (D4), the
agent's `enabled`, the month's token total against the budget. After the reply it records the
tokens used. It also (a) offers the model only the allowed tools and (b) removes any tool call
the model makes that is not allowed, and counts it. The four services wrap the model they
receive in one line each, so the BP-10 evaluation harness (which plays those services) exercises
the governance too, with no extra wiring.

**D3 — Budget in tokens, not money (this ADR's recommendation).** Tokens are what the provider
reports for every answer (`ModelReply.usage`); money needs a price table that changes (today
`CRM_AI_INPUT_PRICE_PER_MILLION` defaults to 0). The cap is **input + output tokens per calendar
month (UTC) per organisation and agent**. A running total is kept in `agent_usage` (tenant,
agent, month, input tokens, output tokens, calls), updated with one atomic
`INSERT ... ON CONFLICT DO UPDATE` so concurrent calls cannot lose counts. BP-09 will add the
per-call `ai_usage` table with estimated money; the monthly total here stays the enforcement
source. At 80 % of the budget the organisation's admins get a notification (once per month and
agent); at 100 % new calls are refused until the next month or until an admin raises the cap.
A single call may overshoot the cap slightly (the check is before the call, the tokens are known
after); that is accepted and documented.

**D4 — Two switches.** (1) **Per organisation and agent:** an admin turns an agent off in the
CRM (audited, notifies the other admins). (2) **Platform-wide:** `CRM_AI_DISABLED=true` in the
environment refuses every AI call for every organisation, without touching the database — the
emergency switch for a leaked key or a runaway, effective on the next call after a restart. Off
means off for the *next model call*: a conversation already in progress stops at its next step,
stored messages stay, and nothing half-done remains because AI features only create proposals
or text (ADR 0014).

**D5 — What the person sees when an agent is off or over budget.**
- Staff assistant, portal assistant, knowledge answers: the existing "assistant not available"
  answer (HTTP 503, code `agent_unavailable`) with a plain sentence; over budget uses code
  `agent_budget_reached`.
- Public website chat: a **fixed, friendly sentence** in the normal reply (not an error), so the
  page keeps working: "Our chat assistant is resting right now. Please leave a message through
  our contact form or call us, and an advisor will get back to you." (text to be confirmed,
  question 3). No lead can be saved while it is off.

**D6 — Defaults and who may change them.** With no row, an agent is **on** with the default
budget `CRM_AGENT_DEFAULT_MONTHLY_TOKENS` (proposed 2,000,000 per agent and organisation; 0 would
mean unlimited and is refused in production). Reading the registry and usage needs the new
permission `agent:read` (tenant admins and sales managers); changing a switch, budget or tool
list needs `agent:manage` (tenant admins only). The tenant always comes from the verified token.
Every change is written to the audit log (`agent.updated`) in the same transaction.

**D7 — API and screens.** `GET /api/v1/agents` (the catalogue joined with this organisation's
settings and this month's usage), `GET /api/v1/agents/{key}`, `PATCH /api/v1/agents/{key}`
(enabled, budget, allowed tools; version check; unknown tools refused). A page "AI agents" under
Automation: a row per agent with owner, on/off switch, usage bar and budget. Nothing about
agents is exposed to portal users or the public.

**D8 — Privacy and metrics.** `agent_usage` holds counts only, no prompts and no answers.
Prometheus gets `ai_refusals_total{agent,reason}` and `ai_dropped_tool_calls_total{agent}` with
**no tenant label** (the existing privacy rule).

## 3. What this does not do

- It does not price the tokens or show money (BP-09).
- It does not rate-limit individual people (existing per-user limits stay) or screen content
  (BP-21).
- It does not govern the CRM MCP server: that is an external client using a person's own
  permissions (ADR 0015), not a CRM-hosted agent.
- It does not stop a provider outage; that stays `AssistantUnavailableError`.

## 4. Consequences

- New module `agents` (tables `agent_settings`, `agent_usage`; migration 0043; RLS guard test
  covers them), small edits at four call sites, one new setting group, two permissions.
- If a request fails *after* a model call and the request transaction rolls back, that call's
  tokens are not counted. The monthly cap can therefore be under-counted by failed requests; the
  provider's own spend limit remains the final backstop (documented in the operations notes).
- Tool narrowing is only a restriction: an admin can remove tools, never add one the code does
  not offer.

## 5. Steps (each stops for review)

| Step | What | Size |
|---|---|---|
| **AG0** | This ADR + phase plan (documents only) | S |
| **AG1** | Module `agents`: catalogue, tables with forced RLS, settings and usage services, permissions; tests first (defaults, atomic usage, tenant isolation, role denial) | M |
| **AG2** | The governed model on the four call sites; switch, budget, tool filtering, platform switch; evaluation cases in the BP-10 harness (agent off → refused, over budget → refused, disallowed tool dropped) | M |
| **AG3** | API (`/agents`), audit, 80 % notification and switch events | M |
| **AG4** | Admin page, Playwright journey, docs, full runs, pull request | M |

Acceptance: with an agent switched off or over budget, none of the four features reaches the
model (proven by a model that fails the test if called); a tenant admin can switch, cap and
narrow an agent from the page; another organisation never sees or affects it; every change is
audited; the full test suites and the evaluation scorecard stay green.

## 6. Questions for the owner

1. **Budget unit.** Tokens now, money later through BP-09? *Recommended: yes.*
2. **Default.** On, with a default of 2,000,000 tokens per agent per organisation per month — or
   should a new agent start **off** until an admin enables it? *Recommended: on with the
   default cap (nothing changes for today's features).*
3. **Public chat text** when off (D5): is the sentence right, and is there a contact form or phone
   number it should name?
4. **Who switches.** Tenant admins only for changes, sales managers may read (D6)? *Recommended: yes.*
5. **Platform switch** `CRM_AI_DISABLED` (D4) — keep? *Recommended: yes.*
